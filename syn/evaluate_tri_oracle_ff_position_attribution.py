"""Measure first-token and later-token feed-forward error on the fixed holdout."""

import argparse
from collections import Counter
import json
from pathlib import Path
import time

from evaluate_tri_oracle_batch424_joint_pilot import (
    ALL_ATTENTION_FUNCTIONS, FEATURES, GIB, IMAGE_TOKENS, ROOT, AutoTokenizer, CLIPImageProcessorPil,
    CompactDecoder, FeedForward, Image, LlavaForConditionalGeneration, LlavaProcessor, check_memory,
    load_official_sources, score_cases, sha256, torch,
)

REFERENCE = ROOT / ".cache/model_reference"
MODES = ("dense_integer", "float_first_token", "float_later_tokens")
COUNTERS = ("prefill_rows", "decode_rows", "prefill_skipped", "decode_skipped", "prefill_predicted", "decode_predicted")


def read(path):
    return json.loads(path.read_text())


def install_override(replacement, context, layer):
    """Swap selected rows for the unchanged floating feed-forward output."""
    def override(_module, arguments, integer):
        # PyTorch supplies integer [1, tokens, features] from the original integer path.
        if context["mode"] == "dense_integer":
            return None
        # The module input is hidden [1, tokens, features], after learned normalization.
        hidden, = arguments
        assert integer.shape == hidden.shape and hidden.shape[0] == 1 and hidden.shape[2] == FEATURES
        if replacement.decoder.prefill_active:
            assert int(replacement.decoder.positions[0]) == 0 and hidden.shape[1] > 1
            if context["mode"] == "float_first_token":
                # The leading row is the original text token at global position zero.
                # first [1, 1, features] comes from the floating module on that row.
                first = replacement.original(hidden[:, :1, :])
                context["rows"][layer] += 1
                return torch.cat((first, integer[:, 1:, :]), dim=1)
            # later [1, tokens-1, features] comes from the same floating module on the remaining rows.
            later = replacement.original(hidden[:, 1:, :])
            context["rows"][layer] += hidden.shape[1] - 1
            return torch.cat((integer[:, :1, :], later), dim=1)
        if context["mode"] == "float_later_tokens":
            assert hidden.shape[1] == 1 and int(replacement.decoder.positions[0]) > 0
            context["rows"][layer] += 1
            # The current decode row [1, 1, features] follows the floating module.
            return replacement.original(hidden)
        return None

    return replacement.module.register_forward_hook(override)


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
    dense = read(dense_path)
    assert dense["state"] == "dense_integer_feedforward_holdout_scored" and dense["questions"] == 256
    floating_path = REFERENCE / "attention_precision_holdout/receipt.json"
    floating = read(floating_path)
    manifest = REFERENCE / "grouped_precision_holdout/manifest.json"
    samples = read(manifest)["samples"]
    pilot_path = ROOT / "records/batch424_joint_pilot_result.json"
    pilot = read(pilot_path)
    first_path, ordinary_path = (REFERENCE / f"{name}/layer_policy.json" for name in ("format322", "format335"))
    evaluator, normalizer, scorer = load_official_sources(ROOT)
    pins = dense["source_sha256"].copy()
    for name, digest in scorer.items():
        assert pins[name] == digest
    for path in (Path(__file__), dense_path, floating_path, manifest, pilot_path, first_path, ordinary_path):
        digest = sha256(path)
        assert pins.get(str(path), digest) == digest, path
        pins[str(path)] = digest
    assert all(sha256(Path(name)) == digest for name, digest in pins.items())
    assert pilot["checkpoint_revision"] == floating["checkpoint_revision"] == dense["checkpoint_revision"]
    assert len(samples) == len(dense["cases"]) == 256
    assert len({item["image_id"] for item in samples}) == 256

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
    hooks = [install_override(item, context, layer) for layer, item in enumerate(replacements)]
    answers = {mode: [] for mode in MODES}
    ALL_ATTENTION_FUNCTIONS["sdpa"] = decoder.attend
    try:
        for index, sample in enumerate(samples):
            check_memory(13.5 * GIB)
            with Image.open(ROOT / sample["image"]) as opened:
                image = opened.convert("RGB")
            prompt = "USER: <image>\n" + sample["question"] + "\nAnswer the question using a single word or phrase.\nASSISTANT:"
            # Batch tensors are built by the checkpoint processor for one prompt and one image.
            batch = processor(images=image, text=prompt, return_tensors="pt").to("cuda")
            # ids [1, prompt tokens] includes the checkpoint image placeholders.
            ids = batch["input_ids"]
            positions = (ids[0] == model.config.image_token_id).nonzero().flatten().tolist()
            assert ids.shape[0] == 1 and bool(batch["attention_mask"].all())
            assert positions and positions[0] > 0 and positions == list(range(positions[0], positions[0] + IMAGE_TOKENS))
            # embeddings [1, prompt tokens, features] is the unmodified embedding lookup.
            embeddings = model.model.get_input_embeddings()(ids)
            # image_states [image tokens, features] is the projected vision encoder output.
            image_states = torch.cat(model.model.get_image_features(batch["pixel_values"], return_dict=True).pooler_output, dim=0)
            assert image_states.shape == (IMAGE_TOKENS, FEATURES)
            image_states = image_states.to(embeddings.device, embeddings.dtype)
            embeddings = embeddings.masked_scatter(model.model.get_placeholder_mask(ids, embeddings, image_states), image_states)
            for mode in MODES:
                context.update(mode=mode, rows=[0] * len(replacements))
                for replacement in replacements:
                    replacement.begin(True, False)
                tokens = decoder.generate(embeddings, positions[0], "compact_and_streaming", {2}, None)
                offsets = [0] + list(range(ids.shape[1], ids.shape[1] + len(tokens) - 1))
                for layer, replacement in enumerate(replacements):
                    assert replacement.positions == offsets and replacement.residual is None
                    assert replacement.prefill_rows == decoder.layer_slots[layer] and replacement.decode_rows == len(tokens) - 1
                    assert replacement.prefill_skipped == replacement.decode_skipped == 0
                    wanted = {"dense_integer": 0, "float_first_token": 1,
                              "float_later_tokens": replacement.prefill_rows - 1 + replacement.decode_rows}
                    assert context["rows"][layer] == wanted[mode]
                counts = {key: sum(getattr(item, key) for item in replacements) for key in COUNTERS}
                case = dict(question_id=sample["question_id"], image_id=sample["image_id"], answer_tokens=tokens,
                    answer=tokenizer.decode(tokens, skip_special_tokens=True), prefill_tokens=ids.shape[1],
                    prefill_slots=sum(decoder.layer_slots), prefill_pairs=decoder.pairs, streaming_heads=decoder.streaming_count,
                    final_image_roots=decoder.layer_roots[-1]) | counts
                if mode == "dense_integer":
                    assert case == dense["cases"][index], (index, sample["question_id"])
                answers[mode].append(case | {"floating_feedforward_rows": sum(context["rows"])})
            print("FF_POSITION_CASE", index + 1, sample["question_id"], flush=True)
    finally:
        ALL_ATTENTION_FUNCTIONS["sdpa"] = original
        for hook, replacement in zip(hooks, replacements, strict=True):
            hook.remove()
            replacement.close()

    scores = {mode: score_cases(samples, cases, evaluator, normalizer) for mode, cases in answers.items()}
    scores["floating_reference"] = score_cases(samples, floating["cases"]["compact_and_streaming"], evaluator, normalizer)
    for score in scores.values():
        score["official_vqa_consensus_percent"] = score.pop("official_vqa_consensus_percent_on64")
    assert scores["dense_integer"] == dense["score"]
    assert scores["floating_reference"] == floating["scores"]["compact_and_streaming"]
    before = scores["dense_integer"]["per_question_score"]
    paired = {}
    for mode in MODES[1:]:
        after = scores[mode]["per_question_score"]
        count = Counter((after[key] > value) - (after[key] < value) for key, value in before.items())
        paired[mode] = dict(improved=count[1], declined=count[-1], unchanged=count[0])
    assert all(sha256(Path(name)) == digest for name, digest in pins.items())
    result = dict(state="feedforward_position_counterfactuals_scored", questions=len(samples), decoder_layers=len(replacements),
                  reproduced_dense_integer_cases=len(answers["dense_integer"]), scores=scores, paired_changes=paired, answers=answers,
                  source_sha256=pins, wall_seconds=time.monotonic()-started, peak_graphics_bytes=torch.cuda.max_memory_allocated(),
                  scope="Software diagnostics of feed-forward numerical error on the fixed holdout. The floating rows are counterfactuals.")
    with (output / "receipt.json").open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print("FF_POSITION_SCORED", {mode: score["official_vqa_consensus_percent"] for mode, score in scores.items()}, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    run(parser.parse_args().output.resolve())
