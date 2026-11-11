"""Score output-channel down-projection scales on the fixed 256-question benchmark."""

import argparse
from copy import copy
import json
from pathlib import Path
import time

from evaluate_tri_oracle_ff_position_attribution import (
    ALL_ATTENTION_FUNCTIONS, AutoTokenizer, CLIPImageProcessorPil, CompactDecoder, COUNTERS, FEATURES,
    FeedForward, GIB, IMAGE_TOKENS, Image, LlavaForConditionalGeneration, LlavaProcessor, REFERENCE,
    ROOT, check_memory, load_official_sources, read, score_cases, sha256, torch,
)
from tri_oracle_integer_reference import _quantize

MODES = ("dense_integer", "channel_scaled_down")


def install_channel_scaling(replacement, layer, weight, context):
    """Reuse exact integer evaluation with alternate down weights [outputs, channels]."""
    original = replacement.reference.evaluate
    scaled = copy(replacement.reference)
    # Signed8 codes [outputs, channels] and one power-of-two exponent per output.
    scaled.down, exponents = _quantize(weight, per_row=True)
    scaled.down_exponent = exponents.T  # [1, outputs], broadcast with each row's integer format.
    assert scaled.down.dtype == torch.int8 and scaled.down.shape == replacement.reference.down.shape

    def evaluate(activation, residual, **settings):
        # Input and residual both have [retained rows, hidden features].
        first = replacement.decoder.prefill_active and context["calls"][layer] == 0
        context["calls"][layer] += 1
        if first:
            assert activation.shape[0] == 1 and int(replacement.decoder.positions[0]) == 0
        if first or context["mode"] == "dense_integer":
            return original(activation, residual, **settings)
        context["scaled_rows"][layer] += activation.shape[0]
        return scaled.evaluate(activation, residual, **settings)

    replacement.reference.evaluate = evaluate
    return [int(exponents.min()), int(exponents.max())]


@torch.inference_mode()
def run(output):
    started = time.monotonic()
    torch.set_num_threads(3)
    torch.set_num_interop_threads(1)
    torch.manual_seed(0)
    check_memory(16 * GIB)
    assert torch.cuda.mem_get_info()[0] > 12 * GIB
    torch.cuda.set_per_process_memory_fraction(0.78)
    torch.cuda.reset_peak_memory_stats()

    dense_path = REFERENCE / "dense_integer_holdout/receipt.json"
    diagnostic_path = ROOT / "records/ff_quantization_sources.json"
    dense, diagnostic = read(dense_path), read(diagnostic_path)
    assert dense["state"] == "dense_integer_feedforward_holdout_scored" and dense["questions"] == 256
    assert diagnostic["layers_improved_by_output_channel_down_scales"] == 22
    assert diagnostic["checkpoint_revision"] == dense["checkpoint_revision"]
    manifest = REFERENCE / "grouped_precision_holdout/manifest.json"
    samples = read(manifest)["samples"]
    assert len(samples) == len(dense["cases"]) == 256 and len({item["image_id"] for item in samples}) == 256
    pilot_path = ROOT / "records/batch424_joint_pilot_result.json"
    pilot = read(pilot_path)
    assert pilot["checkpoint_revision"] == dense["checkpoint_revision"]
    first_path, ordinary_path = (REFERENCE / f"{name}/layer_policy.json" for name in ("format322", "format335"))
    evaluator, normalizer, scorer = load_official_sources(ROOT)
    pins = dense["source_sha256"].copy()
    evidence = scorer | {str(ROOT / path): digest for path, digest in diagnostic["evidence_sha256"].items()}
    evidence.update({str(path): sha256(path) for path in (
        Path(__file__), dense_path, diagnostic_path, manifest, pilot_path, first_path, ordinary_path)})
    for name, digest in evidence.items():
        assert pins.get(name, digest) == digest, name
        pins[name] = digest
    assert all(sha256(Path(name)) == digest for name, digest in pins.items())

    model_dir = REFERENCE / "tiny_llava_v1"
    tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
    processor = LlavaProcessor(image_processor=CLIPImageProcessorPil.from_pretrained(model_dir, local_files_only=True),
                               tokenizer=tokenizer, patch_size=14, vision_feature_select_strategy="default",
                               num_additional_image_tokens=1)
    model = LlavaForConditionalGeneration.from_pretrained(model_dir, local_files_only=True, dtype=torch.float32,
        attn_implementation="sdpa", use_kernels=False, device_map={"": "cuda:0"}).eval()
    assert all(parameter.device.type == "cuda" for parameter in model.parameters())
    assert model.generation_config.eos_token_id == 2 and model.generation_config.num_beams in (None, 1)
    original = ALL_ATTENTION_FUNCTIONS["sdpa"]
    decoder = CompactDecoder(model, original, tuple(pilot["local_ratio"]))
    first, ordinary = (read(path)["layers"] for path in (first_path, ordinary_path))
    replacements = [FeedForward(layer, decoder, zero, regular)
                    for layer, zero, regular in zip(decoder.language.layers, first, ordinary, strict=True)]
    assert len(replacements) == 22
    context = {}
    scales = [install_channel_scaling(item, index, layer.mlp.down_proj.weight, context)
              for index, (item, layer) in enumerate(zip(replacements, decoder.language.layers, strict=True))]
    assert [min(lo for lo, _ in scales), max(hi for _, hi in scales)] == diagnostic["observed_channel_scale_exponent_range"]
    answers = {mode: [] for mode in MODES}
    ALL_ATTENTION_FUNCTIONS["sdpa"] = decoder.attend
    try:
        for index, sample in enumerate(samples):
            check_memory(15.5 * GIB)
            with Image.open(ROOT / sample["image"]) as opened:
                image = opened.convert("RGB")
            prompt = "USER: <image>\n" + sample["question"] + "\nAnswer the question using a single word or phrase.\nASSISTANT:"
            # The checkpoint processor builds one image and one text prompt.
            batch = processor(images=image, text=prompt, return_tensors="pt").to("cuda")
            ids = batch["input_ids"]  # [1, prompt tokens], including the image placeholder span.
            positions = (ids[0] == model.config.image_token_id).nonzero().flatten().tolist()
            assert ids.shape[0] == 1 and bool(batch["attention_mask"].all())
            assert positions and positions[0] > 0 and positions == list(range(positions[0], positions[0] + IMAGE_TOKENS))
            embeddings = model.model.get_input_embeddings()(ids)  # [1, prompt tokens, hidden features]
            # Projected image rows [image tokens, hidden features] replace the image placeholders.
            image_states = torch.cat(model.model.get_image_features(batch["pixel_values"], return_dict=True).pooler_output, dim=0)
            assert image_states.shape == (IMAGE_TOKENS, FEATURES)
            image_states = image_states.to(embeddings.device, embeddings.dtype)
            embeddings = embeddings.masked_scatter(model.model.get_placeholder_mask(ids, embeddings, image_states), image_states)
            for mode in MODES:
                context.update(mode=mode, calls=[0] * 22, scaled_rows=[0] * 22)
                for replacement in replacements:
                    replacement.begin(True, False)
                tokens = decoder.generate(embeddings, positions[0], "compact_and_streaming", {2}, None)
                offsets = [0] + list(range(ids.shape[1], ids.shape[1] + len(tokens) - 1))
                for layer, replacement in enumerate(replacements):
                    assert replacement.positions == offsets and replacement.residual is None
                    assert replacement.prefill_rows == decoder.layer_slots[layer] and replacement.decode_rows == len(tokens) - 1
                    assert replacement.prefill_skipped == replacement.decode_skipped == 0
                    expected = 0 if mode == "dense_integer" else replacement.prefill_rows + replacement.decode_rows - 1
                    assert context["scaled_rows"][layer] == expected
                counts = {key: sum(getattr(item, key) for item in replacements) for key in COUNTERS}
                case = dict(question_id=sample["question_id"], image_id=sample["image_id"], answer_tokens=tokens,
                    answer=tokenizer.decode(tokens, skip_special_tokens=True), prefill_tokens=ids.shape[1],
                    prefill_slots=sum(decoder.layer_slots), prefill_pairs=decoder.pairs, streaming_heads=decoder.streaming_count,
                    final_image_roots=decoder.layer_roots[-1]) | counts
                if mode == "dense_integer":
                    assert case == dense["cases"][index], (index, sample["question_id"])
                answers[mode].append(case | {"channel_scaled_rows": sum(context["scaled_rows"])})
            print("FF_CHANNEL_SCALED_CASE", index + 1, sample["question_id"], flush=True)
    finally:
        ALL_ATTENTION_FUNCTIONS["sdpa"] = original
        for replacement in replacements:
            replacement.close()

    scores = {mode: score_cases(samples, cases, evaluator, normalizer) for mode, cases in answers.items()}
    for score in scores.values():
        score["official_vqa_consensus_percent"] = score.pop("official_vqa_consensus_percent_on64")
    assert scores["dense_integer"] == dense["score"]
    assert all(sha256(Path(name)) == digest for name, digest in pins.items())
    result = dict(state="channel_scaled_down_projection_benchmark_scored", questions=len(samples),
        decoder_layers=len(replacements), checkpoint_revision=dense["checkpoint_revision"],
        reproduced_dense_integer_cases=len(answers["dense_integer"]), scores=scores, answers=answers,
        channel_scale_exponent_ranges=scales, source_sha256=pins, wall_seconds=time.monotonic() - started,
        graphics_peak_allocated_bytes=torch.cuda.max_memory_allocated(),
        scope="Fixed local benchmark with frozen signed8 channel scales on later rows and dense feed-forward execution.")
    with (output / "receipt.json").open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print("FF_CHANNEL_SCALED_SCORED", {mode: score["official_vqa_consensus_percent"] for mode, score in scores.items()}, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    run(parser.parse_args().output.resolve())
