"""Compare frozen input scales on the same balanced GQA Test-Dev questions."""

import argparse
from collections import Counter
from copy import copy
import fcntl
import json
from pathlib import Path
import time

from run_pruned_accuracy_ablation import benchmark, decode, encode
from measure_tri_oracle_input_equalization import HIDDEN, LAYERS, variant
from tri_oracle_integer_reference import _quantize
from verify_tri_oracle_packed_down_weights import ROOT, sha256


DATA = ROOT / ".cache/model_reference/gqa_testdev"
CALIBRATION = ROOT / ".cache/model_reference/input_equalization_v1/verified_receipt.json"


def setup_inputs():
    dataset, labels, pins = benchmark.inputs()

    def pin(path, expected=None):
        actual = sha256(path)
        assert expected is None or actual == expected, path
        assert pins.setdefault(str(path), actual) == actual, path

    result = ROOT / "records/wac_feedforward_input_equalization_result.json"
    pin(result)
    diagnostic = benchmark.read(result)
    assert diagnostic["state"] == "fit_only_power_of_two_input_equalization_measured_on_held_rows"
    pin(CALIBRATION, diagnostic["evidence_sha256"][str(CALIBRATION.relative_to(ROOT))])
    scales = benchmark.read(CALIBRATION)
    assert scales["checkpoint_revision"] == benchmark.REVISION and len(scales["layers"]) == LAYERS
    for index, layer in enumerate(scales["layers"]):
        assert layer["layer"] == index and len(layer["feature_exponents"]) == HIDDEN
        assert all(type(value) is int and -3 <= value <= 3 for value in layer["feature_exponents"])
    assert sum(layer["selection"] != "identity" for layer in scales["layers"]) == 21

    protocol_path = ROOT / "records/wac_gqa_accuracy_protocol_result.json"
    pin(protocol_path)
    protocol = benchmark.read(protocol_path)
    assert protocol["checkpoint_revision"] == benchmark.REVISION
    assert not any(protocol["exact_decoded_image_overlap"].values())
    assert protocol["prompt"] == benchmark.PROMPT
    assert protocol["decoder_max_new_tokens"] == benchmark.MAX_NEW_TOKENS

    panel_path = DATA / "down_scale_panel_cadence_replay/inputs.json"
    panel_proof = panel_path.with_name("independent_receipt.json")
    pin(panel_proof)
    pin(panel_path, benchmark.read(panel_proof)["evidence_sha256"][str(panel_path)])
    panel = benchmark.read(panel_path)["panel"]
    assert len(panel) == 5 and all(len(keys) == 48 for keys in panel.values())
    ordered = [key for group in sorted(panel) for key in panel[group][8:]]
    pilot = [key for group in sorted(panel) for key in panel[group][:8]]
    assert len(ordered) == len(set(ordered)) == len({labels[key]["imageId"] for key in ordered}) == 200
    assert {labels[key]["imageId"] for key in ordered}.isdisjoint(labels[key]["imageId"] for key in pilot)

    prior = DATA / "pruned_reference"
    receipt, config, predictions = (prior / name for name in ("receipt.json", "inputs.json", "predictions.jsonl"))
    pin(receipt)
    control = benchmark.read(receipt)
    pin(config, control["inputs_sha256"])
    pin(predictions, control["predictions_sha256"])
    prior_config = benchmark.read(config)
    assert prior_config["checkpoint_revision"] == benchmark.REVISION and prior_config["prompt"] == benchmark.PROMPT
    assert prior_config["decoder_max_new_tokens"] == benchmark.MAX_NEW_TOKENS
    for name, expected in prior_config["input_sha256"].items():
        pin(Path(name), expected)
    selected = set(ordered)
    with predictions.open() as stream:
        controls = {row["questionId"]: row for line in stream
                    if (row := json.loads(line))["questionId"] in selected}
    assert controls.keys() == selected
    return dataset, labels, ordered, controls, scales, pins


def install(replacement, index, projections, frozen, context):
    """Install an ordinary-row evaluator using checkpoint [K,H]/[H,K] weights.

    K is the feed-forward expansion and H is the hidden width. Both modes
    reuse the same down codes [H,K], output scales [1,H], and original signs.
    """
    initial = replacement.reference.evaluate
    ordinary = copy(replacement.reference)
    ordinary.down, exponents = _quantize(projections.down_proj.weight, per_row=True)  # [H,K], [H,1]
    ordinary.down_exponent = exponents.T  # [1,H]
    powers = benchmark.torch.tensor(frozen["feature_exponents"], dtype=benchmark.torch.int32,
                                    device=ordinary.device)  # [H], calibrated offline
    equalized = ordinary
    if frozen["selection"] != "identity":
        equalized = variant(ordinary, projections.gate_proj.weight, projections.up_proj.weight, powers)

    def dispatch(activation, residual, **settings):
        # Caller supplies original normalized input [M,H] and raw residual [M,H].
        # The policy selected the format from that original input.
        first = replacement.decoder.prefill_active and context["calls"][index] == 0
        context["calls"][index] += 1
        if first:
            assert activation.shape[0] == 1
            return initial(activation, residual, **settings)
        context["ordinary_rows"][index] += activation.shape[0]
        reference = equalized if context["equalized"] else ordinary
        return reference.evaluate(activation, residual, **settings)

    replacement.reference.evaluate = dispatch


def score_row(row, key, label, controls, tokenizer):
    assert row["questionId"] == key
    assert row["baseline"] == {name: controls[key][name] for name in ("tokens", "prediction", "skipped_channels")}
    for mode in ("baseline", "equalized"):
        item = row[mode]
        tokens = item["tokens"]
        assert 0 < len(tokens) <= benchmark.MAX_NEW_TOKENS and all(type(token) is int and token >= 0 for token in tokens)
        assert item["prediction"] == benchmark.normalize(tokenizer.decode(tokens, skip_special_tokens=True))
        assert type(item["skipped_channels"]) is int and item["skipped_channels"] > 0
    baseline = row["baseline"]["prediction"] == label["answer"]
    equalized = row["equalized"]["prediction"] == label["answer"]
    return Counter(baseline=baseline, equalized=equalized, gained=equalized and not baseline,
                   lost=baseline and not equalized, changed_answers=row["baseline"]["prediction"] != row["equalized"]["prediction"])


def recover(stream, ordered, labels, controls, tokenizer):
    stream.seek(0)
    count, end, scores = 0, 0, Counter()
    while line := stream.readline():
        if not line.endswith(b"\n"):
            break
        assert count < len(ordered)
        key = ordered[count]
        scores.update(score_row(json.loads(line), key, labels[key], controls, tokenizer))
        count += 1
        end = stream.tell()
    stream.seek(end)
    stream.truncate()
    return count, scores


@benchmark.torch.inference_mode()
def run(output):
    """Generate paired answers from the same checkpoint and prompt for each question."""
    started = time.monotonic()
    benchmark.start_isolated_memory_guard()
    torch = benchmark.torch
    torch.set_num_threads(3)
    torch.set_num_interop_threads(1)
    torch.manual_seed(0)
    assert torch.cuda.mem_get_info()[0] >= 12 * benchmark.GIB
    torch.cuda.set_per_process_memory_fraction(0.78)
    torch.cuda.reset_peak_memory_stats()
    dataset, labels, ordered, controls, scales, pins = setup_inputs()
    joint = ROOT / "records/batch424_joint_pilot_result.json"
    policies = [benchmark.REFERENCE / name / "layer_policy.json" for name in ("format322", "format335")]
    for path in (Path(__file__).resolve(), joint, *policies, Path(variant.__code__.co_filename),
                 Path(encode.__code__.co_filename)):
        assert pins.setdefault(str(path), sha256(path)) == sha256(path)
    configuration = {"checkpoint_revision": benchmark.REVISION, "questions": ordered, "prompt": benchmark.PROMPT,
                     "maximum_new_tokens": benchmark.MAX_NEW_TOKENS, "input_sha256": pins}
    output.mkdir(exist_ok=True)
    with (output / "run.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        manifest, predictions, receipt = (output / name for name in ("inputs.json", "predictions.jsonl", "receipt.json"))
        if manifest.exists():
            assert benchmark.read(manifest) == configuration
        else:
            assert not predictions.exists()
            benchmark.write(manifest, configuration)
        assert not receipt.exists()
        tokenizer = benchmark.AutoTokenizer.from_pretrained(benchmark.MODEL, local_files_only=True)
        with predictions.open("a+b", buffering=0) as stream:
            completed, scores = recover(stream, ordered, labels, controls, tokenizer)
            if completed < len(ordered):
                generate(stream, ordered, completed, labels, controls, tokenizer, dataset, joint, policies, scales, scores)
        assert scores["equalized"] - scores["baseline"] == scores["gained"] - scores["lost"]
        assert all(sha256(Path(name)) == digest for name, digest in pins.items())
        result = {"state": "paired_input_equalization_gqa_panel_completed", "questions": len(ordered),
                  "checkpoint_revision": benchmark.REVISION, "baseline_predictions_reproduced": len(ordered),
                  "scores": dict(scores), "predictions_sha256": sha256(predictions), "inputs_sha256": sha256(manifest),
                  "peak_gpu_bytes": torch.cuda.max_memory_allocated(), "elapsed_seconds": time.monotonic()-started}
        benchmark.write(receipt, result)
        print("INPUT_EQUALIZATION_GQA_COMPLETE", dict(scores), flush=True)


def generate(stream, ordered, completed, labels, controls, tokenizer, dataset, joint, policies, scales, scores):
    """Run frozen model variants on shared image/text embeddings [1,T,H]."""
    images = benchmark.load_images(dataset)
    processor = benchmark.LlavaProcessor(
        image_processor=benchmark.CLIPImageProcessorPil.from_pretrained(benchmark.MODEL, local_files_only=True),
        tokenizer=tokenizer, patch_size=14, vision_feature_select_strategy="default", num_additional_image_tokens=1,
    )
    model = benchmark.LlavaForConditionalGeneration.from_pretrained(
        benchmark.MODEL, local_files_only=True, dtype=benchmark.torch.float32, attn_implementation="sdpa",
        use_kernels=False, device_map={"": "cuda:0"},
    ).eval()
    assert model.generation_config.eos_token_id == tokenizer.eos_token_id == 2
    original = benchmark.ALL_ATTENTION_FUNCTIONS["sdpa"]
    decoder = benchmark.CompactDecoder(model, original, tuple(benchmark.read(joint)["local_ratio"]))
    layers = decoder.language.layers
    first, ordinary = (benchmark.read(path)["layers"] for path in policies)
    replacements = [benchmark.FeedForward(layer, decoder, initial, later)
                    for layer, initial, later in zip(layers, first, ordinary, strict=True)]
    context = {}
    for index, (replacement, layer, frozen) in enumerate(zip(replacements, layers, scales["layers"], strict=True)):
        install(replacement, index, layer.mlp, frozen, context)
    benchmark.ALL_ATTENTION_FUNCTIONS["sdpa"] = decoder.attend
    try:
        for offset, key in enumerate(ordered[completed:], completed+1):
            assert benchmark.host_available() >= 14.5 * benchmark.GIB
            label = labels[key]
            embeddings, image_start = encode(model, processor, images[label["imageId"]], label["question"])  # [1,T,H], scalar
            row = {"questionId": key}
            for mode in ("baseline", "equalized"):
                context.update(calls=[0]*LAYERS, ordinary_rows=[0]*LAYERS, equalized=mode == "equalized")
                for replacement in replacements:
                    replacement.begin(True, True)
                tokens = decode(decoder, embeddings, image_start, benchmark.MODE, tokenizer.eos_token_id)
                assert all(context["ordinary_rows"][index] == item.prefill_rows+item.decode_rows-1
                           for index, item in enumerate(replacements))
                prediction = benchmark.normalize(tokenizer.decode(tokens, skip_special_tokens=True))
                skips = sum(item.prefill_skipped + item.decode_skipped for item in replacements)
                row[mode] = {"tokens": tokens, "prediction": prediction, "skipped_channels": skips}
            scores.update(score_row(row, key, label, controls, tokenizer))
            stream.write((json.dumps(row) + "\n").encode())
            if offset == 1 or offset % 8 == 0:
                print("INPUT_EQUALIZATION_GQA_PROGRESS", offset, len(ordered), dict(scores), flush=True)
    finally:
        benchmark.ALL_ATTENTION_FUNCTIONS["sdpa"] = original
        for replacement in replacements:
            replacement.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    run(parser.parse_args().output.resolve())
