"""Export trained compact query/key/value operands for native attention-row verification."""

from collections import Counter
import gzip
import json
import math
from pathlib import Path

from prepare_tri_oracle_batch425_softmax import (
    ALL_ATTENTION_FUNCTIONS, AutoTokenizer, CLIPImageProcessorPil, HEADS, IMAGE_TOKENS,
    Image, KEY_HEADS, LlavaForConditionalGeneration, LlavaProcessor, ROOT, SoftmaxTrace,
    GIB, _quantize, check_memory, np, sha256, torch,
)
from run_tri_oracle_batch425_softmax import FULL_SCALE, fixed_probabilities, real_probabilities


def hex_bytes(vector):
    """Pack the feature-zero byte at the least significant end of a native vector."""
    return vector.tobytes()[::-1].hex()


class OperandTrace(SoftmaxTrace):
    def __init__(self, model, attention, ratio, maps):
        super().__init__(model, attention, ratio, maps)
        self.cases = []

    def attend(self, module, query, key, value, attention_mask, **kwargs):
        """Observe trained Q [1, query head, query, feature] and K/V [1, key head, key, feature]."""
        start = len(self.rows)
        output = super().attend(module, query, key, value, attention_mask, **kwargs)
        if start == len(self.rows):
            return output
        queries = self.positions.tolist()
        query_codes = {}
        operands = {}
        for row in self.rows[start:]:
            head = row["head"]
            group = head // (HEADS // KEY_HEADS)
            if head not in query_codes:
                # Q codes [retained query, feature] with a single exponent.
                codes, exponent = _quantize(query[0, head])
                query_codes[head] = codes.cpu().numpy(), int(exponent)
            if group not in operands:
                # K and V codes [retained key, feature], each using a group exponent.
                k_codes, k_exp = _quantize(key[0, group])
                v_codes, v_exp = _quantize(value[0, group])
                operands[group] = (k_codes.cpu().numpy(), int(k_exp), v_codes.cpu().numpy(), int(v_exp))
            q_codes, q_exp = query_codes[head]
            k_codes, k_exp, v_codes, v_exp = operands[group]
            q_row = q_codes[queries.index(row["query_position"])]
            shift = q_exp + k_exp + 5
            assert kwargs["scaling"] == 0.125 and -31 <= shift <= 31
            # Independent signed dot products [retained key] from the captured operand codes.
            dots = (k_codes.astype(np.int32) @ q_row.astype(np.int32)).tolist()
            scores = [round(math.ldexp(dot, shift)) for dot in dots]
            assert scores == row["scores"]
            selected = [rank for rank, size in enumerate(row["sizes"]) if size]
            probabilities = fixed_probabilities(scores, row["sizes"])
            unit_sizes = fixed_probabilities(scores, [int(size != 0) for size in row["sizes"]])
            reference = real_probabilities(scores, row["sizes"])
            # Value output [feature], in integer probability-code units and real value-code units.
            v64 = v_codes.astype(np.int64)
            result = np.asarray(probabilities, dtype=np.int64) @ v64
            wrong = np.asarray(unit_sizes, dtype=np.int64) @ v64
            ideal = np.asarray(reference, dtype=np.float64) @ v64
            self.cases.append(dict(image_start=self.image_start, query_hex=hex_bytes(q_row),
                keys_hex=[hex_bytes(vector) for vector in k_codes], values_hex=[hex_bytes(vector) for vector in v_codes],
                value_exponent=v_exp, shift=shift, selected=selected, dots=[dots[rank] for rank in selected],
                result=result.tolist(), unit_size_result=wrong.tolist(),
                max_absolute_value_code_error=float(np.max(np.abs(result / FULL_SCALE - ideal)))))
        return output


@torch.inference_mode()
def main():
    check_memory(15*GIB)
    assert torch.cuda.mem_get_info()[0] > 12*GIB
    torch.cuda.set_per_process_memory_fraction(0.84)
    torch.set_num_threads(3)
    torch.set_num_interop_threads(1)
    torch.manual_seed(0)

    compact_path = ROOT / "records/batch422_compact_decoder_result.json"
    norm_path = ROOT / "records/batch425_proportional_softmax_result.json"
    norm_archive = ROOT / "records/batch425_proportional_softmax_evidence.json.gz"
    compact = json.loads(compact_path.read_text())
    norm = json.loads(norm_path.read_text())
    assert sha256(norm_archive) == norm["native_evidence_sha256"]
    frozen = json.loads(json.loads(gzip.decompress(norm_archive.read_bytes()))["trained_trace"])
    hashes = frozen["source_sha256"].copy()
    for path in (compact_path, norm_path, norm_archive, Path(__file__), ROOT/"syn/run_tri_oracle_batch425_softmax.py"):
        hashes[str(path)] = sha256(path)
    mode = "compact_and_streaming"
    map_path = Path(compact["native_fixture"]) / f"map_{compact['native_fixture_modes'].index(mode)}.hex"
    assert hashes[str(map_path)] == compact["native_fixture_sha256"][str(map_path)]
    assert all(sha256(Path(path)) == digest for path,digest in hashes.items())
    positions_map = [int(line, 16) for line in map_path.read_text().splitlines()]
    maps = [positions_map[start:start+IMAGE_TOKENS] for start in range(0, len(positions_map), IMAGE_TOKENS)]
    directory = ROOT / ".cache/model_reference/batch426"
    assert not directory.exists()
    manifest = ROOT / ".cache/model_reference/vqav2_pilot/manifest.json"
    sample = json.loads(manifest.read_text())["samples"][0]
    assert sample["question_id"] == frozen["question"]
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
    # Prompt IDs [1, token], normalized image [1, channel, height, width].
    ids = batch["input_ids"]
    positions = (ids[0] == model.config.image_token_id).nonzero().flatten().tolist()
    assert positions == list(range(positions[0], positions[0]+IMAGE_TOKENS))
    # Embeddings [1, prompt token, feature], projected image states [image token, feature].
    embeddings = model.model.get_input_embeddings()(ids)
    image_states = torch.cat(model.model.get_image_features(batch["pixel_values"], return_dict=True).pooler_output, dim=0)
    embeddings = embeddings.masked_scatter(model.model.get_placeholder_mask(ids, embeddings, image_states),
                                            image_states.to(embeddings.device, embeddings.dtype))
    original = ALL_ATTENTION_FUNCTIONS["sdpa"]
    decoder = OperandTrace(model, original, tuple(compact["local_ratio"]), maps)
    ALL_ATTENTION_FUNCTIONS["sdpa"] = decoder.attend
    try:
        answer = decoder.generate(embeddings, positions[0], mode, {2}, None)
    finally:
        ALL_ATTENTION_FUNCTIONS["sdpa"] = original
    assert answer == frozen["answer"] and decoder.rows == frozen["rows"]
    cases = [row | case for row, case in zip(decoder.rows, decoder.cases, strict=True)]
    assert len(cases) == norm["trained_rows"]
    assert max(case["max_absolute_value_code_error"] for case in cases) < 0.125
    assert all(sha256(Path(path)) == digest for path,digest in hashes.items())
    directory.mkdir()
    report = dict(question=sample["question_id"], cases=cases, maps=maps, source_sha256=hashes)
    (directory/"operands.json").write_text(json.dumps(report,separators=(",",":"))+"\n")
    print("BATCH426_OPERANDS", Counter(case["layer"] for case in cases),
          "selected", sum(len(case["selected"]) for case in cases))


if __name__ == "__main__":
    main()
