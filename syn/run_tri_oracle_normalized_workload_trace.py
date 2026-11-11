"""Count local algorithmic work on the pinned 600-prefill, 60-decode workload."""

import argparse
import json
from pathlib import Path

from evaluate_tri_oracle_batch422_compact_decoder import HEADS, RECENT_TOKENS, SINK_TOKENS
from evaluate_tri_oracle_channel_scaled_down import (
    ALL_ATTENTION_FUNCTIONS, AutoTokenizer, CLIPImageProcessorPil, CompactDecoder, COUNTERS, FEATURES,
    FeedForward, GIB, IMAGE_TOKENS, Image, LlavaForConditionalGeneration, LlavaProcessor, REFERENCE,
    ROOT, check_memory, install_channel_scaling, read, sha256, torch,
)

PREFILL, DECODE, CHANNELS = 600, 60, 5632
MODES = {"identity_dense": ("identity", False), "compact_streaming_dense": ("compact_and_streaming", False),
         "compact_streaming_pruned": ("compact_and_streaming", True)}


class CountedDecoder(CompactDecoder):
    def attend(self, module, query, key, value, attention_mask, **kwargs):
        """Count allowed pairs for query [1, head, token, feature] and compact keys."""
        previous = self.pairs if id(module) in self.layer_ids else 0
        output = super().attend(module, query, key, value, attention_mask, **kwargs)
        if id(module) not in self.layer_ids:
            return output
        index = self.layer_index
        if self.prefill_active:
            self.prefill_pairs[index] += self.pairs - previous
        else:
            assert self.positions.numel() == 1 and self.positions[0] == self.key_positions[-1]
            keys = self.key_positions.numel()
            streaming_heads = int(self.streaming[index].sum()) if self.mode == "compact_and_streaming" else 0
            # A single final-position query can see all causal keys. Streaming
            # heads see the union of the fixed sink and recent key ranges.
            visible_stream = min(keys, SINK_TOKENS + RECENT_TOKENS)
            self.decode_pairs[index] += (HEADS - streaming_heads) * keys + streaming_heads * visible_stream
        return output


@torch.inference_mode()
def run(output):
    torch.set_num_threads(3)
    torch.set_num_interop_threads(1)
    torch.manual_seed(0)
    check_memory(16 * GIB)
    assert torch.cuda.mem_get_info()[0] > 12 * GIB
    torch.cuda.set_per_process_memory_fraction(0.78)
    torch.cuda.reset_peak_memory_stats()
    records = ROOT / "records"
    original_path = records / "all_layer_integer_model_validation.json"
    original_proof = records / "all_layer_integer_model_qualification.json"
    assert read(original_proof)["report_sha256"][str(original_path.relative_to(ROOT))] == sha256(original_path)
    original = read(original_path)
    assert original["state"] == "completed" and (original["prefill_tokens"], original["decode_tokens"]) == (PREFILL, DECODE)
    token_trace = original["baseline_tokens"]
    assert len(token_trace) == DECODE and all(type(token) is int for token in token_trace)
    calibrated_path = REFERENCE / "ff_channel_scaled_pruned/receipt.json"
    calibrated = read(calibrated_path)
    assert calibrated["state"] == "scaled_down_and_pruned_local_benchmark_scored"
    assert calibrated["checkpoint_revision"] == original["checkpoint_revision"]
    pins = calibrated["source_sha256"].copy()
    demo = ROOT / ".cache/model_reference/ai2d-demo.jpg"
    assert original["input_sha256"][str(demo.relative_to(ROOT))] == sha256(demo)
    for path in (Path(__file__), original_path, original_proof, calibrated_path, demo):
        digest = sha256(path)
        assert pins.get(str(path), digest) == digest
        pins[str(path)] = digest
    assert all(sha256(Path(name)) == digest for name, digest in pins.items())

    model_dir = REFERENCE / "tiny_llava_v1"
    tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
    processor = LlavaProcessor(image_processor=CLIPImageProcessorPil.from_pretrained(model_dir, local_files_only=True),
        tokenizer=tokenizer, patch_size=14, vision_feature_select_strategy="default", num_additional_image_tokens=1)
    model = LlavaForConditionalGeneration.from_pretrained(model_dir, local_files_only=True, dtype=torch.float32,
        attn_implementation="sdpa", use_kernels=False, device_map={"": "cuda:0"}).eval()
    with Image.open(demo) as opened:
        batch = processor(images=opened.convert("RGB"), text=original["prompt"], return_tensors="pt").to("cuda")
    ids = batch["input_ids"]  # [1, prefill tokens]
    positions = (ids[0] == model.config.image_token_id).nonzero().flatten().tolist()
    assert ids.shape == (1, PREFILL) and bool(batch["attention_mask"].all())
    assert len(positions) == IMAGE_TOKENS and positions == list(range(positions[0], positions[0] + IMAGE_TOKENS))
    embeddings = model.model.get_input_embeddings()(ids)  # [1, prefill tokens, hidden features]
    # Projected image tokens [image tokens, hidden features] fill the image placeholder span.
    image = torch.cat(model.model.get_image_features(batch["pixel_values"], return_dict=True).pooler_output, dim=0)
    assert image.shape == (IMAGE_TOKENS, FEATURES)
    image = image.to(embeddings.device, embeddings.dtype)
    embeddings = embeddings.masked_scatter(model.model.get_placeholder_mask(ids, embeddings, image), image)
    tokens = torch.tensor(token_trace, device="cuda")  # [decode steps], fixed from the archived baseline.

    original_attention = ALL_ATTENTION_FUNCTIONS["sdpa"]
    pilot = read(records / "batch424_joint_pilot_result.json")
    decoder = CountedDecoder(model, original_attention, tuple(pilot["local_ratio"]))
    first, ordinary = (read(REFERENCE / f"{name}/layer_policy.json")["layers"] for name in ("format322", "format335"))
    replacements = [FeedForward(layer, decoder, zero, regular)
                    for layer, zero, regular in zip(decoder.language.layers, first, ordinary, strict=True)]
    assert len(replacements) == 22
    context = {}
    for index, (replacement, layer) in enumerate(zip(replacements, decoder.language.layers, strict=True)):
        install_channel_scaling(replacement, index, layer.mlp.down_proj.weight, context)
    ALL_ATTENTION_FUNCTIONS["sdpa"] = decoder.attend
    cases = {}
    try:
        for mode, (attention, prune) in MODES.items():
            context.update(mode=mode, calls=[0] * 22, scaled_rows=[0] * 22)
            decoder.prefill_pairs, decoder.decode_pairs = [0] * 22, [0] * 22
            for replacement in replacements:
                replacement.begin(True, prune)
            assert bool(torch.isfinite(decoder.prefill(embeddings, positions[0], attention, PREFILL)).all())
            for token in tokens:
                check_memory(15.5 * GIB)
                assert bool(torch.isfinite(decoder.decode(token)).all())
            assert decoder.decode_steps == DECODE and sum(decoder.prefill_pairs) == decoder.pairs
            layers = []
            for index, replacement in enumerate(replacements):
                assert replacement.positions == [0, *range(PREFILL, PREFILL + DECODE)] and replacement.residual is None
                assert replacement.prefill_rows == decoder.layer_slots[index] and replacement.decode_rows == DECODE
                assert context["scaled_rows"][index] == replacement.prefill_rows + replacement.decode_rows - 1
                assert replacement.prefill_skipped == (replacement.prefill_predicted if prune else 0)
                assert replacement.decode_skipped == (replacement.decode_predicted if prune else 0)
                heads = int(decoder.streaming[index].sum()) if attention != "identity" else 0
                layers.append(dict(layer=index, image_roots=decoder.layer_roots[index], streaming_heads=heads,
                    prefill_pairs=decoder.prefill_pairs[index], decode_pairs=decoder.decode_pairs[index],
                    **{key: getattr(replacement, key) for key in COUNTERS}))
            cases[mode] = layers
            print("NORMALIZED_WORKLOAD_CASE", mode, sum(decoder.prefill_pairs), sum(decoder.decode_pairs), flush=True)
    finally:
        ALL_ATTENTION_FUNCTIONS["sdpa"] = original_attention
        for replacement in replacements:
            replacement.close()
    assert all(sha256(Path(name)) == digest for name, digest in pins.items())
    result = dict(state="normalized_workload_logical_trace_counted", checkpoint_revision=original["checkpoint_revision"],
                  prefill_tokens=PREFILL, decode_steps=DECODE, forced_tokens=token_trace, channels=CHANNELS,
                  layers=cases, graphics_peak_bytes=torch.cuda.max_memory_allocated(), input_sha256=pins,
                  scope="One archived input and fixed continuation. Counts are logical model work opportunities.")
    with (output / "receipt.json").open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    run(parser.parse_args().output.resolve())
