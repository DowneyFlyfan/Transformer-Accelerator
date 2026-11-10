"""Capture compact prompt operands and independent head-prediction totals."""

import json
import math
from pathlib import Path

from prepare_tri_oracle_batch426_attention import OperandTrace, hex_bytes
from prepare_tri_oracle_batch425_softmax import (
    ALL_ATTENTION_FUNCTIONS, AutoTokenizer, CLIPImageProcessorPil, HEADS, IMAGE_TOKENS,
    Image, KEY_HEADS, LlavaForConditionalGeneration, LlavaProcessor, ROOT,
    GIB, _quantize, check_memory, np, sha256, torch,
)
from prepare_tri_oracle_batch409_attention_fixture import ALPHA


class HeadTrace(OperandTrace):
    def __init__(self, model, attention, ratio, maps):
        super().__init__(model, attention, ratio, maps)
        self.heads = []

    def attend(self, module, query, key, value, attention_mask, **kwargs):
        """Capture prompt Q [1, head, query, feature] and K [1, key head, key, feature]."""
        start = len(self.rows)
        output = super().attend(module, query, key, value, attention_mask, **kwargs)
        if not self.prefill_active or start == len(self.rows):
            return output
        heads = sorted({row["head"] for row in self.rows[start:]})
        count = query.shape[2]
        assert count == key.shape[2] and count > 96 and kwargs["scaling"] == 0.125
        for head in heads:
            group = head // (HEADS // KEY_HEADS)
            # Signed codes [prompt row, feature], with one scalar exponent per head.
            q, qe = _quantize(query[0,head])
            k, ke = _quantize(key[0,group])
            q_codes, k_codes = q.cpu().numpy(), k.cpu().numpy()
            scale = math.ldexp(kwargs["scaling"], int(qe)+int(ke))
            alpha = int(ALPHA / scale)
            assert alpha * scale == ALPHA
            # Scalar integer tile reductions consume [prompt row, compact key].
            dots = q_codes.astype(np.int32) @ k_codes.astype(np.int32).T
            inner = recent = 0
            for row in range(96, count):
                tile = row // 32 * 32
                scores = dots[row]
                cutoff = int(max(scores[:32])) - alpha
                inner += int(np.count_nonzero(scores[tile-64:tile-32] > cutoff))
                recent += int(np.count_nonzero(scores[tile:row+1] > cutoff))
            streaming = recent*self.ratio[1] > inner*self.ratio[0]
            assert streaming == bool(self.streaming[self.layer_index][head])
            self.heads.append(dict(layer=self.layer_index, head=head, alpha=alpha, inner=inner, recent=recent,
                                   streaming=streaming, queries=[hex_bytes(vector) for vector in q_codes[96:]],
                                   keys=[hex_bytes(vector) for vector in k_codes]))
        return output


@torch.inference_mode()
def main():
    check_memory(15*GIB)
    assert torch.cuda.mem_get_info()[0] > 12*GIB
    torch.cuda.set_per_process_memory_fraction(0.84)
    torch.set_num_threads(3)
    torch.set_num_interop_threads(1)
    torch.manual_seed(0)
    operand_path = ROOT / ".cache/model_reference/batch426/operands.json"
    result_path = ROOT / "records/batch426_attention_row_result.json"
    compact_path = ROOT / "records/batch422_compact_decoder_result.json"
    operands, result, compact = [json.loads(path.read_text()) for path in (operand_path, result_path, compact_path)]
    assert sha256(operand_path) == result["inputs_sha256"][str(operand_path)]
    hashes = operands["source_sha256"].copy()
    for path in (Path(__file__), operand_path, result_path, compact_path, ROOT/"syn/prepare_tri_oracle_batch426_attention.py"):
        hashes[str(path)] = sha256(path)
    assert all(sha256(Path(path)) == digest for path,digest in hashes.items())
    directory = ROOT / ".cache/model_reference/batch427"
    assert not directory.exists()
    manifest = ROOT / ".cache/model_reference/vqav2_pilot/manifest.json"
    sample = json.loads(manifest.read_text())["samples"][0]
    assert sample["question_id"] == operands["question"]
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
    # Prompt IDs [1, token] and input image [1, channel, height, width].
    ids = batch["input_ids"]
    image_positions = (ids[0] == model.config.image_token_id).nonzero().flatten().tolist()
    assert image_positions == list(range(image_positions[0], image_positions[0]+IMAGE_TOKENS))
    # Embedded prompt [1, prompt token, feature] with projected image [image token, feature].
    embeddings = model.model.get_input_embeddings()(ids)
    image_states = torch.cat(model.model.get_image_features(batch["pixel_values"], return_dict=True).pooler_output, dim=0)
    embeddings = embeddings.masked_scatter(model.model.get_placeholder_mask(ids, embeddings, image_states),
                                            image_states.to(embeddings.device, embeddings.dtype))
    original = ALL_ATTENTION_FUNCTIONS["sdpa"]
    tracer = HeadTrace(model, original, tuple(compact["local_ratio"]), operands["maps"])
    ALL_ATTENTION_FUNCTIONS["sdpa"] = tracer.attend
    try:
        answer = tracer.generate(embeddings, image_positions[0], "compact_and_streaming", {2}, None)
    finally:
        ALL_ATTENTION_FUNCTIONS["sdpa"] = original
    assert answer == compact["cases"]["compact_and_streaming"][0]["answer_tokens"]
    assert [row | case for row,case in zip(tracer.rows,tracer.cases,strict=True)] == operands["cases"]
    assert {(head["layer"],head["head"]) for head in tracer.heads} == {
        (case["layer"],case["head"]) for case in operands["cases"]}
    assert all(sha256(Path(path)) == digest for path,digest in hashes.items())
    directory.mkdir()
    (directory/"heads.json").write_text(json.dumps(dict(question=sample["question_id"], heads=tracer.heads,
                                                        source_sha256=hashes),separators=(",",":"))+"\n")
    print("BATCH427_HEADS", [(head["layer"],head["head"],head["streaming"]) for head in tracer.heads])


if __name__ == "__main__":
    main()
