"""Compare frozen prompt weight ranges on the fixed GQA panel."""

import argparse
from collections import Counter
from copy import copy
import json
from pathlib import Path
import time

from measure_tri_oracle_weight_range import codes_at
from run_pruned_accuracy_ablation import benchmark, decode, encode
from tri_oracle_integer_reference import _quantize
from verify_tri_oracle_packed_down_weights import ROOT, sha256


DATA = ROOT / ".cache/model_reference/gqa_testdev"
CALIBRATION = ROOT / ".cache/model_reference/weight_range_v2.json"
MODES = ("baseline", "calibrated_prefill")


def inputs(pins):
    calibration = ROOT / "records/wac_gate_up_weight_range_result.json"
    prior_panel = ROOT / "records/wac_gqa_input_equalization_result.json"
    for path in (calibration, prior_panel, Path(__file__).resolve()):
        pins[str(path)] = sha256(path)
    ranges, panel = map(benchmark.read, (calibration, prior_panel))
    assert ranges["state"] == "gate_up_weight_ranges_independently_checked_on_held_prompt_rows"
    assert panel["state"] == "frozen_input_equalization_gqa_panel_independently_rescored"
    manifest = DATA / "input_equalization_panel/inputs.json"
    predictions = manifest.with_name("predictions.jsonl")
    for path, report in ((CALIBRATION, ranges), (manifest, panel), (predictions, panel)):
        digest = sha256(path)
        assert digest == report["evidence_sha256"][str(path.relative_to(ROOT))]
        pins[str(path)] = digest
    setup = benchmark.read(manifest)
    frozen = benchmark.read(CALIBRATION)
    assert setup["checkpoint_revision"] == frozen["checkpoint_revision"] == benchmark.REVISION
    assert setup["prompt"] == benchmark.PROMPT and setup["maximum_new_tokens"] == benchmark.MAX_NEW_TOKENS
    assert [item["selected_offsets"] for item in frozen["layers"]] == ranges["selected_offsets_by_layer"]
    ordered = setup["questions"]
    with predictions.open() as stream:
        rows = [json.loads(line) for line in stream]
    assert [item["questionId"] for item in rows] == ordered and len(set(ordered)) == 200
    return ordered, {row["questionId"]: row["baseline"] for row in rows}, frozen["layers"]


def install(replacement, index, weights, frozen, context):
    """Keep the current decoder and change only calibrated prompt weight codes."""
    first = replacement.reference.evaluate
    ordinary = copy(replacement.reference)
    ordinary.down, powers = _quantize(weights.down_proj.weight, per_row=True)  # [H,K] weights, [H,1] scales.
    ordinary.down_exponent = powers.T  # [1,H], one scale per output channel.
    revised = copy(ordinary)  # Reuses the original prediction signs, fixed-point path, and down weights.
    gate_offset, up_offset = frozen["selected_offsets"]
    revised.gate_exponent += gate_offset
    revised.up_exponent += up_offset
    revised.gate, clipped_gate = codes_at(weights.gate_proj.weight, revised.gate_exponent)  # Signed8 [K,H].
    revised.up, clipped_up = codes_at(weights.up_proj.weight, revised.up_exponent)  # Signed8 [K,H].
    assert frozen["clipped_weights"] == {"gate": clipped_gate, "up": clipped_up}

    def dispatch(activation, residual, **settings):
        # [R,H] normalized activation and raw residual for R retained rows and H hidden features.
        prefill = replacement.decoder.prefill_active
        first_row = prefill and context["calls"][index] == 0
        context["calls"][index] += 1
        if first_row:
            assert activation.shape[0] == 1
            return first(activation, residual, **settings)
        if prefill and context["calibrated"]:
            context["changed_rows"][index] += activation.shape[0]
            return revised.evaluate(activation, residual, **settings)
        return ordinary.evaluate(activation, residual, **settings)

    replacement.reference.evaluate = dispatch


@benchmark.torch.inference_mode()
def run(output):
    started = time.monotonic()
    benchmark.start_isolated_memory_guard()
    torch = benchmark.torch
    torch.set_num_threads(3)
    torch.set_num_interop_threads(1)
    torch.manual_seed(0)
    assert torch.cuda.mem_get_info()[0] > 12 * benchmark.GIB
    torch.cuda.set_per_process_memory_fraction(0.78)
    torch.cuda.reset_peak_memory_stats()
    dataset, labels, pins = benchmark.inputs()
    ordered, controls, ranges = inputs(pins)
    assert len({labels[key]["imageId"] for key in ordered}) == 200
    joint = ROOT / "records/batch424_joint_pilot_result.json"
    policies = [benchmark.REFERENCE / name / "layer_policy.json" for name in ("format322", "format335")]
    for file in (joint, *policies, Path(encode.__code__.co_filename), Path(codes_at.__code__.co_filename)):
        digest = sha256(file)
        assert pins.setdefault(str(file), digest) == digest
    tokenizer = benchmark.AutoTokenizer.from_pretrained(benchmark.MODEL, local_files_only=True)
    processor = benchmark.LlavaProcessor(
        image_processor=benchmark.CLIPImageProcessorPil.from_pretrained(benchmark.MODEL, local_files_only=True),
        tokenizer=tokenizer, patch_size=14, vision_feature_select_strategy="default", num_additional_image_tokens=1,
    )
    images = benchmark.load_images(dataset)
    model = benchmark.LlavaForConditionalGeneration.from_pretrained(
        benchmark.MODEL, local_files_only=True, dtype=torch.float32, attn_implementation="sdpa",
        use_kernels=False, device_map={"": "cuda:0"},
    ).eval()
    assert model.generation_config.eos_token_id == tokenizer.eos_token_id == 2
    original = benchmark.ALL_ATTENTION_FUNCTIONS["sdpa"]
    decoder = benchmark.CompactDecoder(model, original, tuple(benchmark.read(joint)["local_ratio"]))
    first, ordinary = (benchmark.read(path)["layers"] for path in policies)
    layers = decoder.language.layers
    replacements = [benchmark.FeedForward(layer, decoder, initial, later)
                    for layer, initial, later in zip(layers, first, ordinary, strict=True)]
    context = {}
    for index, (replacement, layer, frozen) in enumerate(zip(replacements, layers, ranges, strict=True)):
        install(replacement, index, layer.mlp, frozen, context)
    assert len(replacements) == 22

    output.mkdir()
    manifest = output / "inputs.json"
    benchmark.write(manifest, {"checkpoint_revision": benchmark.REVISION, "questions": ordered, "modes": MODES,
                               "input_sha256": pins, "prompt": benchmark.PROMPT, "weight_skipping": True})
    predictions = output / "predictions.jsonl"
    scores = Counter()
    benchmark.ALL_ATTENTION_FUNCTIONS["sdpa"] = decoder.attend
    try:
        with predictions.open("x", buffering=1) as stream:
            for index, key in enumerate(ordered, 1):
                assert benchmark.host_available() >= 14.5 * benchmark.GIB
                label = labels[key]
                embeddings, image_start = encode(model, processor, images[label["imageId"]], label["question"])  # [1,T,H], scalar.
                row = {"questionId": key}
                for mode in MODES:
                    calibrated = mode == "calibrated_prefill"
                    context.update(calls=[0] * 22, changed_rows=[0] * 22, calibrated=calibrated)
                    for replacement in replacements:
                        replacement.begin(True, True)
                    tokens = decode(decoder, embeddings, image_start, benchmark.MODE, tokenizer.eos_token_id)
                    assert context["changed_rows"] == [item.prefill_rows - 1 if calibrated else 0 for item in replacements]
                    prediction = benchmark.normalize(tokenizer.decode(tokens, skip_special_tokens=True))
                    skips = sum(item.prefill_skipped + item.decode_skipped for item in replacements)
                    row[mode] = {"tokens": tokens, "prediction": prediction, "skipped_channels": skips}
                    assert skips > 0
                    scores[mode] += prediction == label["answer"]
                assert row["baseline"] == controls[key], key
                stream.write(json.dumps(row) + "\n")
                if index % 8 == 0:
                    print("GQA_WEIGHT_RANGE_PROGRESS", index, len(ordered), dict(scores), flush=True)
    finally:
        benchmark.ALL_ATTENTION_FUNCTIONS["sdpa"] = original
        for replacement in replacements:
            replacement.close()
    assert scores["baseline"] == 116 and all(sha256(Path(name)) == digest for name, digest in pins.items())
    result = {"state": "gqa_frozen_prefill_weight_ranges_completed", "questions": len(ordered), "scores": dict(scores),
              "elapsed_seconds": time.monotonic() - started, "peak_gpu_bytes": torch.cuda.max_memory_allocated(),
              "input_sha256": sha256(manifest), "predictions_sha256": sha256(predictions)}
    benchmark.write(output / "receipt.json", result)
    print(result["state"], dict(scores), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=lambda value: Path(value).resolve())
    run(parser.parse_args().output)
