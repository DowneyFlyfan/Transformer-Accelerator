"""Capture compact trained attention rows and independent causal multiplicities."""

from bisect import bisect_right
from collections import Counter
import json
import math
from pathlib import Path

from transformers.models.llama.modeling_llama import ALL_ATTENTION_FUNCTIONS

from evaluate_tri_oracle_batch417_sparse_answers import RECENT_TOKENS, SINK_TOKENS
from evaluate_tri_oracle_batch421_merge_aware_attention import IMAGE_TOKENS, causal_bias
from evaluate_tri_oracle_batch422_compact_decoder import CompactDecoder
from run_tri_oracle_batch396_masks import GIB, check_memory, sha256
from tri_oracle_integer_reference import _dot, _quantize
from verify_tri_oracle_batch414_head_policy import (
    HEADS, KEY_HEADS, ROOT, AutoTokenizer, CLIPImageProcessorPil, Image,
    LlavaForConditionalGeneration, LlavaProcessor, np, torch,
)


class SoftmaxTrace(CompactDecoder):
    def __init__(self, model, attention, ratio, maps):
        super().__init__(model, attention, ratio)
        self.maps = maps
        self.rows = []

    def attend(self, module, query, key, value, attention_mask, **kwargs):
        """Capture Q [1, query head, retained query, feature] and K/V [1, key head, retained key, feature]."""
        output = super().attend(module, query, key, value, attention_mask, **kwargs)
        if id(module) not in self.layer_ids or self.layer_index not in (0, 10, 21):
            return output
        if not self.prefill_active and self.decode_steps != 0:
            return output
        query_positions = self.positions.tolist()
        key_positions = self.key_positions.tolist()
        origins = self.maps[self.layer_index]
        frame = self.frames[self.layer_index]
        assert frame.origins.tolist() == origins
        flags = self.streaming[self.layer_index].tolist()
        heads = sorted({flags.index(flag) for flag in (False, True) if flag in flags})
        indices = (sorted({0, self.image_start, len(query_positions)//2, len(query_positions)-1})
                   if self.prefill_active else [0])
        # Bias [retained query, retained key] comes from the existing compact attention path.
        bias = causal_bias(frame, self.image_start, self.positions, self.key_positions)
        for head in heads:
            group = head // (HEADS // KEY_HEADS)
            # Signed integer codes [retained query/key, feature], one exponent per head.
            qcodes, qe = _quantize(query[0, head])
            kcodes, ke = _quantize(key[0, group])
            padded = torch.nn.functional.pad(kcodes, (0, 0, 0, (-len(key_positions)) % 16))
            # Dot products [selected query, retained key] before scale and causal bias.
            selected = qcodes[indices]
            sums = _dot(selected, padded)[:, :len(key_positions)].cpu().numpy()
            cpu_sums = selected.cpu().numpy().astype(np.int32) @ kcodes.cpu().numpy().astype(np.int32).T
            np.testing.assert_array_equal(sums, cpu_sums)
            scale = math.ldexp(kwargs["scaling"], int(qe) + int(ke))
            for index, dot_products in zip(indices, sums.tolist(), strict=True):
                position = query_positions[index]
                prefix = max(0, position-self.image_start+1)
                visible = bisect_right(key_positions, position)
                group_sizes = Counter(origins[:prefix])
                sizes = []
                for rank, key_position in enumerate(key_positions):
                    if rank >= visible or (flags[head] and SINK_TOKENS <= rank < visible-RECENT_TOKENS):
                        sizes.append(0)
                    elif self.image_start <= key_position < self.image_start+IMAGE_TOKENS:
                        sizes.append(group_sizes[key_position-self.image_start])
                    else:
                        sizes.append(1)
                # Log-bias exp gives [retained key] causal sizes before streaming masking.
                causal_sizes = bias[index].exp().round().to(torch.int32).tolist()
                assert sizes == [size if not flags[head] or rank < SINK_TOKENS or rank >= visible-RECENT_TOKENS else 0
                                 for rank, size in enumerate(causal_sizes)]
                scores = [round(score * scale * 256) for score in dot_products]
                assert max(sizes) > 0 and all(-32768 <= score < 32768 for score in scores)
                self.rows.append(dict(layer=self.layer_index, head=head, streaming=flags[head],
                                      prefill=self.prefill_active, query_position=position,
                                      scores=scores, sizes=sizes))
        return output


@torch.inference_mode()
def main():
    check_memory(15*GIB)
    assert torch.cuda.mem_get_info()[0] > 12*GIB
    torch.cuda.set_per_process_memory_fraction(0.84)
    torch.set_num_threads(3)
    torch.set_num_interop_threads(1)
    torch.manual_seed(0)

    receipt = ROOT / "records/batch422_compact_decoder_result.json"
    prior = json.loads(receipt.read_text())
    assert prior["state"] == "cumulative_compact_decoder_pilot_scored"
    hashes = prior["source_sha256"].copy()
    mode = "compact_and_streaming"
    mode_index = prior["native_fixture_modes"].index(mode)
    map_path = Path(prior["native_fixture"]) / f"map_{mode_index}.hex"
    assert sha256(map_path) == prior["native_fixture_sha256"][str(map_path)]
    for path in (receipt, map_path, Path(__file__)):
        hashes[str(path)] = sha256(path)
    assert all(sha256(Path(path)) == digest for path, digest in hashes.items())
    mapping = [int(line, 16) for line in map_path.read_text().splitlines()]
    assert len(mapping) == 22 * IMAGE_TOKENS
    maps = [mapping[start:start+IMAGE_TOKENS] for start in range(0, len(mapping), IMAGE_TOKENS)]
    directory = ROOT / ".cache/model_reference/batch425"
    assert not directory.exists()
    manifest = ROOT / ".cache/model_reference/vqav2_pilot/manifest.json"
    sample = json.loads(manifest.read_text())["samples"][0]
    archive = prior["cases"][mode][0]
    assert sample["question_id"] == archive["question_id"]
    model_dir = ROOT / ".cache/model_reference/tiny_llava_v1"
    tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
    processor = LlavaProcessor(image_processor=CLIPImageProcessorPil.from_pretrained(model_dir, local_files_only=True),
                              tokenizer=tokenizer, patch_size=14, vision_feature_select_strategy="default",
                              num_additional_image_tokens=1)
    model = LlavaForConditionalGeneration.from_pretrained(model_dir, local_files_only=True, dtype=torch.float32,
                        attn_implementation="sdpa", use_kernels=False).to("cuda").eval()
    with Image.open(ROOT / sample["image"]) as opened:
        image = opened.convert("RGB")
    prompt = "USER: <image>\n" + sample["question"] + "\nAnswer the question using a single word or phrase.\nASSISTANT:"
    batch = processor(images=image, text=prompt, return_tensors="pt").to("cuda")
    # Text token IDs [1, prompt token], image tensor [1, channel, height, width].
    ids = batch["input_ids"]
    positions = (ids[0] == model.config.image_token_id).nonzero().flatten().tolist()
    assert positions == list(range(positions[0], positions[0]+IMAGE_TOKENS))
    # Embeddings [1, prompt token, feature], projected vision states [image token, feature].
    embeddings = model.model.get_input_embeddings()(ids)
    image_states = torch.cat(model.model.get_image_features(batch["pixel_values"], return_dict=True).pooler_output, dim=0)
    image_states = image_states.to(embeddings.device, embeddings.dtype)
    embeddings = embeddings.masked_scatter(model.model.get_placeholder_mask(ids, embeddings, image_states), image_states)
    original = ALL_ATTENTION_FUNCTIONS["sdpa"]
    decoder = SoftmaxTrace(model, original, tuple(prior["local_ratio"]), maps)
    ALL_ATTENTION_FUNCTIONS["sdpa"] = decoder.attend
    try:
        answer = decoder.generate(embeddings, positions[0], mode, {2}, None)
    finally:
        ALL_ATTENTION_FUNCTIONS["sdpa"] = original
    assert answer == archive["answer_tokens"] and decoder.layer_slots == archive["layer_cache_slots"]
    assert decoder.pairs == archive["prefill_kept_pairs"]
    rows = decoder.rows
    assert {row["layer"] for row in rows} == {0, 10, 21}
    assert {row["prefill"] for row in rows} == {True, False} and {row["streaming"] for row in rows} == {True, False}
    assert any(max(row["sizes"]) > 1 and 0 in row["sizes"] for row in rows)
    assert all(sha256(Path(path)) == digest for path, digest in hashes.items())
    directory.mkdir()
    (directory / "rows.json").write_text(json.dumps(dict(question=sample["question_id"], answer=answer, rows=rows,
                                                       source_sha256=hashes), separators=(",", ":")) + "\n")
    print(f"BATCH425_TRACE question={sample['question_id']} rows={len(rows)} keys={sum(len(row['scores']) for row in rows)}")


if __name__ == "__main__":
    main()
