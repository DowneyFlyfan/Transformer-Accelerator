"""Measure trained channel-scaled weights with feed-forward prediction enabled."""

import argparse
from collections import Counter
from decimal import Decimal
import json
from pathlib import Path
import time

from evaluate_tri_oracle_channel_scaled_down import (
    ALL_ATTENTION_FUNCTIONS, AutoTokenizer, CLIPImageProcessorPil, CompactDecoder, COUNTERS, FEATURES,
    FeedForward, GIB, IMAGE_TOKENS, Image, LlavaForConditionalGeneration, LlavaProcessor, REFERENCE,
    ROOT, check_memory, install_channel_scaling, load_official_sources, read, score_cases, sha256, torch,
)

MODES = ("channel_scaled_down", "channel_scaled_down_pruned")
CHANNELS = 5632


@torch.inference_mode()
def run(output):
    start = time.monotonic()
    torch.set_num_threads(3)
    torch.set_num_interop_threads(1)
    torch.manual_seed(0)
    check_memory(16 * GIB)
    assert torch.cuda.mem_get_info()[0] > 12 * GIB
    torch.cuda.set_per_process_memory_fraction(0.78)
    torch.cuda.reset_peak_memory_stats()
    prior_path = REFERENCE / "ff_channel_scaled_down_holdout/receipt.json"
    verified_path = ROOT / "records/ff_channel_scaled_down_holdout_result.json"
    prior, verified = read(prior_path), read(verified_path)
    assert verified["state"] == "channel_scaled_down_projection_benchmark_independently_scored"
    assert verified["checkpoint_revision"] == prior["checkpoint_revision"] and prior["questions"] == 256
    assert verified["evidence_sha256"][str(prior_path.relative_to(ROOT))] == sha256(prior_path)
    pins = prior["source_sha256"].copy()
    anchors = {str(ROOT / name): digest for name, digest in verified["evidence_sha256"].items()}
    anchors.update({str(path): sha256(path) for path in (Path(__file__), verified_path)})
    for name, digest in anchors.items():
        assert pins.get(name, digest) == digest, name
        pins[name] = digest
    assert all(sha256(Path(name)) == digest for name, digest in pins.items())
    pilot = read(ROOT / "records/batch424_joint_pilot_result.json")
    samples = read(REFERENCE / "grouped_precision_holdout/manifest.json")["samples"]
    assert len(samples) == len({sample["image_id"] for sample in samples}) == 256
    evaluator, normalizer, scorer = load_official_sources(ROOT)
    assert all(pins[name] == digest for name, digest in scorer.items())

    model_dir = REFERENCE / "tiny_llava_v1"
    tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
    processor = LlavaProcessor(image_processor=CLIPImageProcessorPil.from_pretrained(model_dir, local_files_only=True),
        tokenizer=tokenizer, patch_size=14, vision_feature_select_strategy="default", num_additional_image_tokens=1)
    model = LlavaForConditionalGeneration.from_pretrained(model_dir, local_files_only=True, dtype=torch.float32,
        attn_implementation="sdpa", use_kernels=False, device_map={"": "cuda:0"}).eval()
    assert all(parameter.device.type == "cuda" for parameter in model.parameters())
    assert model.generation_config.eos_token_id == 2 and model.generation_config.num_beams in (None, 1)
    original = ALL_ATTENTION_FUNCTIONS["sdpa"]
    decoder = CompactDecoder(model, original, tuple(pilot["local_ratio"]))
    first, ordinary = (read(REFERENCE / f"{name}/layer_policy.json")["layers"] for name in ("format322", "format335"))
    replacements = [FeedForward(layer, decoder, zero, regular)
                    for layer, zero, regular in zip(decoder.language.layers, first, ordinary, strict=True)]
    context = {}
    scales = [install_channel_scaling(item, i, layer.mlp.down_proj.weight, context)
              for i, (item, layer) in enumerate(zip(replacements, decoder.language.layers, strict=True))]
    assert scales == prior["channel_scale_exponent_ranges"] and len(replacements) == 22
    cases = {mode: [] for mode in MODES}
    ALL_ATTENTION_FUNCTIONS["sdpa"] = decoder.attend
    try:
        for index, sample in enumerate(samples):
            check_memory(15.5 * GIB)
            with Image.open(ROOT / sample["image"]) as opened:
                image = opened.convert("RGB")
            prompt = "USER: <image>\n" + sample["question"] + "\nAnswer the question using a single word or phrase.\nASSISTANT:"
            batch = processor(images=image, text=prompt, return_tensors="pt").to("cuda")
            ids = batch["input_ids"]  # [1, prompt tokens] with the contiguous image-placeholder span.
            positions = (ids[0] == model.config.image_token_id).nonzero().flatten().tolist()
            assert ids.shape[0] == 1 and bool(batch["attention_mask"].all())
            assert positions and positions[0] > 0 and positions == list(range(positions[0], positions[0] + IMAGE_TOKENS))
            embeddings = model.model.get_input_embeddings()(ids)  # [1, prompt tokens, hidden features]
            # Projected image states [image tokens, hidden features] replace the placeholder embeddings.
            states = torch.cat(model.model.get_image_features(batch["pixel_values"], return_dict=True).pooler_output, dim=0)
            assert states.shape == (IMAGE_TOKENS, FEATURES)
            states = states.to(embeddings.device, embeddings.dtype)
            embeddings = embeddings.masked_scatter(model.model.get_placeholder_mask(ids, embeddings, states), states)
            for mode in MODES:
                prune = mode == "channel_scaled_down_pruned"
                context.update(mode=mode, calls=[0] * 22, scaled_rows=[0] * 22)
                for item in replacements:
                    item.begin(True, prune)
                tokens = decoder.generate(embeddings, positions[0], "compact_and_streaming", {2}, None)
                offsets = [0] + list(range(ids.shape[1], ids.shape[1] + len(tokens) - 1))
                for layer, item in enumerate(replacements):
                    assert item.positions == offsets and item.residual is None
                    assert item.prefill_rows == decoder.layer_slots[layer] and item.decode_rows == len(tokens) - 1
                    assert item.prefill_skipped == (item.prefill_predicted if prune else 0)
                    assert item.decode_skipped == (item.decode_predicted if prune else 0)
                    assert context["scaled_rows"][layer] == item.prefill_rows + item.decode_rows - 1
                counts = {key: sum(getattr(item, key) for item in replacements) for key in COUNTERS}
                case = dict(question_id=sample["question_id"], image_id=sample["image_id"], answer_tokens=tokens,
                    answer=tokenizer.decode(tokens, skip_special_tokens=True), prefill_tokens=ids.shape[1],
                    prefill_slots=sum(decoder.layer_slots), prefill_pairs=decoder.pairs, streaming_heads=decoder.streaming_count,
                    final_image_roots=decoder.layer_roots[-1], channel_scaled_rows=sum(context["scaled_rows"])) | counts
                if not prune:
                    assert case == prior["answers"][mode][index], (index, sample["question_id"])
                cases[mode].append(case)
            print("FF_SCALED_PRUNE_CASE", index + 1, sample["question_id"], flush=True)
    finally:
        ALL_ATTENTION_FUNCTIONS["sdpa"] = original
        for item in replacements:
            item.close()

    scores = {mode: score_cases(samples, answers, evaluator, normalizer) for mode, answers in cases.items()}
    for score in scores.values():
        score["official_vqa_consensus_percent"] = score.pop("official_vqa_consensus_percent_on64")
    assert scores[MODES[0]] == prior["scores"][MODES[0]]
    assert all(sha256(Path(name)) == digest for name, digest in pins.items())
    baseline, pruned = (scores[mode]["per_question_score"] for mode in MODES)
    paired = Counter((pruned[q] > before) - (pruned[q] < before) for q, before in baseline.items())
    percents = {mode: score["official_vqa_consensus_percent"] for mode, score in scores.items()}
    delta = Decimal(str(percents[MODES[1]])) - Decimal(str(percents[MODES[0]]))
    work = {}
    for name in ("prefill", "decode"):
        rows = sum(row[f"{name}_rows"] for row in cases[MODES[1]])
        skipped = sum(row[f"{name}_skipped"] for row in cases[MODES[1]])
        assert 0 < skipped <= rows * CHANNELS
        work[name] = dict(rows=rows, skipped_channels=skipped, channel_opportunities=rows * CHANNELS)
    result = dict(state="scaled_down_and_pruned_local_benchmark_scored", questions=256,
        reproduced_control_cases=256, decoder_layers=22, checkpoint_revision=prior["checkpoint_revision"],
        scores=scores, scores_percent=percents, change_percentage_points=float(delta), answers=cases,
        paired_question_scores=dict(improved=paired[1], declined=paired[-1], unchanged=paired[0]), work=work,
        source_sha256=pins, wall_seconds=time.monotonic()-start, graphics_peak_bytes=torch.cuda.max_memory_allocated(),
        scope="Fixed local benchmark with cumulative token merging, streaming heads and prepared weight-skip prediction.")
    with (output / "receipt.json").open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print("FF_SCALED_PRUNE_SCORED", percents, work, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    run(parser.parse_args().output.resolve())
