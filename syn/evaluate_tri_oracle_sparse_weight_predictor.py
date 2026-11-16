"""Test partial weight reads before high-rate feed-forward pruning."""

import argparse
from collections import Counter
import json
from pathlib import Path
import time

from evaluate_tri_oracle_same_count_mask import (
    ARCHIVE, BENCHMARK, HIGH_RATE, LAYERS, REPORT, ROOT, TORCH, combined, digest, exact_budget_mask,
)
from tri_oracle_integer_reference import _dot, _quantize, _requantize
from verify_tri_oracle_full_down_code_score import verified_rows


MODES = ("high_rate_magnitude", "sparse_three_sigma", "sparse_top64", "sparse_top512")
TOP_COUNT = {"sparse_top64": 64, "sparse_top512": 512}
REFERENCE = ROOT / "records/tri_oracle_prompt_mask_rates.json"


def probe(reference, activation, norm, stats, mode):
    """Estimate a [M,K] gated magnitude using only selected features.

    M indexes retained prompt rows, H hidden features, and K intermediate
    feed-forward channels. activation and norm are the original [M,H]
    projection inputs and pre-scale predictor codes from the reference.
    Return the estimated magnitude [M,K] and per-row feature count [M].
    """
    codes, _ = _quantize(activation, per_row=True)  # [M,H], same signed8 inputs as the full dots
    if mode == "sparse_three_sigma":
        selected = norm.abs() > 768  # [M,H], documented three-sigma selection
    else:
        wanted = TORCH.full((len(codes), 1), TOP_COUNT[mode], device=codes.device, dtype=TORCH.int64)  # [M,1]
        selected = exact_budget_mask(-codes.to(TORCH.int32).abs(), wanted)  # [M,H], largest input codes
    partial = codes.masked_fill(~selected, 0)  # [M,H], zero unprobed inputs for reference arithmetic
    gate = _requantize(_dot(partial, reference.gate), stats["gate_shift"][:, None], 16)  # [M,K]
    up = _requantize(_dot(partial, reference.up), stats["up_shift"][:, None], 16)  # [M,K]
    product = reference.silu_response[gate + 32768] * up  # [M,K], partial signed gate/up products
    shift = TORCH.full_like(stats["down_shift"][:, None], 8)  # [M,1], existing fixed-point format
    return _requantize(product, shift, 16).abs(), selected.sum(1)


def install(item, projection, index, codebook, context):
    combined.configure(item, projection, index, codebook, context)
    baseline = item.reference.evaluate
    # The archive supplies the calibrated signed8 down weights [H,K] and
    # per-output exponents [H,1]. The first prompt row keeps its scalar scale.
    saved = TORCH.load(codebook, weights_only=True, map_location="cpu")
    trained = saved["codes"].to(projection.down_proj.weight.device)  # [H,K]
    scale = saved["scale"].to(trained.device).T  # [1,H]

    def evaluate(activation, residual, **settings):
        # The pair of [M,H] activations and residuals comes from the existing
        # prompt decoder. The archived computation returns [M,H] integer
        # accumulations, [M,H] dequantized outputs and exact predictor statistics.
        first = item.decoder.prefill_active and context["calls"][index] == 0
        raw, values, stats = baseline(activation, residual, **settings)
        mode = context["mode"]
        if mode is None or not item.decoder.prefill_active:
            return raw, values, stats
        assert settings["prune"]
        previous_count = stats["skip_count"].long()[:, None]  # [M,1], archived count for the first row
        reference = item.reference
        products = combined.gated_codes(reference, activation, stats)  # [M,K], full products for replay
        budget = previous_count if first else TORCH.full_like(previous_count, products.shape[1] * HIGH_RATE // 100)
        if mode == "high_rate_magnitude":
            score = products.abs()  # [M,K], after-compute diagnostic
            # Reproduce the earlier high-rate replay's archived first-row selection.
            mask = exact_budget_mask(score, budget)  # [M,K]
            norm = stats["norm_codes"]  # [M,H]
            outliers = norm.abs() > 768  # [M,H]
            signs = (TORCH.where(norm < 0, -1, 1) * outliers).to(TORCH.int8)  # [M,H]
            gate = _dot(signs, reference.gate_sign)  # [M,K]
            up = _dot(signs, reference.up_sign).abs()  # [M,K]
            prior = ((stats["outlier_count"][:, None] > 0) & (gate <= settings["gate_threshold"])
                     & (up <= settings["up_window"]))  # [M,K]
            assert TORCH.equal(prior.sum(1, keepdim=True), previous_count)
            context["changed_selections"] += int((mask & ~prior).sum())
        elif first:
            # The protection of the first prompt position is part of this
            # candidate convention. Leave those recorded sums intact.
            context["budget"] += int(previous_count.sum())
            context["used"] += int(previous_count.sum())
            context["opportunities"] += products.numel()
            return raw, values, stats
        else:
            score, features = probe(reference, activation, stats["norm_codes"], stats, mode)  # [M,K], [M]
            mask = exact_budget_mask(score, budget)  # [M,K]
            h, k = activation.shape[1], products.shape[1]
            kept = k - budget[:, 0]  # [M], retained channels per row
            context["probe_feature_events"] += int(features.sum())
            context["probe_bytes"] += int((2 * features * k).sum())
            context["followup_bytes_with_per_row_reuse"] += int((kept * (3 * h - 2 * features)).sum())
            context["followup_bytes_without_per_row_reuse"] += int((kept * 3 * h).sum())
            context["dense_reference_bytes"] += len(products) * 3 * h * k
        context["budget"] += int(budget.sum())
        context["used"] += int(mask.sum())
        context["opportunities"] += mask.numel()
        context["high_budget_rows"] += 0 if first else len(products)

        weights = reference.down if first else trained  # [H,K]
        exponent = reference.down_exponent if first else scale  # scalar or [1,H]
        shift = stats["down_shift"][:, None]  # [M,1]
        wide = _requantize(products, shift, 16)  # [M,K], original down input before saturation
        base = wide.clamp(-128, 127)  # [M,K], original signed8 primary plane
        down = base.masked_fill(mask, 0).to(TORCH.int8)  # [M,K], apply candidate skip
        raw = _dot(down, weights)  # [M,H], signed32 primary sums
        if combined.LATE[0] <= index < combined.LATE[1]:
            delta = (wide - base).clamp(-128, 127).masked_fill(mask, 0).to(TORCH.int8)  # [M,K]
            affected = delta.ne(0).any(dim=1)  # [M], rows needing the existing correction
            if bool(affected.any()):
                raw[affected] += _dot(delta[affected], weights)  # [D,H], selected residual sums
        gain = stats["up_gain_bits"][:, None]  # [M,1], stored gain
        values = TORCH.ldexp(raw.float(), exponent + shift - 8 - gain)  # [M,H], calibrated outputs
        return raw, values, stats

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
    pinned = BENCHMARK.read(REFERENCE)["evidence_sha256"]

    def previous(name):
        (path,) = (ROOT / entry for entry in pinned if entry.endswith(f"/prompt_mask_rate_trials/{name}"))
        assert digest(path) == pinned[str(path.relative_to(ROOT))]
        return path

    previous_inputs = previous("inputs.json")
    previous_predictions = previous("predictions.jsonl")
    held = BENCHMARK.read(previous_inputs)["questions"]
    assert len(held) == len({labels[key]["imageId"] for key in held}) == 67
    lines = previous_predictions.read_text().splitlines()
    assert [json.loads(line)["questionId"] for line in lines] == held
    controls = {row["questionId"]: row for line in lines if (row := json.loads(line))}
    assert digest(ARCHIVE) == BENCHMARK.read(REPORT)["evidence_sha256"][str(ARCHIVE.relative_to(ROOT))]
    archived = {row["questionId"]: row for row in verified_rows(ARCHIVE, sorted(labels))}

    model, processor, tokenizer = combined.load_model()
    images = BENCHMARK.load_images(dataset)
    original = BENCHMARK.ALL_ATTENTION_FUNCTIONS["sdpa"]
    decoder = BENCHMARK.CompactDecoder(model, original, tuple(BENCHMARK.read(joint)["local_ratio"]))
    first, ordinary = (BENCHMARK.read(path)["layers"] for path in policies)
    layers = decoder.language.layers
    items = [BENCHMARK.FeedForward(layer, decoder, a, b)
             for layer, a, b in zip(layers, first, ordinary, strict=True)]
    context = {}
    for index, (item, layer, codebook) in enumerate(zip(items, layers, codebooks, strict=True)):
        install(item, layer.mlp, index, codebook, context)

    counters = ("budget", "used", "opportunities", "high_budget_rows", "changed_selections", "probe_feature_events",
                "probe_bytes", "followup_bytes_with_per_row_reuse", "followup_bytes_without_per_row_reuse",
                "dense_reference_bytes")
    out.mkdir(parents=True, exist_ok=True)
    manifest = out / "inputs.json"
    BENCHMARK.write(manifest, {
        "checkpoint_revision": BENCHMARK.REVISION, "questions": held, "modes": MODES,
        "prompt": BENCHMARK.PROMPT, "high_rate_percent_for_nonfirst_prompt_rows": HIGH_RATE,
        "fixed_top_k": TOP_COUNT, "input_sha256": setup["input_sha256"] | {
            str(path): digest(path) for path in (
                ARCHIVE, REPORT, REFERENCE, previous_inputs, previous_predictions, Path(__file__).resolve())},
    })

    def answer(key, embeddings, image_start, mode):
        # Both modes start from the same [1,T,H] checkpoint embeddings.
        context.update(mode=mode, calibrated=True, clipping=True, verify_raw=False, calls=[0]*LAYERS,
                       weight_rows=[0]*LAYERS, clip_rows=[0]*LAYERS, workload=Counter())
        context.update(dict.fromkeys(counters, 0))
        for item in items:
            item.begin(True, True)
        tokens = combined.decode(decoder, embeddings, image_start, BENCHMARK.MODE, tokenizer.eos_token_id)
        prediction = BENCHMARK.normalize(tokenizer.decode(tokens, skip_special_tokens=True))
        skipped = sum(item.prefill_skipped + item.decode_skipped for item in items)
        return {
            "questionId": key, "tokens": tokens, "prediction": prediction, "skipped_channels": skipped,
            "workload": dict(context["workload"]), **{name: context[name] for name in counters},
        }

    BENCHMARK.ALL_ATTENTION_FUNCTIONS["sdpa"] = decoder.attend
    comparisons = {mode: Counter() for mode in MODES}
    work = {mode: Counter() for mode in MODES}
    predictions = out / "predictions.jsonl"
    try:
        with predictions.open("x", buffering=1) as stream:
            for index, key in enumerate(held, 1):
                assert BENCHMARK.host_available() >= 9 * combined.GIB
                label = labels[key]
                encoded = combined.encode(model, processor, images[label["imageId"]], label["question"])
                control = answer(key, *encoded, None)
                assert {name: control[name] for name in archived[key]} == archived[key]
                old = control["prediction"] == label["answer"]
                candidates = {}
                for mode in MODES:
                    result = answer(key, *encoded, mode)
                    if mode == "high_rate_magnitude":
                        expected = controls[key]["candidates"][mode]
                        assert {name: result[name] for name in expected} == expected, key
                    assert result["used"] == result["budget"] > 0
                    new = result["prediction"] == label["answer"]
                    comparisons[mode].update(baseline=int(old), candidate=int(new), gained=int(new and not old),
                                             lost=int(old and not new), first_token_changed=int(
                                                 result["tokens"][0] != control["tokens"][0]))
                    work[mode].update({name: result[name] for name in counters})
                    candidates[mode] = result
                stream.write(json.dumps({"questionId": key, "baseline": control, "candidates": candidates}) + "\n")
                if index % 8 == 0 or index == len(held):
                    print("SPARSE_WEIGHT_PROGRESS", index, len(held), comparisons, flush=True)
    finally:
        BENCHMARK.ALL_ATTENTION_FUNCTIONS["sdpa"] = original
    result = {
        "state": "sparse_weight_predictor_held_panel_completed", "questions": len(held),
        "baseline_outputs_reproduced": len(held), "magnitude_outputs_reproduced": len(held),
        "comparisons": comparisons, "work": work, "device": TORCH.cuda.get_device_name(),
        "peak_device_bytes": TORCH.cuda.max_memory_allocated(), "elapsed_seconds": time.monotonic() - started,
        "inputs_sha256": digest(manifest), "predictions_sha256": digest(predictions),
    }
    BENCHMARK.write(out / "receipt.json", result)
    print("SPARSE_WEIGHT_COMPLETE", json.dumps(result), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", type=lambda name: Path(name).resolve())
    options = parser.parse_args()
    assert options.out.is_relative_to(ROOT / ".cache")
    run(options.out)
