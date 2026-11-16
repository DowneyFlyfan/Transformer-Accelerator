"""Compare weight and activation precision in the same late down projections."""

import argparse
from collections import Counter
from hashlib import file_digest
import json
from pathlib import Path
import time

import combined
from verify_tri_oracle_full_down_code_score import verified_rows
from tri_oracle_integer_reference import _dot, _requantize


ROOT = combined.ROOT
DATA = combined.DATA
BENCHMARK = combined.benchmark
TORCH = combined.torch
REFINE_BITS = 6
MODES = ("weight_plane", "exact_gated")
REPORT = ROOT / "records/tri_oracle_full_calibrated_clipped_accuracy.json"
ARCHIVE = DATA / "full_calibrated_clip/predictions.jsonl"


def digest(path):
    with path.open("rb") as source:
        return file_digest(source, "sha256").hexdigest()


def install_refinement(item, projection, index, codebook, context):
    """Wrap one feed-forward layer with the paired test's late prompt substitution."""
    combined.configure(item, projection, index, codebook, context)
    if not combined.LATE[0] <= index < combined.LATE[1]:
        return
    ordinary_evaluate = item.reference.evaluate
    # H is hidden width; K is the width of the intermediate feed-forward channels.
    # The archived codebook supplies the signed8 weights [H,K] and row exponents [H,1].
    # Checkpoint weights are the trained floating-point values [H,K].
    state = TORCH.load(codebook, weights_only=True, map_location="cpu")
    trained = projection.down_proj.weight
    exponents = state["scale"].to(trained.device)  # [H,1]
    coarse_weights = state["codes"].to(trained.device)  # [H,K]
    exact_codes = TORCH.ldexp(trained.float(), -exponents)  # [H,K], primary code units
    fine_unrounded = (exact_codes - coarse_weights) * (1 << REFINE_BITS)  # [H,K], residual code units
    fine_rounded = fine_unrounded.sign() * (fine_unrounded.abs() + 0.5).floor()  # [H,K], ties away
    assert bool(((fine_rounded >= -128) & (fine_rounded <= 127)).all())
    fine = fine_rounded.to(TORCH.int8).contiguous()  # [H,K], signed8 residual weights
    reconstructed = coarse_weights.float() + fine.float() / (1 << REFINE_BITS)  # [H,K], reconstructed units
    assert bool(((exact_codes - reconstructed).abs() <= (0.5 / (1 << REFINE_BITS))).all())
    context["plane_bytes"] += fine.numel()

    def evaluate(activation, residual, **settings):
        # Inputs activation and residual [M,H] are the retained token rows for
        # one call. The archived evaluator provides primary raw sums [M,H],
        # floating interpretations [M,H], and per-row arithmetic statistics.
        refine = (context["mode"] and item.decoder.prefill_active and context["calls"][index] != 0)
        raw, values, stats = ordinary_evaluate(activation, residual, **settings)
        if not refine:
            return raw, values, stats
        assert settings["prune"] and context["clipping"] and context["calibrated"]
        reference = item.reference
        norm = stats["norm_codes"]  # [M,H], pre-scale normalized residual codes
        outliers = norm.abs() > 768  # [M,H], original three-sigma selection
        signs = (TORCH.where(norm < 0, -1, 1) * outliers).to(TORCH.int8)  # [M,H]
        gate = _dot(signs, reference.gate_sign)  # [M,K], agreement scores
        up = _dot(signs, reference.up_sign)  # [M,K]
        skip = ((stats["outlier_count"][:, None] > 0)
                & (gate <= settings.get("gate_threshold", 0))
                & (up.abs() <= settings.get("up_window", 0)))  # [M,K], unchanged skip mask
        assert TORCH.equal(skip.sum(dim=1, dtype=TORCH.int32), stats["skip_count"])
        gated = combined.gated_codes(reference, activation, stats)  # [M,K], signed16 gate/up products
        shift = stats["down_shift"][:, None]  # [M,1], archived down-input shift
        wide = _requantize(gated, shift, 16)  # [M,K], rounded in original down projection units
        primary = wide.clamp(-128, 127)  # [M,K], original signed8 input before mask
        delta = (wide - primary).clamp(-128, 127).masked_fill(skip, 0).to(TORCH.int8)  # [M,K]
        coarse = primary.masked_fill(skip, 0).to(TORCH.int8)  # [M,K], original primary input
        active = delta.ne(0).any(dim=1)  # [M], rows with clipping restoration
        selected = delta[active]  # [A,K], A rows needing clipping restoration
        gain = stats["up_gain_bits"][:, None]  # [M,1], archived gain compensation
        if context["mode"] == "exact_gated":
            # Start with the full signed16 [M,K] gated values, before the
            # original down shift. Saturating high=128 requires a carry.
            retained = gated.masked_fill(skip, 0)  # [M,K], original pruning
            low = (retained + 128).remainder(256) - 128  # [M,K], signed8 digit
            upper = (retained - low) >> 8  # [M,K], high digit, including 128
            high = upper.clamp(max=127)  # [M,K], signed8 high digit
            carry = upper - high  # [M,K], one only on the positive endpoint range
            assert bool(((high >= -128) & (carry >= 0) & (carry <= 1)).all())
            assert TORCH.equal(retained, low + 256 * (high + carry))
            full_sum = TORCH.zeros_like(raw, dtype=TORCH.int64)  # [M,H]
            exact_rows = 0
            for digit, multiplier in ((low, 1), (high, 256), (carry, 256)):
                uses_digit = digit.ne(0).any(dim=1)  # [M], active rows
                if bool(uses_digit.any()):
                    gathered = digit[uses_digit].to(TORCH.int8)  # [D,K], D rows using this digit
                    digit_sum = _dot(gathered, coarse_weights)  # [D,H], signed32 dot sums
                    full_sum[uses_digit] += digit_sum.to(TORCH.int64) * multiplier
                    exact_rows += len(gathered)
            scale = exponents.T - 8 - gain  # [M,H], full gated code units
            values = TORCH.ldexp(full_sum.float(), scale)  # [M,H]
            context["extra_rows"] += exact_rows - len(coarse) - len(selected)
            context["maximum_sum"] = max(context["maximum_sum"], int(full_sum.abs().max()))
            return raw, values, stats

        correction = _dot(coarse, fine).to(TORCH.int64)  # [M,H], residual-weight accumulations
        if len(selected):
            correction[active] += _dot(selected, fine)
        aligned = raw.to(TORCH.int64) * (1 << REFINE_BITS) + correction  # [M,H], exact aligned sums
        scale = exponents.T + shift - 8 - gain - REFINE_BITS  # [M,H], one effective scale per output
        values = TORCH.ldexp(aligned.float(), scale)  # [M,H], candidate hidden contributions
        context["extra_rows"] += len(coarse) + len(selected)
        context["maximum_sum"] = max(context["maximum_sum"], int(aligned.abs().max()))
        # Keep the archived raw representation for downstream diagnostics.
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
    start = time.monotonic()
    dataset, labels, codebooks, joint, policies, _, setup = combined.prepare()
    record = BENCHMARK.read(REPORT)
    assert digest(ARCHIVE) == record["evidence_sha256"][str(ARCHIVE.relative_to(ROOT))]
    saved = {entry["questionId"]: entry for entry in verified_rows(ARCHIVE, sorted(labels))}
    chosen = {}
    for key in setup["questions"]:
        chosen.setdefault(labels[key]["imageId"], key)
    questions = sorted(chosen.values())
    assert len(questions) == len(chosen) == 67
    assert not chosen.keys() & set(setup["excluded_source_panel_images"])

    model, processor, tokenizer = combined.load_model()
    images = BENCHMARK.load_images(dataset)
    original = BENCHMARK.ALL_ATTENTION_FUNCTIONS["sdpa"]
    decoder = BENCHMARK.CompactDecoder(model, original, tuple(BENCHMARK.read(joint)["local_ratio"]))
    a, b = (BENCHMARK.read(path)["layers"] for path in policies)
    layers = decoder.language.layers
    items = [BENCHMARK.FeedForward(layer, decoder, first, ordinary)
             for layer, first, ordinary in zip(layers, a, b, strict=True)]
    context = {"plane_bytes": 0}
    for index, (item, layer, codebook) in enumerate(zip(items, layers, codebooks, strict=True)):
        install_refinement(item, layer.mlp, index, codebook, context)

    out.mkdir(parents=True, exist_ok=True)
    predictions = out / "predictions.jsonl"
    benchmark_inputs = {
        "checkpoint_revision": BENCHMARK.REVISION, "questions": questions, "prompt": BENCHMARK.PROMPT,
        "refined_prefill_layers": list(range(*combined.LATE)), "residual_weight_fractional_bits": REFINE_BITS,
        "modes": MODES,
        "input_sha256": setup["input_sha256"] | {
            str(ARCHIVE): digest(ARCHIVE), str(REPORT): digest(REPORT),
            str(Path(__file__).resolve()): digest(Path(__file__)),
        },
    }
    BENCHMARK.write(out / "inputs.json", benchmark_inputs)

    def answer(key, embeddings, image_start, mode):
        # Initial image/text embeddings [1,T,H] are shared between paired
        # modes. Decoder outputs greedy token indices until stopping.
        context.update(mode=mode, calibrated=True, clipping=True, verify_raw=False,
                       calls=[0]*22, weight_rows=[0]*22, clip_rows=[0]*22,
                       workload=Counter(), extra_rows=0, maximum_sum=0)
        for item in items:
            item.begin(True, True)
        tokens = combined.decode(decoder, embeddings, image_start, BENCHMARK.MODE, tokenizer.eos_token_id)
        prediction = BENCHMARK.normalize(tokenizer.decode(tokens, skip_special_tokens=True))
        skipped = sum(item.prefill_skipped + item.decode_skipped for item in items)
        assert skipped > 0
        return {
            "questionId": key, "tokens": tokens, "prediction": prediction, "skipped_channels": skipped,
            "workload": dict(context["workload"]), "extra_rows": context["extra_rows"],
            "maximum_aligned_sum": context["maximum_sum"],
        }

    counts = {mode: Counter() for mode in MODES}
    candidate_extra_rows = {mode: 0 for mode in MODES}
    maximum_sum = {mode: 0 for mode in MODES}
    minimum_free_host = BENCHMARK.host_available()
    BENCHMARK.ALL_ATTENTION_FUNCTIONS["sdpa"] = decoder.attend
    try:
        with predictions.open("x", buffering=1) as stream:
            for index, key in enumerate(questions, 1):
                available = BENCHMARK.host_available()
                minimum_free_host = min(minimum_free_host, available)
                assert available >= 9 * combined.GIB, "Yield to current hardware jobs"
                label = labels[key]
                embeddings, image_start = combined.encode(model, processor, images[label["imageId"]], label["question"])
                control = answer(key, embeddings, image_start, None)
                assert {k: v for k, v in control.items() if k not in ("extra_rows", "maximum_aligned_sum")} == saved[key], key
                previous = control["prediction"] == label["answer"]
                candidates = {}
                for mode in MODES:
                    tested = answer(key, embeddings, image_start, mode)
                    correct = tested["prediction"] == label["answer"]
                    counts[mode].update(control=int(previous), refined=int(correct),
                                        gained=int(not previous and correct), lost=int(previous and not correct),
                                        first_token_changed=int(control["tokens"][0] != tested["tokens"][0]))
                    candidate_extra_rows[mode] += tested["extra_rows"]
                    maximum_sum[mode] = max(maximum_sum[mode], tested["maximum_aligned_sum"])
                    candidates[mode] = tested
                stream.write(json.dumps({"questionId": key, "baseline": control, "candidates": candidates}) + "\n")
                if index % 8 == 0 or index == len(questions):
                    print("LATE_DOWN_PRECISION_PROGRESS", index, len(questions), counts, flush=True)
    finally:
        BENCHMARK.ALL_ATTENTION_FUNCTIONS["sdpa"] = original
    assert all(values["refined"] - values["control"] == values["gained"] - values["lost"]
               for values in counts.values())
    result = {
        "state": "late_down_precision_host_panel_completed", "questions": len(questions),
        "baseline_outputs_reproduced": len(questions), "comparisons": dict(counts),
        "late_prefill_layers": list(range(*combined.LATE)),
        "additional_signed8_dot_rows": candidate_extra_rows,
        "extra_weight_code_bytes": {"weight_plane": context["plane_bytes"], "exact_gated": 0},
        "largest_absolute_aligned_sum": maximum_sum,
        "device": TORCH.cuda.get_device_name(), "peak_device_bytes": TORCH.cuda.max_memory_allocated(),
        "minimum_sampled_host_available_bytes": minimum_free_host, "elapsed_seconds": time.monotonic() - start,
        "inputs_sha256": digest(out / "inputs.json"), "predictions_sha256": digest(predictions),
    }
    BENCHMARK.write(out / "receipt.json", result)
    print("LATE_DOWN_PRECISION_COMPLETE", json.dumps(result), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=lambda value: Path(value).resolve())
    args = parser.parse_args()
    assert args.output.is_relative_to(ROOT / ".cache")
    run(args.output)
