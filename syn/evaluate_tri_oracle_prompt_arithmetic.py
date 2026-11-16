"""Localize the held-out accuracy gap with matched prompt arithmetic controls."""

import argparse
from collections import Counter
from hashlib import file_digest
import json
from pathlib import Path
import time

import combined
from tri_oracle_integer_reference import _dot
from verify_tri_oracle_full_down_code_score import verified_rows


ROOT, DATA, BENCHMARK, TORCH = combined.ROOT, combined.DATA, combined.benchmark, combined.torch
ARCHIVE = DATA / "full_calibrated_clip/predictions.jsonl"
REPORT = ROOT / "records/tri_oracle_full_calibrated_clipped_accuracy.json"
PREVIOUS = ROOT / "records/tri_oracle_late_down_precision.json"
MODES = ("late_float_down", "late_float_feedforward", "all_float_pruned", "all_float_unpruned")


def digest(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def install(item, projections, index, codebook, context):
    """Use the existing evaluator and mask on each retained prompt row."""
    combined.configure(item, projections, index, codebook, context)
    evaluate_archived = item.reference.evaluate

    def evaluate(activation, residual, **settings):
        # The archived wrapper passes activation and residual [M,H], where M
        # counts retained token rows and H indexes hidden features. raw and
        # values [M,H] hold the archived down projection in two representations.
        raw, values, stats = evaluate_archived(activation, residual, **settings)
        mode = context["mode"]
        late = combined.LATE[0] <= index < combined.LATE[1]
        if mode is None or not item.decoder.prefill_active or (mode.startswith("late_") and not late):
            return raw, values, stats
        assert settings["prune"] and context["calibrated"] and context["clipping"]
        # K indexes intermediate feed-forward channels. In the late-only
        # down diagnostic, gated_code is the original signed16 [M,K] and
        # gain [M,1] is the archived precision-compensation exponent.
        if mode == "late_float_down":
            gated_code = combined.gated_codes(item.reference, activation, stats)  # [M,K]
            gain = stats["up_gain_bits"][:, None]  # [M,1]
            gated = TORCH.ldexp(gated_code.float(), -8 - gain)  # [M,K], represented activation
        else:
            gate = projections.gate_proj(activation)  # [M,K], trained floating projection
            up = projections.up_proj(activation)  # [M,K], trained floating projection
            gated = projections.act_fn(gate) * up  # [M,K], trained smooth activation and gating
        assert gated.shape[0] == activation.shape[0]
        # norm [M,H] comes from the original pre-scale normalization. The
        # unchanged predictor supplies a skip mask [M,K] from sign scores.
        norm = stats["norm_codes"]  # [M,H]
        outlier = norm.abs() > 768  # [M,H]
        signs = (TORCH.where(norm < 0, -1, 1) * outlier).to(TORCH.int8)  # [M,H]
        gate_margin = _dot(signs, item.reference.gate_sign)  # [M,K]
        up_margin = _dot(signs, item.reference.up_sign)  # [M,K]
        skip = ((stats["outlier_count"][:, None] > 0)
                & (gate_margin <= settings["gate_threshold"])
                & (up_margin.abs() <= settings["up_window"]))  # [M,K]
        assert TORCH.equal(skip.sum(1, dtype=TORCH.int32), stats["skip_count"])
        context["float_rows"][index] += len(gated)
        context["predicted_skip"] += int(skip.sum())
        if mode != "all_float_unpruned":
            gated = gated.masked_fill(skip, 0)  # [M,K], retain predictor decisions
            context["applied_skip"] += int(skip.sum())
        values = projections.down_proj(gated)  # [M,H], floating diagnostic output
        # Keep raw in its archived integer representation for diagnostics.
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
    record = BENCHMARK.read(REPORT)
    prior = BENCHMARK.read(PREVIOUS)
    prior_config, = (ROOT / name for name in prior["evidence_sha256"] if name.endswith("/inputs.json"))
    assert digest(prior_config) == prior["evidence_sha256"][str(prior_config.relative_to(ROOT))]
    assert digest(ARCHIVE) == record["evidence_sha256"][str(ARCHIVE.relative_to(ROOT))]
    archived = {entry["questionId"]: entry for entry in verified_rows(ARCHIVE, sorted(labels))}
    chosen = {}
    for key in setup["questions"]:
        chosen.setdefault(labels[key]["imageId"], key)
    questions = sorted(chosen.values())
    assert questions == BENCHMARK.read(prior_config)["questions"]
    assert len(questions) == 67 and not chosen.keys() & set(setup["excluded_source_panel_images"])

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

    out.mkdir(parents=True, exist_ok=True)
    manifest = out / "inputs.json"
    BENCHMARK.write(manifest, {
        "checkpoint_revision": BENCHMARK.REVISION, "questions": questions, "prompt": BENCHMARK.PROMPT,
        "late_prefill_layers": list(range(*combined.LATE)), "modes": MODES,
        "input_sha256": setup["input_sha256"] | {str(path): digest(path) for path in
            (ARCHIVE, REPORT, PREVIOUS, prior_config, Path(__file__).resolve())},
    })

    def answer(key, embeddings, image_start, mode):
        # Shared checkpoint image/text embeddings [1,T,H] enter the decoder.
        # Tokens are the greedy index sequence, at most the frozen budget.
        context.update(mode=mode, calibrated=True, clipping=True, verify_raw=False, calls=[0]*22,
                       weight_rows=[0]*22, clip_rows=[0]*22, float_rows=[0]*22,
                       workload=Counter(), predicted_skip=0, applied_skip=0)
        for item in items:
            item.begin(True, True)
        tokens = combined.decode(decoder, embeddings, image_start, BENCHMARK.MODE, tokenizer.eos_token_id)
        prediction = BENCHMARK.normalize(tokenizer.decode(tokens, skip_special_tokens=True))
        predicted = sum(item.prefill_skipped + item.decode_skipped for item in items)
        assert context["applied_skip"] == (0 if mode == "all_float_unpruned" else context["predicted_skip"])
        for index, row_count in enumerate(decoder.layer_slots):
            substituting = mode is not None and (not mode.startswith("late_") or combined.LATE[0] <= index < combined.LATE[1])
            assert context["float_rows"][index] == (row_count if substituting else 0)
        return {
            "questionId": key, "tokens": tokens, "prediction": prediction, "skipped_channels": predicted,
            "workload": dict(context["workload"]), "float_rows": context["float_rows"],
            "diagnostic_predicted_skip": context["predicted_skip"], "diagnostic_applied_skip": context["applied_skip"],
        }

    results = {mode: Counter() for mode in MODES}
    min_free = BENCHMARK.host_available()
    predictions = out / "predictions.jsonl"
    BENCHMARK.ALL_ATTENTION_FUNCTIONS["sdpa"] = decoder.attend
    try:
        with predictions.open("x", buffering=1) as stream:
            for index, key in enumerate(questions, 1):
                min_free = min(min_free, BENCHMARK.host_available())
                assert min_free >= 9 * combined.GIB, "Yield to current hardware jobs"
                label = labels[key]
                embeddings, image_start = combined.encode(model, processor, images[label["imageId"]], label["question"])
                baseline = answer(key, embeddings, image_start, None)
                assert {part: baseline[part] for part in archived[key]} == archived[key], key
                old = baseline["prediction"] == label["answer"]
                candidates = {}
                for mode in MODES:
                    row = answer(key, embeddings, image_start, mode)
                    new = row["prediction"] == label["answer"]
                    results[mode].update(baseline=int(old), candidate=int(new), gained=int(new and not old),
                                         lost=int(old and not new), first_token_changed=int(
                                             baseline["tokens"][0] != row["tokens"][0]))
                    candidates[mode] = row
                stream.write(json.dumps({"questionId": key, "baseline": baseline, "candidates": candidates}) + "\n")
                if index % 8 == 0 or index == len(questions):
                    print("PROMPT_ARITHMETIC_PROGRESS", index, len(questions), results, flush=True)
    finally:
        BENCHMARK.ALL_ATTENTION_FUNCTIONS["sdpa"] = original
    result = {
        "state": "matched_prompt_arithmetic_controls_completed", "questions": len(questions),
        "baseline_outputs_reproduced": len(questions), "comparisons": results,
        "device": TORCH.cuda.get_device_name(), "peak_device_bytes": TORCH.cuda.max_memory_allocated(),
        "minimum_sampled_host_available_bytes": min_free, "elapsed_seconds": time.monotonic() - started,
        "inputs_sha256": digest(manifest), "predictions_sha256": digest(predictions),
    }
    BENCHMARK.write(out / "receipt.json", result)
    print("PROMPT_ARITHMETIC_COMPLETE", json.dumps(result), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", type=lambda value: Path(value).resolve())
    options = parser.parse_args()
    assert options.out.is_relative_to(ROOT / ".cache")
    run(options.out)
