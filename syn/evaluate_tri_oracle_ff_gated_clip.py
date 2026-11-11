"""Measure the isolated effect of the intermediate gated-product clip."""

import argparse
import inspect
import json
from pathlib import Path
import textwrap
import time

from evaluate_tri_oracle_ff_position_attribution import (
    ALL_ATTENTION_FUNCTIONS, AutoTokenizer, CLIPImageProcessorPil, CompactDecoder, COUNTERS, FEATURES,
    FeedForward, GIB, IMAGE_TOKENS, Image, LlavaForConditionalGeneration, LlavaProcessor, REFERENCE,
    ROOT, check_memory, load_official_sources, read, score_cases, sha256, torch,
)
import tri_oracle_integer_reference as integer_reference

MODES = ("dense_integer", "wide_later_gated_product")


def wider_evaluator():
    """Build an exact copy of the reference with a single wider saturation bound."""
    original = textwrap.dedent(inspect.getsource(integer_reference.IntegerFeedForwardReference.evaluate))
    narrow = "gated=_requantize(products,torch.full_like(down_shift,8),16)"
    assert original.count(narrow) == 1
    # products [token rows, intermediate channels] uses two signed 16-bit factors.
    # After the eight-bit right shift, even a product of 2**30 fits signed 24 bits.
    widened = original.replace(narrow, narrow[:-3] + "24)")
    widened = widened.replace('    return raw,values,stats',
        '    stats["formerly_clipped"] = ((gated < -32768) | (gated > 32767)).sum(dim=-1,dtype=torch.int32)\n'
        '    return raw,values,stats')
    assert widened.count('stats["formerly_clipped"]') == 1
    scope = vars(integer_reference).copy()
    exec(compile(widened, inspect.getsourcefile(integer_reference), "exec"), scope)
    return scope["evaluate"]


def install_evaluator(layer, index, context, wider):
    original = layer.reference.evaluate

    def evaluate(activation, residual, **format_options):
        # The normalized activation and pre-scale residual are both [token rows, 2048 input features].
        # evaluate_protected calls this once for the original first row, then dispatches the remaining rows.
        first = layer.decoder.prefill_active and context["calls"][index] == 0
        context["calls"][index] += 1
        if first:
            assert activation.shape[0] == 1 and int(layer.decoder.positions[0]) == 0
        if first or context["mode"] == "dense_integer":
            return original(activation, residual, **format_options)
        # The widened evaluator returns [token rows, output features] and the same row-ordered metadata.
        raw, values, stats = wider(layer.reference, activation, residual, **format_options)
        context["rows"][index] += activation.shape[0]
        context["formerly_clipped"] += int(stats.pop("formerly_clipped").sum())
        return raw, values, stats

    layer.reference.evaluate = evaluate


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
    position_path = REFERENCE / "ff_position_holdout/verified.json"
    position = read(position_path)
    assert position["state"] == "feedforward_position_counterfactuals_independently_scored"
    assert position["scores_percent"]["dense_integer"] == dense["score"]["official_vqa_consensus_percent"]
    manifest = REFERENCE / "grouped_precision_holdout/manifest.json"
    samples = read(manifest)["samples"]
    assert len(samples) == len(dense["cases"]) == 256 and len({sample["image_id"] for sample in samples}) == 256
    pilot_path = ROOT / "records/batch424_joint_pilot_result.json"
    pilot = read(pilot_path)
    assert dense["checkpoint_revision"] == pilot["checkpoint_revision"]
    first_path, ordinary_path = (REFERENCE / f"{name}/layer_policy.json" for name in ("format322", "format335"))
    evaluator, normalizer, scorer = load_official_sources(ROOT)
    pins = dense["source_sha256"].copy()
    evidence = scorer | {str(ROOT / path): digest for path, digest in position["evidence_sha256"].items()}
    evidence.update({str(path): sha256(path) for path in (Path(__file__), Path(integer_reference.__file__),
                     dense_path, position_path, manifest, pilot_path, first_path, ordinary_path)})
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
    wider = wider_evaluator()
    for index, replacement in enumerate(replacements):
        install_evaluator(replacement, index, context, wider)
    answers = {mode: [] for mode in MODES}
    ALL_ATTENTION_FUNCTIONS["sdpa"] = decoder.attend
    try:
        for index, sample in enumerate(samples):
            check_memory(13.5 * GIB)
            with Image.open(ROOT / sample["image"]) as opened:
                image = opened.convert("RGB")
            prompt = "USER: <image>\n" + sample["question"] + "\nAnswer the question using a single word or phrase.\nASSISTANT:"
            # Checkpoint processor outputs the single prompt and image batch on the graphics processor.
            batch = processor(images=image, text=prompt, return_tensors="pt").to("cuda")
            # ids [1, prompt tokens] includes the image placeholders.
            ids = batch["input_ids"]
            positions = (ids[0] == model.config.image_token_id).nonzero().flatten().tolist()
            assert ids.shape[0] == 1 and bool(batch["attention_mask"].all())
            assert positions and positions[0] > 0 and positions == list(range(positions[0], positions[0] + IMAGE_TOKENS))
            # embeddings [1, prompt tokens, features] is the text lookup with the projected vision rows inserted.
            embeddings = model.model.get_input_embeddings()(ids)
            # image_states [image tokens, features] is the projected vision encoder output.
            image_states = torch.cat(model.model.get_image_features(batch["pixel_values"], return_dict=True).pooler_output, dim=0)
            assert image_states.shape == (IMAGE_TOKENS, FEATURES)
            image_states = image_states.to(embeddings.device, embeddings.dtype)
            embeddings = embeddings.masked_scatter(model.model.get_placeholder_mask(ids, embeddings, image_states), image_states)
            for mode in MODES:
                context.update(mode=mode, calls=[0] * 22, rows=[0] * 22, formerly_clipped=0)
                for replacement in replacements:
                    replacement.begin(True, False)
                tokens = decoder.generate(embeddings, positions[0], "compact_and_streaming", {2}, None)
                offsets = [0] + list(range(ids.shape[1], ids.shape[1] + len(tokens) - 1))
                for layer, replacement in enumerate(replacements):
                    assert replacement.positions == offsets and replacement.residual is None
                    assert replacement.prefill_rows == decoder.layer_slots[layer] and replacement.decode_rows == len(tokens) - 1
                    assert replacement.prefill_skipped == replacement.decode_skipped == 0
                    expected = 0 if mode == "dense_integer" else replacement.prefill_rows + replacement.decode_rows - 1
                    assert context["rows"][layer] == expected
                counts = {key: sum(getattr(item, key) for item in replacements) for key in COUNTERS}
                case = dict(question_id=sample["question_id"], image_id=sample["image_id"], answer_tokens=tokens,
                    answer=tokenizer.decode(tokens, skip_special_tokens=True), prefill_tokens=ids.shape[1],
                    prefill_slots=sum(decoder.layer_slots), prefill_pairs=decoder.pairs,
                    streaming_heads=decoder.streaming_count, final_image_roots=decoder.layer_roots[-1]) | counts
                if mode == "dense_integer":
                    assert case == dense["cases"][index], (index, sample["question_id"])
                answers[mode].append(case | {"wide_gated_rows": sum(context["rows"]), "formerly_clipped": context["formerly_clipped"]})
            print("FF_GATED_CLIP_CASE", index + 1, sample["question_id"], flush=True)
    finally:
        ALL_ATTENTION_FUNCTIONS["sdpa"] = original
        for replacement in replacements:
            replacement.close()

    scores = {mode: score_cases(samples, cases, evaluator, normalizer) for mode, cases in answers.items()}
    for score in scores.values():
        score["official_vqa_consensus_percent"] = score.pop("official_vqa_consensus_percent_on64")
    assert scores["dense_integer"] == dense["score"]
    assert all(sha256(Path(name)) == digest for name, digest in pins.items())
    result = dict(state="feedforward_gated_clip_counterfactual_scored", questions=len(samples), decoder_layers=len(replacements),
        reproduced_dense_integer_cases=len(answers["dense_integer"]), scores=scores, answers=answers,
        source_sha256=pins, wall_seconds=time.monotonic() - started, peak_graphics_bytes=torch.cuda.max_memory_allocated(),
        scope="Software diagnostic changing only the intermediate product saturation bound for later rows.")
    with (output / "receipt.json").open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print("FF_GATED_CLIP_SCORED", {mode: score["official_vqa_consensus_percent"] for mode, score in scores.items()}, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    run(parser.parse_args().output.resolve())
