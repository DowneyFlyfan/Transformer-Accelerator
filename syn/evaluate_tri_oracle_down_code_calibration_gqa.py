"""Compare frozen down weight codes on the established 200-question panel."""

import argparse
from collections import Counter
from copy import copy
import json
from pathlib import Path
import time

from evaluate_tri_oracle_weight_range_gqa import inputs as panel_inputs
from measure_tri_oracle_input_equalization import EXPANSION, HIDDEN, LAYERS
from run_pruned_accuracy_ablation import benchmark, decode, encode
from tri_oracle_integer_reference import _quantize
from verify_tri_oracle_packed_down_weights import ROOT, sha256


EXPORT = ROOT / ".cache/model_reference/gqa_testdev/down_code_calibration_export"
MODES = ("baseline", "calibrated_prefill")


def install(replacement, index, weights, frozen, context):
    """Install the frozen [H,K] signed-eight-bit weights for ordinary prefill rows."""
    torch = benchmark.torch
    initial = replacement.reference.evaluate
    ordinary = copy(replacement.reference)
    original, scale = _quantize(weights.down_proj.weight, per_row=True)  # [H,K] and [H,1]
    ordinary.down = original
    ordinary.down_exponent = scale.T  # [1,H], one output scale per channel
    record = torch.load(frozen, weights_only=True, map_location="cpu")
    candidate = record["codes"].to(device=original.device)  # [H,K], fixed calibrated weights
    assert candidate.dtype == torch.int8 and candidate.shape == (HIDDEN, EXPANSION)
    assert torch.equal(record["scale"].to(device=scale.device), scale)
    assert bool(((candidate.to(torch.int16) - original).abs() <= 1).all())
    revised = copy(ordinary)
    revised.down = candidate

    def dispatch(activation, residual, **settings):
        # Activation and residual are [M,H] for M retained rows and H hidden features.
        prefill = replacement.decoder.prefill_active
        first = prefill and context["calls"][index] == 0
        context["calls"][index] += 1
        if first:
            assert activation.shape[0] == 1
            return initial(activation, residual, **settings)
        if prefill and context["calibrated"]:
            context["changed_rows"][index] += activation.shape[0]
            return revised.evaluate(activation, residual, **settings)
        return ordinary.evaluate(activation, residual, **settings)

    replacement.reference.evaluate = dispatch


@benchmark.torch.inference_mode()
def run(output):
    started = time.monotonic()
    torch = benchmark.torch
    assert Path("/.dockerenv").is_file()
    assert int(Path("/sys/fs/cgroup/memory.max").read_text()) <= 3 * benchmark.GIB
    assert benchmark.host_available() >= 12 * benchmark.GIB
    torch.set_num_threads(3)
    torch.set_num_interop_threads(1)
    torch.manual_seed(0)
    assert torch.cuda.mem_get_info()[0] >= 12 * benchmark.GIB
    torch.cuda.set_per_process_memory_fraction(0.78)
    torch.cuda.reset_peak_memory_stats()
    dataset, labels, pins = benchmark.inputs()
    ordered, controls, _ = panel_inputs(pins)
    assert len({labels[key]["imageId"] for key in ordered}) == 200
    joint = ROOT / "records/batch424_joint_pilot_result.json"
    protocol_path = ROOT / "records/wac_gqa_accuracy_protocol_result.json"
    frozen_path = EXPORT / "receipt.json"
    protocol, frozen = map(benchmark.read, (protocol_path, frozen_path))
    assert protocol["checkpoint_revision"] == frozen["checkpoint_revision"] == benchmark.REVISION
    assert not any(protocol["exact_decoded_image_overlap"].values())
    assert frozen["state"] == "bounded_down_weight_code_calibration_heldout_measured"
    assert all(sha256(Path(name)) == checksum for name, checksum in frozen["evidence_sha256"].items())
    policies = [benchmark.REFERENCE / name / "layer_policy.json" for name in ("format322", "format335")]
    for path in (Path(__file__).resolve(), Path(encode.__code__.co_filename), joint, protocol_path, frozen_path, *policies):
        checksum = sha256(path)
        assert pins.setdefault(str(path), checksum) == checksum
    code_files = [EXPORT / f"codes/down_{index:02d}.pt" for index in range(LAYERS)]
    assert len(frozen["layers"]) == len(code_files)
    for index, (entry, file) in enumerate(zip(frozen["layers"], code_files, strict=True)):
        assert entry["layer"] == index and sha256(file) == entry["codebook_sha256"]
        pins[str(file)] = entry["codebook_sha256"]

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
    original_attention = benchmark.ALL_ATTENTION_FUNCTIONS["sdpa"]
    decoder = benchmark.CompactDecoder(model, original_attention, tuple(benchmark.read(joint)["local_ratio"]))
    first, ordinary = (benchmark.read(path)["layers"] for path in policies)
    layers = decoder.language.layers
    replacements = [benchmark.FeedForward(layer, decoder, initial, later)
                    for layer, initial, later in zip(layers, first, ordinary, strict=True)]
    context = {}
    for index, (replacement, layer, codebook) in enumerate(zip(replacements, layers, code_files, strict=True)):
        install(replacement, index, layer.mlp, codebook, context)
    assert len(replacements) == LAYERS

    output.mkdir()
    manifest, predictions = (output / name for name in ("inputs.json", "predictions.jsonl"))
    benchmark.write(manifest, {"checkpoint_revision": benchmark.REVISION, "questions": ordered, "modes": MODES,
                               "input_sha256": pins, "prompt": benchmark.PROMPT, "weight_skipping": True,
                               "maximum_new_tokens": benchmark.MAX_NEW_TOKENS})
    scores = Counter()
    benchmark.ALL_ATTENTION_FUNCTIONS["sdpa"] = decoder.attend
    minimum_memory = benchmark.host_available()
    try:
        with predictions.open("x", buffering=1) as stream:
            for completed, key in enumerate(ordered, 1):
                minimum_memory = min(minimum_memory, benchmark.host_available())
                assert minimum_memory >= 8.5 * benchmark.GIB
                label = labels[key]
                embeddings, image_start = encode(model, processor, images[label["imageId"]], label["question"])  # [1,T,H]
                row = {"questionId": key}
                for mode in MODES:
                    calibrated = mode == "calibrated_prefill"
                    context.update(calls=[0] * LAYERS, changed_rows=[0] * LAYERS, calibrated=calibrated)
                    for replacement in replacements:
                        replacement.begin(True, True)
                    tokens = decode(decoder, embeddings, image_start, benchmark.MODE, tokenizer.eos_token_id)
                    assert context["changed_rows"] == [item.prefill_rows - 1 if calibrated else 0 for item in replacements]
                    prediction = benchmark.normalize(tokenizer.decode(tokens, skip_special_tokens=True))
                    skips = sum(item.prefill_skipped + item.decode_skipped for item in replacements)
                    assert skips > 0
                    row[mode] = {"tokens": tokens, "prediction": prediction, "skipped_channels": skips}
                    scores[mode] += prediction == label["answer"]
                assert row["baseline"] == controls[key], key
                stream.write(json.dumps(row) + "\n")
                if completed % 8 == 0:
                    print("DOWN_CODE_GQA_PROGRESS", completed, len(ordered), dict(scores), flush=True)
    finally:
        benchmark.ALL_ATTENTION_FUNCTIONS["sdpa"] = original_attention
        for replacement in replacements:
            replacement.close()
    assert scores["baseline"] == 116 and all(sha256(Path(name)) == checksum for name, checksum in pins.items())
    result = {"state": "gqa_frozen_prefill_down_codes_completed", "questions": len(ordered), "scores": dict(scores),
              "minimum_host_available_bytes": minimum_memory, "peak_gpu_bytes": torch.cuda.max_memory_allocated(),
              "wall_seconds": time.monotonic() - started, "input_sha256": sha256(manifest),
              "predictions_sha256": sha256(predictions)}
    benchmark.write(output / "receipt.json", result)
    print(result["state"], dict(scores), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=lambda value: Path(value).resolve())
    run(parser.parse_args().output)
