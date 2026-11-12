"""Locate the integer feed-forward accuracy loss on the archived GQA panel."""

import argparse
from collections import Counter
import json
from pathlib import Path
import time

from run_pruned_accuracy_ablation import benchmark, encode
from verify_tri_oracle_packed_down_weights import ROOT, sha256


DATA = ROOT / ".cache/model_reference/gqa_testdev"
MODE = "compact_and_streaming"
PHASES = {"integer_both": (True, True), "float_prefill": (False, True), "float_decode": (True, False)}


def phase_tokens(decoder, replacements, context, embeddings, image_start, eos, prefill_integer, decode_integer):
    """Use the shared image/text embeddings [1,T,H] returned by encode.

    T is the prompt length and H is the hidden width. Both decoder calls
    return one logit vector [V], where V is the vocabulary size.
    """
    context.update(mode="channel_scaled_down_pruned", calls=[0] * 22, scaled_rows=[0] * 22)
    for layer in replacements:
        layer.begin(prefill_integer, False)
    logits = decoder.prefill(embeddings, image_start, MODE, embeddings.shape[1], None)  # [V], final prompt row.
    for index, layer in enumerate(replacements):
        assert layer.prefill_rows == (decoder.layer_slots[index] if prefill_integer else 0)
        assert layer.prefill_skipped == 0 and layer.residual is None
        layer.begin(decode_integer, False)
    tokens = []
    for step in range(benchmark.MAX_NEW_TOKENS):
        token = logits.argmax()  # Scalar vocabulary index, selected greedily from [V].
        tokens.append(int(token))
        if tokens[-1] == eos or step + 1 == benchmark.MAX_NEW_TOKENS:
            break
        logits = decoder.decode(token)  # [V], following the generated token.
    assert decoder.decode_steps == len(tokens) - 1
    for layer in replacements:
        assert layer.decode_rows == (decoder.decode_steps if decode_integer else 0)
        assert layer.decode_skipped == 0 and layer.residual is None
    return tokens


def archived_panel(pins):
    directory = DATA / "paired_ablation"
    archive = directory / "independent_receipt.json"
    prior = benchmark.read(archive)
    assert prior["state"] == "gqa_paired_accuracy_ablation_independently_rescored"
    assert prior["matches"]["integer_feedforward"] == 89 and prior["matches"]["streaming_heads"] == 106
    for name, expected in prior["evidence_sha256"].items():
        assert sha256(Path(name)) == expected
        assert pins.setdefault(name, expected) == expected
    config = benchmark.read(directory / "inputs.json")
    assert config["checkpoint_revision"] == benchmark.REVISION and config["prompt"] == benchmark.PROMPT
    assert config["decoder_max_new_tokens"] == benchmark.MAX_NEW_TOKENS
    panel = sorted(key for group in config["panel"].values() for key in group)
    assert len(panel) == len(set(panel)) == prior["questions"] == 160
    controls = {}
    with (directory / "predictions.jsonl").open() as stream:
        for key, line in zip(panel, stream, strict=True):
            row = json.loads(line)
            assert row["questionId"] == key
            controls[key] = row["modes"]["integer_feedforward"]["tokens"]
    pins[str(archive)] = sha256(archive)
    return config, panel, controls


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
    prior_config, panel, controls = archived_panel(pins)
    joint = ROOT / "records/batch424_joint_pilot_result.json"
    policies = [benchmark.REFERENCE / directory / "layer_policy.json" for directory in ("format322", "format335")]
    for file in (joint, *policies):
        digest = sha256(file)
        assert digest == prior_config["input_sha256"][str(file)]
        pins[str(file)] = digest
    for file in (Path(__file__).resolve(), Path(encode.__code__.co_filename).resolve()):
        digest = sha256(file)
        assert pins.setdefault(str(file), digest) == digest

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
    decoder = benchmark.CompactDecoder(model, original, tuple(benchmark.read(joint)["local_ratio"]))
    first, ordinary = (benchmark.read(path)["layers"] for path in policies)
    layers = decoder.language.layers
    replacements = [benchmark.FeedForward(layer, decoder, initial, later)
                    for layer, initial, later in zip(layers, first, ordinary, strict=True)]
    context = {}
    for index, (item, layer) in enumerate(zip(replacements, layers, strict=True)):
        benchmark.install_channel_scaling(item, index, layer.mlp.down_proj.weight, context)  # [H,K], down weights.
    assert len(replacements) == 22

    output.mkdir()
    manifest = output / "inputs.json"
    benchmark.write(manifest, {"checkpoint_revision": benchmark.REVISION, "panel": panel, "modes": PHASES,
                               "input_sha256": pins, "prompt": benchmark.PROMPT, "weight_skipping": False})
    predictions = output / "predictions.jsonl"
    counts = Counter()
    benchmark.ALL_ATTENTION_FUNCTIONS["sdpa"] = decoder.attend
    try:
        with predictions.open("x", buffering=1) as stream:
            for index, key in enumerate(panel, 1):
                assert benchmark.host_available() >= 14.5 * benchmark.GIB
                label = labels[key]
                # [1,T,H] checkpoint embeddings and scalar image start position.
                embeddings, image_start = encode(model, processor, images[label["imageId"]], label["question"])
                results = {}
                for mode, flags in PHASES.items():
                    tokens = phase_tokens(decoder, replacements, context, embeddings, image_start,
                                          tokenizer.eos_token_id, *flags)
                    if mode == "integer_both":
                        assert tokens == controls[key], key
                    results[mode] = tokens
                    counts[mode] += benchmark.normalize(tokenizer.decode(tokens, skip_special_tokens=True)) == label["answer"]
                stream.write(json.dumps({"questionId": key, "tokens": results}) + "\n")
                if index % 8 == 0:
                    print("GQA_PHASE_PRECISION_PROGRESS", index, len(panel), dict(counts), flush=True)
    finally:
        benchmark.ALL_ATTENTION_FUNCTIONS["sdpa"] = original
        for item in replacements:
            item.close()
    assert counts["integer_both"] == 89 and all(sha256(Path(name)) == digest for name, digest in pins.items())
    report = {"state": "paired_gqa_phase_precision_completed", "questions": len(panel), "exact_matches": dict(counts),
              "elapsed_seconds": time.monotonic() - started, "peak_gpu_bytes": torch.cuda.max_memory_allocated(),
              "inputs_sha256": sha256(manifest), "predictions_sha256": sha256(predictions)}
    benchmark.write(output / "receipt.json", report)
    print(report["state"], dict(counts), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=lambda value: Path(value).resolve())
    run(parser.parse_args().output)
