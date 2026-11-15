"""Localize the prompt feed-forward precision gap on the fixed question panel."""

import argparse
from collections import Counter
import fcntl
import json
import os
from pathlib import Path

from evaluate_tri_oracle_gqa_phase_precision import DATA, MODE, archived_panel, phase_tokens
from measure_tri_oracle_input_equalization import GIB, LAYERS
from run_pruned_accuracy_ablation import benchmark, encode
from run_tri_oracle_full_down_code_gqa import hardware_needs_memory
from verify_tri_oracle_packed_down_weights import ROOT, sha256


torch = benchmark.torch
GROUPS = {"layers_00_05": (0, 6), "layers_06_10": (6, 11),
          "layers_11_16": (11, 17), "layers_17_21": (17, 22)}
JOINT = ROOT / "records/batch424_joint_pilot_result.json"
POLICIES = tuple(benchmark.REFERENCE / directory / "layer_policy.json" for directory in ("format322", "format335"))


def prepare():
    dataset, labels, pins = benchmark.inputs()
    old_config, panel, integer_controls = archived_panel(pins)
    assert [layer for bounds in GROUPS.values() for layer in range(*bounds)] == list(range(LAYERS))
    phase = DATA / "phase_precision"
    files = {name: phase / name for name in ("inputs.json", "predictions.jsonl", "receipt.json")}
    receipt = benchmark.read(files["receipt.json"])
    assert receipt["state"] == "paired_gqa_phase_precision_completed"
    assert receipt["questions"] == len(panel) and receipt["exact_matches"]["float_prefill"] == 106
    assert sha256(files["inputs.json"]) == receipt["inputs_sha256"]
    assert sha256(files["predictions.jsonl"]) == receipt["predictions_sha256"]
    settings = benchmark.read(files["inputs.json"])
    assert settings["panel"] == panel and settings["checkpoint_revision"] == benchmark.REVISION
    assert settings["prompt"] == benchmark.PROMPT and settings["weight_skipping"] is False
    controls = {}
    with files["predictions.jsonl"].open() as stream:
        for key, line in zip(panel, stream, strict=True):
            row = json.loads(line)
            assert row["questionId"] == key and row["tokens"]["integer_both"] == integer_controls[key]
            controls[key] = row["tokens"]
    for path in (JOINT, *POLICIES):
        checksum = sha256(path)
        assert checksum == old_config["input_sha256"][str(path)]
        pins[str(path)] = checksum
    for path in (*files.values(), Path(__file__).resolve(), Path(encode.__code__.co_filename),
                 Path(phase_tokens.__code__.co_filename)):
        checksum = sha256(path)
        assert pins.setdefault(str(path), checksum) == checksum
    return dataset, labels, panel, controls, pins


def group_tokens(decoder, replacements, context, embeddings, image_start, eos, bounds):
    """Run a diagnostic prefill mask on the original prompt embeddings [1,T,H]."""
    lo, hi = bounds
    context.update(mode="channel_scaled_down_pruned", calls=[0] * LAYERS, scaled_rows=[0] * LAYERS)
    for index, item in enumerate(replacements):
        item.begin(not lo <= index < hi, False)
    logits = decoder.prefill(embeddings, image_start, MODE, embeddings.shape[1], None)  # [V], next token scores
    for index, item in enumerate(replacements):
        expected = 0 if lo <= index < hi else decoder.layer_slots[index]
        assert item.prefill_rows == expected and item.prefill_skipped == 0 and item.residual is None
        item.begin(True, False)
    tokens = []
    for step in range(benchmark.MAX_NEW_TOKENS):
        token = logits.argmax()  # Scalar greedy token ID
        tokens.append(int(token))
        if tokens[-1] == eos or step + 1 == benchmark.MAX_NEW_TOKENS:
            break
        logits = decoder.decode(token)  # [V], same integer answer-generation path
    assert all(item.decode_rows == decoder.decode_steps and item.decode_skipped == 0 and
               item.residual is None for item in replacements)
    return tokens


def score(row, key, labels, tokenizer):
    assert row["questionId"] == key and row["groups"].keys() == GROUPS.keys()
    counts = Counter()
    for group, tokens in row["groups"].items():
        assert 1 <= len(tokens) <= benchmark.MAX_NEW_TOKENS
        assert tokens[-1] == tokenizer.eos_token_id or len(tokens) == benchmark.MAX_NEW_TOKENS
        response = benchmark.normalize(tokenizer.decode(tokens, skip_special_tokens=True))
        counts[group] += response == labels[key]["answer"]
    return counts


def recover(stream, panel, labels, tokenizer):
    stream.seek(0)
    done, offset, counts = 0, 0, Counter()
    while line := stream.readline():
        if not line.endswith(b"\n"):
            break
        assert done < len(panel)
        counts.update(score(json.loads(line), panel[done], labels, tokenizer))
        done += 1
        offset = stream.tell()
    stream.seek(offset)
    stream.truncate()
    return done, counts


@torch.inference_mode()
def run(output):
    assert Path("/.dockerenv").is_file() and __debug__
    assert int(Path("/sys/fs/cgroup/memory.max").read_text()) <= 3 * GIB
    if benchmark.host_available() < 12 * GIB or torch.cuda.mem_get_info()[0] < 12 * GIB or hardware_needs_memory():
        return 75
    torch.set_num_threads(3)
    torch.set_num_interop_threads(1)
    torch.manual_seed(0)
    torch.cuda.set_per_process_memory_fraction(0.78)
    torch.cuda.reset_peak_memory_stats()
    dataset, labels, panel, controls, pins = prepare()
    images = benchmark.load_images(dataset)
    tokenizer = benchmark.AutoTokenizer.from_pretrained(benchmark.MODEL, local_files_only=True)
    processor = benchmark.LlavaProcessor(
        image_processor=benchmark.CLIPImageProcessorPil.from_pretrained(benchmark.MODEL, local_files_only=True),
        tokenizer=tokenizer, patch_size=14, vision_feature_select_strategy="default", num_additional_image_tokens=1,
    )
    model = benchmark.LlavaForConditionalGeneration.from_pretrained(
        benchmark.MODEL, local_files_only=True, dtype=torch.float32, attn_implementation="sdpa",
        use_kernels=False, device_map={"": "cuda:0"},
    ).eval()
    assert model.generation_config.eos_token_id == tokenizer.eos_token_id == 2
    original = benchmark.ALL_ATTENTION_FUNCTIONS["sdpa"]
    decoder = benchmark.CompactDecoder(model, original, tuple(benchmark.read(JOINT)["local_ratio"]))
    first, ordinary = (benchmark.read(path)["layers"] for path in POLICIES)
    layers = decoder.language.layers
    replacements = [benchmark.FeedForward(layer, decoder, initial, later)
                    for layer, initial, later in zip(layers, first, ordinary, strict=True)]
    context = {}
    for index, (item, layer) in enumerate(zip(replacements, layers, strict=True)):
        benchmark.install_channel_scaling(item, index, layer.mlp.down_proj.weight, context)  # [H,K]

    def embed(key):
        item = labels[key]
        return encode(model, processor, images[item["imageId"]], item["question"])  # [1,T,H], scalar position

    chosen = {}
    for key in panel:
        chosen.setdefault(labels[key]["types"]["structural"], key)
    assert len(chosen) == 5
    output.mkdir(exist_ok=True)
    manifest, predictions = (output / name for name in ("inputs.json", "predictions.jsonl"))
    configuration = {"checkpoint_revision": benchmark.REVISION, "panel": panel,
                     "groups": {name: list(bounds) for name, bounds in GROUPS.items()},
                     "prompt": benchmark.PROMPT, "maximum_new_tokens": benchmark.MAX_NEW_TOKENS,
                     "input_sha256": pins}
    benchmark.ALL_ATTENTION_FUNCTIONS["sdpa"] = decoder.attend
    try:
        for key in chosen.values():
            embeddings, image_start = embed(key)  # [1,T,H], scalar position
            for mode, flags in (("integer_both", (True, True)), ("float_prefill", (False, True))):
                tokens = phase_tokens(decoder, replacements, context, embeddings, image_start,
                                      tokenizer.eos_token_id, *flags)
                assert tokens == controls[key][mode], (key, mode)
        print("GQA_LAYER_GROUP_CONTROL_TOKENS_MATCHED", len(chosen), flush=True)
        with (output / "run.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if manifest.exists():
                assert benchmark.read(manifest) == configuration
            else:
                assert not predictions.exists()
                benchmark.write(manifest, configuration)
            with predictions.open("a+b") as stream:
                done, counts = recover(stream, panel, labels, tokenizer)
                for completed, key in enumerate(panel[done:], done + 1):
                    if benchmark.host_available() < 8.5 * GIB or hardware_needs_memory():
                        return 75
                    embeddings, image_start = embed(key)  # [1,T,H], scalar position
                    row = {"questionId": key, "groups": {
                        name: group_tokens(decoder, replacements, context, embeddings, image_start,
                                           tokenizer.eos_token_id, bounds)
                        for name, bounds in GROUPS.items()}}
                    counts.update(score(row, key, labels, tokenizer))
                    stream.write((json.dumps(row) + "\n").encode())
                    if completed % 8 == 0:
                        stream.flush()
                        os.fsync(stream.fileno())
                        print("GQA_LAYER_GROUP_PROGRESS", completed, len(panel), dict(counts), flush=True)
            assert all(sha256(Path(name)) == checksum for name, checksum in pins.items())
            benchmark.write(output / "receipt.json",
                            dict(state="gqa_prompt_precision_layer_groups_completed", questions=len(panel),
                                 exact_matches=dict(counts), controls_reexecuted=len(chosen) * 2,
                                 inputs_sha256=sha256(manifest), predictions_sha256=sha256(predictions),
                                 peak_gpu_bytes=torch.cuda.max_memory_allocated()))
    finally:
        benchmark.ALL_ATTENTION_FUNCTIONS["sdpa"] = original
        for item in replacements:
            item.close()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    raise SystemExit(run(args.output.resolve()))
