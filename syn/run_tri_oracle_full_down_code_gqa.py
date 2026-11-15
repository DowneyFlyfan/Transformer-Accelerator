"""Resume the frozen down-code model on the complete pinned question set."""

import argparse
from collections import Counter
import fcntl
import json
import os
from pathlib import Path
import time

from evaluate_tri_oracle_down_code_calibration_gqa import EXPORT, install
from run_dense_testdev import recover_predictions
from run_pruned_accuracy_ablation import benchmark, decode, encode
from verify_tri_oracle_packed_down_weights import ROOT, sha256


DATA = EXPORT.parent
CONTROL = DATA / "pruned_reference"
PANEL = DATA / "down_code_calibration_panel"
PHYSICAL = ROOT / ".cache/indexed_whole_chip/dual_group_probe/bounded_decoder/native_placement"
MINIMUM_QUESTIONS = 12_578


def checked_inputs():
    dataset, labels, pins = benchmark.inputs()

    def pin(path, expected=None):
        checksum = sha256(path)
        assert expected is None or checksum == expected, path
        assert pins.setdefault(str(path), checksum) == checksum, path

    baseline = benchmark.read(CONTROL / "receipt.json")
    panel = benchmark.read(PANEL / "receipt.json")
    assert baseline["state"] == "gqa_testdev_pruned_reference_completed"
    assert baseline["questions"] == len(labels) == MINIMUM_QUESTIONS
    assert panel["state"] == "gqa_frozen_prefill_down_codes_completed"
    for source, proof, field in ((CONTROL, baseline, "inputs_sha256"), (PANEL, panel, "input_sha256")):
        pin(source / "receipt.json")
        pin(source / "inputs.json", proof[field])
        pin(source / "predictions.jsonl", proof["predictions_sha256"])
        configuration = benchmark.read(source / "inputs.json")
        assert configuration["checkpoint_revision"] == benchmark.REVISION
        assert configuration["prompt"] == benchmark.PROMPT
        limit = configuration.get("decoder_max_new_tokens", configuration.get("maximum_new_tokens"))
        assert limit == benchmark.MAX_NEW_TOKENS
        for name, checksum in configuration["input_sha256"].items():
            path = Path(name)
            if name in pins:
                assert pins[name] == checksum
            else:
                pin(path, checksum)

    receipt_path = EXPORT / "receipt.json"
    calibration = benchmark.read(receipt_path)
    protocol = ROOT / "records/wac_gqa_accuracy_protocol_result.json"
    assert not any(benchmark.read(protocol)["exact_decoded_image_overlap"].values())
    policies = tuple(benchmark.REFERENCE / name / "layer_policy.json" for name in ("format322", "format335"))
    joint = ROOT / "records/batch424_joint_pilot_result.json"
    for path in (receipt_path, protocol, joint, *policies, Path(__file__).resolve(),
                 Path(install.__code__.co_filename), Path(recover_predictions.__code__.co_filename)):
        pin(path)
    assert calibration["checkpoint_revision"] == benchmark.REVISION
    codebooks = tuple(EXPORT / f"codes/down_{i:02d}.pt" for i in range(22))
    for index, (row, path) in enumerate(zip(calibration["layers"], codebooks, strict=True)):
        assert row["layer"] == index
        pin(path, row["codebook_sha256"])
    anchors = {row["questionId"]: row["calibrated_prefill"] for line in (PANEL / "predictions.jsonl").open()
               if (row := json.loads(line))}
    assert len(anchors) == panel["questions"] == 200
    assert anchors.keys() <= labels.keys()
    return dataset, labels, baseline, anchors, codebooks, joint, policies, pins


def hardware_needs_memory():
    return any((stage / "console.log").is_file() and not (stage / "status.json").is_file()
               for stage in (PHYSICAL / "import", PHYSICAL / "cold"))


def generate(dataset, labels, tokenizer, anchors, codebooks, joint, policies, ordered, stream, done, stop):
    """Keep the same model path as the panel and score only the calibrated condition."""
    torch = benchmark.torch
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
    items = [benchmark.FeedForward(layer, decoder, initial, regular)
             for layer, initial, regular in zip(layers, first, ordinary, strict=True)]
    context = {}
    for index, (item, layer, codebook) in enumerate(zip(items, layers, codebooks, strict=True)):
        install(item, index, layer.mlp, codebook, context)

    def answer(key):
        context.update(calls=[0] * len(items), changed_rows=[0] * len(items), calibrated=True)
        for item in items:
            item.begin(True, True)
        label = labels[key]
        embeddings, start = encode(model, processor, images[label["imageId"]], label["question"])  # [1,T,H]
        tokens = decode(decoder, embeddings, start, benchmark.MODE, tokenizer.eos_token_id)
        assert context["changed_rows"] == [item.prefill_rows-1 for item in items]
        predicted = benchmark.normalize(tokenizer.decode(tokens, skip_special_tokens=True))
        skips = sum(item.prefill_skipped + item.decode_skipped for item in items)
        result = {"tokens": tokens, "prediction": predicted, "skipped_channels": skips}
        assert skips > 0 and result == anchors.get(key, result), key
        return result

    benchmark.ALL_ATTENTION_FUNCTIONS["sdpa"] = decoder.attend
    counts = Counter()
    try:
        categories = {}
        for key in anchors:
            categories.setdefault(labels[key]["types"]["structural"], key)
        for key in categories.values():
            answer(key)
        print("FULL_DOWN_CODE_PANEL_CANARIES_MATCHED", len(categories), flush=True)
        for key in ordered[done:stop]:
            if benchmark.host_available() < 8.5 * benchmark.GIB or hardware_needs_memory():
                break
            row = answer(key)
            stream.write((json.dumps({"questionId": key} | row) + "\n").encode())
            counts.update(correct=int(row["prediction"] == labels[key]["answer"]))
            done += 1
            if done % 64 == 0 or done == stop:
                stream.flush()
                os.fsync(stream.fileno())
                print("FULL_DOWN_CODE_PROGRESS", done, len(ordered), counts["correct"], flush=True)
        stream.flush()
        os.fsync(stream.fileno())
    finally:
        benchmark.ALL_ATTENTION_FUNCTIONS["sdpa"] = original
        for item in items:
            item.close()
    return done


def paired_score(predictions, labels, ordered):
    counts = Counter()
    with (CONTROL / "predictions.jsonl").open() as original, predictions.open() as current:
        for key, before, after in zip(ordered, original, current, strict=True):
            old, new = json.loads(before), json.loads(after)
            assert old["questionId"] == new["questionId"] == key
            target = labels[key]["answer"]
            baseline, calibrated = old["prediction"] == target, new["prediction"] == target
            counts.update(baseline=baseline, calibrated=calibrated, gained=calibrated and not baseline,
                          lost=baseline and not calibrated, changed=old["prediction"] != new["prediction"])
    assert counts["calibrated"] - counts["baseline"] == counts["gained"] - counts["lost"]
    return counts


@benchmark.torch.inference_mode()
def run(output, limit):
    started = time.monotonic()
    assert Path("/.dockerenv").is_file()
    assert int(Path("/sys/fs/cgroup/memory.max").read_text()) <= 3 * benchmark.GIB
    if benchmark.host_available() < 12 * benchmark.GIB or hardware_needs_memory():
        return 75
    torch = benchmark.torch
    torch.set_num_threads(3)
    torch.set_num_interop_threads(1)
    torch.manual_seed(0)
    assert torch.cuda.mem_get_info()[0] >= 12 * benchmark.GIB
    torch.cuda.set_per_process_memory_fraction(0.78)
    torch.cuda.reset_peak_memory_stats()
    dataset, labels, baseline, anchors, codebooks, joint, policies, pins = checked_inputs()
    ordered = sorted(labels)
    tokenizer = benchmark.AutoTokenizer.from_pretrained(benchmark.MODEL, local_files_only=True)
    output.mkdir(exist_ok=True)
    manifest, predictions, receipt = (output / name for name in ("inputs.json", "predictions.jsonl", "receipt.json"))
    configuration = {"checkpoint_revision": benchmark.REVISION, "questions": len(ordered), "prompt": benchmark.PROMPT,
                     "maximum_new_tokens": benchmark.MAX_NEW_TOKENS, "input_sha256": pins}
    with (output / "run.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if manifest.exists():
            assert benchmark.read(manifest) == configuration
        else:
            assert not predictions.exists() and not receipt.exists()
            benchmark.write(manifest, configuration)
        with predictions.open("a+b") as stream:
            stream.seek(0)
            done, _ = recover_predictions(stream, ordered, labels, tokenizer, 1)
            if receipt.exists():
                assert done == len(ordered) and sha256(predictions) == benchmark.read(receipt)["predictions_sha256"]
                return 0
            stop = len(ordered) if limit is None else min(len(ordered), done + limit)
            before = done
            if done < stop:
                done = generate(dataset, labels, tokenizer, anchors, codebooks, joint, policies, ordered, stream, done, stop)
        print("FULL_DOWN_CODE_CHECKPOINT", before, done, len(ordered), flush=True)
        if done < stop:
            return 75
        if done == len(ordered):
            assert all(sha256(Path(name)) == digest for name, digest in pins.items())
            counts = paired_score(predictions, labels, ordered)
            assert counts["baseline"] == baseline["exact_matches"] == 5975
            benchmark.write(receipt, {"state": "full_balanced_testdev_bounded_down_codes_completed", "questions": done,
                                       "accuracy_percent": 100*counts["calibrated"]/done, "paired_counts": dict(counts),
                                       "inputs_sha256": sha256(manifest), "predictions_sha256": sha256(predictions),
                                       "peak_gpu_bytes": torch.cuda.max_memory_allocated(),
                                       "last_invocation_seconds": time.monotonic()-started})
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=lambda value: Path(value).resolve())
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    assert args.limit is None or args.limit > 0
    raise SystemExit(run(args.output, args.limit))
