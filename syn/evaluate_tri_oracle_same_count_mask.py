"""Compare channel selection at the current and higher prompt skip budgets."""

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import time

from evaluate_tri_oracle_prompt_arithmetic import ARCHIVE, BENCHMARK, REPORT, ROOT, TORCH, combined, digest
from tri_oracle_integer_reference import _dot, _requantize
from verify_tri_oracle_full_down_code_score import verified_rows


MODES = ("activation_oracle", "calibrated_sign_rank", "high_rate_magnitude")
HIGH_RATE = 58
LAYERS = 22
BINS = 9
CELLS = BINS * BINS
SOURCE = ROOT / "records/tri_oracle_prompt_arithmetic.json"


def bin_index(gate, up_abs, outliers):
    """Map the original [M,K] sign margins and [M] counts to [M,K] bins."""
    total = outliers[:, None].clamp_min(1)  # [M,1], number of outliers in each prompt row
    gate_bin = ((gate + total) * 4 // total).clamp(0, BINS - 1)  # [M,K]
    up_bin = (up_abs * 8 // total).clamp(0, BINS - 1)  # [M,K]
    return gate_bin * BINS + up_bin  # [M,K], paired gate and absolute-up bins


def exact_budget_mask(score, count):
    """Select [M,K] channels from scores [M,K] and requested counts [M,1]."""
    order = TORCH.argsort(score, dim=-1, stable=True)  # [M,K], ascending score then channel index
    ranks = TORCH.arange(score.shape[1], device=score.device)[None, :]  # [1,K]
    chosen = TORCH.empty_like(score, dtype=TORCH.bool).scatter_(1, order, ranks < count)  # [M,K]
    assert TORCH.equal(chosen.sum(1, keepdim=True), count)
    return chosen


def install(item, projection, index, codebook, context):
    combined.configure(item, projection, index, codebook, context)
    archived_evaluate = item.reference.evaluate
    # H and K are hidden and intermediate dimensions. The frozen archive
    # provides calibrated signed8 weights [H,K] and exponents [H,1].
    saved = TORCH.load(codebook, weights_only=True, map_location="cpu")
    weights = saved["codes"].to(projection.down_proj.weight.device)  # [H,K]
    exponents = saved["scale"].to(weights.device).T  # [1,H], per hidden output

    def evaluate(activation, residual, **settings):
        # The wrapper supplies retained normalized activations and pre-scale
        # residuals [M,H]. The archived integer projection returns two [M,H]
        # outputs and a table of exact per-row or per-input statistics.
        first = item.decoder.prefill_active and context["calls"][index] == 0
        raw, ordinary, stats = archived_evaluate(activation, residual, **settings)
        mode = context["mode"]
        if not item.decoder.prefill_active or mode is None:
            return raw, ordinary, stats
        assert settings["prune"]
        norm = stats["norm_codes"]  # [M,H], pre-scale normalized residual
        selected = norm.abs() > 768  # [M,H], three-sigma outliers
        signs = (TORCH.where(norm < 0, -1, 1) * selected).to(TORCH.int8)  # [M,H]
        gate = _dot(signs, item.reference.gate_sign)  # [M,K], signed agreement
        up = _dot(signs, item.reference.up_sign).abs()  # [M,K], absolute agreement
        n = stats["outlier_count"]  # [M], exact outlier counts
        skip = ((n[:, None] > 0) & (gate <= settings["gate_threshold"])
                & (up <= settings["up_window"]))  # [M,K], archived predictor
        assert TORCH.equal(skip.sum(1, dtype=TORCH.int32), stats["skip_count"])
        products = combined.gated_codes(item.reference, activation, stats)  # [M,K], signed16 products
        if mode == "fit":
            # Deterministically sample rows and channels for calibration, with
            # no answer labels. Normalize each row to compare its channels.
            stride = index % 16
            shape_region = (slice(0, None, 8), slice(stride, None, 16))
            signal = products[shape_region].abs().float()  # [S,C], sampled rows and channels
            sample_n = n[::8]  # [S], outlier counts for the sampled rows
            relative = signal / signal.mean(1, keepdim=True).clamp_min(1.0)  # [S,C]
            target = (relative * 256).round().clamp_max(4095).to(TORCH.int64)  # [S,C]
            bins = bin_index(gate[shape_region], up[shape_region], sample_n).long().flatten()  # [S*C]
            valid = (sample_n[:, None] > 0).expand_as(signal).flatten()  # [S*C]
            target = target.flatten()[valid]  # [V], finite calibration entries
            indices = bins[valid]  # [V], matching bin IDs
            context["bin_sums"][index].scatter_add_(0, indices, target)
            context["bin_counts"][index].scatter_add_(0, indices, TORCH.ones_like(indices))
            return raw, ordinary, stats

        if mode in ("activation_oracle", "high_rate_magnitude"):
            score = products.abs()  # [M,K], available after gate and up calculation
        elif mode == "calibrated_sign_rank":
            bins = bin_index(gate, up, n).long()  # [M,K], derived without gated magnitudes
            score = context["rank_table"][index][bins].to(TORCH.int32) * 4097 + up  # [M,K]
        else:
            assert mode == "check_reconstruction"
            score = None

        budget = skip.sum(1, keepdim=True)  # [M,1], existing predictor budget for this activation
        if mode == "high_rate_magnitude" and not first:
            budget = TORCH.full_like(budget, products.shape[1] * HIGH_RATE // 100)  # [M,1]
            context["high_budget_rows"] += len(products)
        mask = skip if score is None else exact_budget_mask(score, budget)  # [M,K]
        context["budget"] += int(budget.sum())
        context["used"] += int(mask.sum())
        context["changed_selections"] += int((mask & ~skip).sum())
        context["opportunities"] += mask.numel()

        # Recreate the archived integer primary and clipping paths, with
        # only channel selection held different. The first prompt row uses
        # the original scalar weight exponent and original signed8 weights.
        weights_here = item.reference.down if first else weights  # [H,K]
        scale = item.reference.down_exponent if first else exponents  # scalar or [1,H]
        shift = stats["down_shift"][:, None]  # [M,1], configured down shift
        wide = _requantize(products, shift, 16)  # [M,K], pre-saturation integer codes
        primary = wide.clamp(-128, 127)  # [M,K], signed8 primary codes before mask
        lean = primary.masked_fill(mask, 0).to(TORCH.int8)  # [M,K]
        sums = _dot(lean, weights_here)  # [M,H], signed32 primary accumulations
        if combined.LATE[0] <= index < combined.LATE[1]:
            delta = (wide - primary).clamp(-128, 127).masked_fill(mask, 0).to(TORCH.int8)  # [M,K]
            active = delta.ne(0).any(dim=1)  # [M], rows with a clipping residual
            if bool(active.any()):
                sums[active] += _dot(delta[active], weights_here)  # [D,H] selected row corrections
        gain = stats["up_gain_bits"][:, None]  # [M,1], archived gain exponent
        values = TORCH.ldexp(sums.float(), scale + shift - 8 - gain)  # [M,H]
        if mode == "check_reconstruction":
            assert TORCH.equal(raw, sums) and TORCH.equal(ordinary, values), index
        return sums, values, stats

    item.reference.evaluate = evaluate


@TORCH.inference_mode()
def run(out):
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    assert BENCHMARK.host_available() >= 10 * combined.GIB
    assert TORCH.cuda.mem_get_info()[0] >= 12 * combined.GIB
    TORCH.set_num_threads(3)
    TORCH.set_num_interop_threads(1)
    TORCH.manual_seed(0)
    TORCH.cuda.set_per_process_memory_fraction(0.78)
    TORCH.cuda.reset_peak_memory_stats()
    started = time.monotonic()
    dataset, labels, codebooks, joint, policies, _, setup = combined.prepare()
    report = BENCHMARK.read(REPORT)
    prior = BENCHMARK.read(SOURCE)
    prior_config, = (ROOT / name for name in prior["evidence_sha256"]
                     if name.endswith("/matched_prompt_arithmetic/inputs.json"))
    assert digest(prior_config) == prior["evidence_sha256"][str(prior_config.relative_to(ROOT))]
    assert digest(ARCHIVE) == report["evidence_sha256"][str(ARCHIVE.relative_to(ROOT))]
    archived = {row["questionId"]: row for row in verified_rows(ARCHIVE, sorted(labels))}
    held = BENCHMARK.read(prior_config)["questions"]
    assert len(held) == len({labels[key]["imageId"] for key in held}) == 67
    held_images = {labels[key]["imageId"] for key in held}
    fit = {}
    for key in sorted(labels, key=lambda key: sha256(("sign-rank-fit-v1:" + key).encode()).digest()):
        image = labels[key]["imageId"]
        if image in setup["excluded_source_panel_images"]:
            fit.setdefault(image, key)
            if len(fit) == 16:
                break
    assert len(fit) == 16 and not held_images.intersection(fit)

    model, processor, tokenizer = combined.load_model()
    images = BENCHMARK.load_images(dataset)
    original = BENCHMARK.ALL_ATTENTION_FUNCTIONS["sdpa"]
    decoder = BENCHMARK.CompactDecoder(model, original, tuple(BENCHMARK.read(joint)["local_ratio"]))
    first, ordinary = (BENCHMARK.read(path)["layers"] for path in policies)
    layers = decoder.language.layers
    items = [BENCHMARK.FeedForward(layer, decoder, a, b)
             for layer, a, b in zip(layers, first, ordinary, strict=True)]
    context = {}
    # [L,B] integer totals, where L is layer and B is the joint sign bin.
    context["bin_sums"] = TORCH.zeros((LAYERS, CELLS), dtype=TORCH.int64, device="cuda")
    context["bin_counts"] = TORCH.zeros_like(context["bin_sums"])  # [L,B]
    for index, (item, layer, codebook) in enumerate(zip(items, layers, codebooks, strict=True)):
        install(item, layer.mlp, index, codebook, context)

    def embeddings_for(key):
        # [1,T,H] embeddings from a fixed image and question prompt.
        label = labels[key]
        return combined.encode(model, processor, images[label["imageId"]], label["question"])

    def answer(key, embeddings, image_start, mode):
        context.update(mode=mode, calibrated=True, clipping=True, verify_raw=False, calls=[0]*LAYERS,
                       weight_rows=[0]*LAYERS, clip_rows=[0]*LAYERS, workload=Counter(),
                       budget=0, used=0, changed_selections=0, opportunities=0, high_budget_rows=0)
        for item in items:
            item.begin(True, True)
        tokens = combined.decode(decoder, embeddings, image_start, BENCHMARK.MODE, tokenizer.eos_token_id)
        prediction = BENCHMARK.normalize(tokenizer.decode(tokens, skip_special_tokens=True))
        skipped = sum(item.prefill_skipped + item.decode_skipped for item in items)
        return {
            "questionId": key, "tokens": tokens, "prediction": prediction, "skipped_channels": skipped,
            "workload": dict(context["workload"]), "budget": context["budget"], "used": context["used"],
            "changed_selections": context["changed_selections"], "opportunities": context["opportunities"],
            "high_budget_rows": context["high_budget_rows"],
        }

    out.mkdir(parents=True, exist_ok=True)
    manifest = out / "inputs.json"
    BENCHMARK.write(manifest, {
        "checkpoint_revision": BENCHMARK.REVISION, "questions": held, "fit_questions": list(fit.values()),
        "prompt": BENCHMARK.PROMPT, "calibration_uses_labels": False, "modes": MODES,
        "high_rate_percent_for_nonfirst_prompt_rows": HIGH_RATE,
        "input_sha256": setup["input_sha256"] | {str(path): digest(path) for path in
            (ARCHIVE, REPORT, SOURCE, prior_config, Path(__file__).resolve())},
    })

    def assert_memory():
        assert BENCHMARK.host_available() >= 9 * combined.GIB

    BENCHMARK.ALL_ATTENTION_FUNCTIONS["sdpa"] = decoder.attend
    try:
        for key in fit.values():
            assert_memory()
            answer(key, *embeddings_for(key), "fit")
        sums = context["bin_sums"]  # [L,B], clipped relative magnitude units
        samples = context["bin_counts"]  # [L,B], label-free calibration counts
        totals = samples.sum(0)  # [B], pooled bin counts
        pooled = TORCH.where(totals > 0, sums.sum(0) / totals.clamp_min(1), 4095.0)  # [B], prior mean
        average = (sums + pooled[None, :] * 32) / (samples + 32)  # [L,B], shrink sparse bins
        ranks = TORCH.argsort(average, dim=1, stable=True)  # [L,B], bins ordered by mean magnitude
        table = TORCH.empty_like(ranks).scatter_(1, ranks, TORCH.arange(CELLS, device="cuda").expand_as(ranks))
        context["rank_table"] = table  # [L,B], usable as a sign-score lookup
        ranking = out / "sign_rank_table.json"
        BENCHMARK.write(ranking, {"rank_by_layer_and_bin": table.tolist(), "samples": samples.tolist()})
        print("SAME_COUNT_FIT_COMPLETE", len(fit), int(samples.sum()), flush=True)

        results = {mode: Counter() for mode in MODES}
        activity = {mode: Counter() for mode in MODES}
        predictions = out / "predictions.jsonl"
        with predictions.open("x", buffering=1) as stream:
            for index, key in enumerate(held, 1):
                assert_memory()
                inputs = embeddings_for(key)
                baseline = answer(key, *inputs, None)
                assert {part: baseline[part] for part in archived[key]} == archived[key], key
                if index == 1:
                    check = answer(key, *inputs, "check_reconstruction")
                    assert {part: check[part] for part in archived[key]} == archived[key]
                reference = baseline["prediction"] == labels[key]["answer"]
                candidates = {}
                for mode in MODES:
                    row = answer(key, *inputs, mode)
                    assert row["used"] == row["budget"] > 0
                    result = row["prediction"] == labels[key]["answer"]
                    results[mode].update(baseline=int(reference), candidate=int(result),
                                         gained=int(result and not reference), lost=int(reference and not result),
                                         first_token_changed=int(baseline["tokens"][0] != row["tokens"][0]))
                    activity[mode].update({key: row[key] for key in
                                          ("budget", "used", "changed_selections", "opportunities", "high_budget_rows")})
                    candidates[mode] = row
                stream.write(json.dumps({"questionId": key, "baseline": baseline, "candidates": candidates}) + "\n")
                if index % 8 == 0 or index == len(held):
                    print("SAME_COUNT_PROGRESS", index, len(held), results, flush=True)
    finally:
        BENCHMARK.ALL_ATTENTION_FUNCTIONS["sdpa"] = original
    result = {
        "state": "same_count_prompt_masks_host_panel_completed", "questions": len(held),
        "calibration_images": len(fit), "calibration_entries": int(samples.sum()),
        "baseline_outputs_reproduced": len(held), "comparisons": results, "activity": activity,
        "device": TORCH.cuda.get_device_name(), "peak_device_bytes": TORCH.cuda.max_memory_allocated(),
        "elapsed_seconds": time.monotonic() - started, "inputs_sha256": digest(manifest),
        "rank_table_sha256": digest(ranking), "predictions_sha256": digest(predictions),
    }
    BENCHMARK.write(out / "receipt.json", result)
    print("SAME_COUNT_COMPLETE", json.dumps(result), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", type=lambda value: Path(value).resolve())
    options = parser.parse_args()
    assert options.out.is_relative_to(ROOT / ".cache")
    run(options.out)
