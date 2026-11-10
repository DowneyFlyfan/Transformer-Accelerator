"""Measure answer changes from the local streaming-head attention reconstruction."""

import gzip
import hashlib
import inspect
import json
from pathlib import Path

from verify_tri_oracle_batch414_head_policy import (
    HEADS, KEY_HEADS, ROOT, TILE, WIDTH, AutoTokenizer, CLIPImageProcessorPil, Image,
    LlavaForConditionalGeneration, LlavaProcessor, causal_geometry, classify_layer, torch,
)
from transformers.models.llama.modeling_llama import ALL_ATTENTION_FUNCTIONS, LlamaAttention

from run_tri_oracle_batch396_masks import GIB, check_memory, sha256
from score_tri_oracle_format326_vqav2 import load_official_sources, score_cases


SINK_TOKENS = 32
RECENT_TOKENS = 32
MODES = ("dense", "explicit_dense_mask", "frozen_streaming", "live_streaming")


def streaming_mask(query_positions, key_positions, streaming):
    """Absolute positions [query] and [key] and Boolean selection [head].

    Returns a Boolean mask [1, head, query, key], true for kept keys.
    Both streaming windows are fixed local choices. Retrieval heads remain causal.
    """
    query = query_positions[:, None]
    key = key_positions[None, :]
    causal = key <= query
    window = (key < SINK_TOKENS) | (key > query - RECENT_TOKENS)
    return (causal[None, :, :] & (~streaming[:, None, None] | window[None, :, :]))[None]


def verify_mask():
    mask = streaming_mask(torch.tensor([0, 63, 64, 96]), torch.arange(97), torch.tensor([False, True]))
    expected = [list(range(1)), list(range(64)), list(range(32)) + list(range(33, 65)),
                list(range(32)) + list(range(65, 97))]
    for row, position in enumerate((0, 63, 64, 96)):
        assert mask[0, 0, row].nonzero().flatten().tolist() == list(range(position+1))
        assert mask[0, 1, row].nonzero().flatten().tolist() == expected[row]


class HeadPolicy:
    def __init__(self, layers, original):
        self.layer_by_module = {id(layer.self_attn): index for index, layer in enumerate(layers)}
        self.original = original

    def begin(self, mode, prefill, reference=None, ratio=(1, 1)):
        numerator, denominator = ratio
        assert 0 <= numerator <= 255 and 1 <= denominator <= 255
        assert mode in MODES and (mode != "frozen_streaming" or reference is not None)
        self.mode = mode
        self.prefill = prefill
        self.reference = reference
        self.ratio = ratio
        self.geometry = causal_geometry(prefill) if mode == "live_streaming" else None
        layer_count = len(self.layer_by_module)
        self.calls = [0] * layer_count
        self.flags = [None] * layer_count  # GPU Boolean [head] for each layer after prefill.
        self.head_counts = [0] * layer_count
        self.prefill_dense = self.prefill_kept = self.decode_dense = self.decode_kept = 0

    def __call__(self, module, query, key, value, attention_mask, **kwargs):
        """Operate on query [1, head, query, feature] and key/value [1, key head, key, feature]."""
        layer = self.layer_by_module.get(id(module))
        if layer is None:
            return self.original(module, query, key, value, attention_mask, **kwargs)
        q_count, k_count = query.shape[2], key.shape[2]
        assert query.shape == (1, HEADS, q_count, WIDTH)
        assert key.shape == value.shape == (1, KEY_HEADS, k_count, WIDTH)
        calls = self.calls[layer]
        if calls == 0:
            assert q_count == k_count == self.prefill
            if self.mode == "live_streaming":
                decision, _ = classify_layer(query[0], key[0], kwargs["scaling"], self.geometry, False)
                if layer == 0 and self.reference is not None:
                    assert decision["fixed_inner_recent"] == self.reference[layer]["fixed_inner_recent"]
            elif self.mode == "frozen_streaming":
                decision = self.reference[layer]
            if self.mode in ("frozen_streaming", "live_streaming"):
                numerator, denominator = self.ratio
                flags = [recent*denominator > inner*numerator for inner, recent in decision["fixed_inner_recent"]]
            else:
                flags = [False] * HEADS
            self.flags[layer] = torch.tensor(flags, dtype=torch.bool, device=query.device)
            self.head_counts[layer] = sum(flags)
        else:
            assert q_count == 1 and k_count == self.prefill+calls
        self.calls[layer] += 1

        # The pilot has no padding. Count causal pairs using the union of the two windows.
        start = k_count-q_count
        dense = q_count*start + q_count*(q_count+1)//2
        streaming = sum(min(position+1, SINK_TOKENS+RECENT_TOKENS) for position in range(start, k_count))
        kept = HEADS*dense - self.head_counts[layer]*(dense-streaming)
        if calls == 0:
            self.prefill_dense += HEADS*dense
            self.prefill_kept += kept
        else:
            self.decode_dense += HEADS*dense
            self.decode_kept += kept

        if self.mode != "dense":
            absolute_queries = torch.arange(start, k_count, device=query.device)
            absolute_keys = torch.arange(k_count, device=query.device)
            allowed = streaming_mask(absolute_queries, absolute_keys, self.flags[layer])
            if attention_mask is None:
                attention_mask = allowed
            elif attention_mask.dtype == torch.bool:
                attention_mask = attention_mask & allowed
            else:
                attention_mask = attention_mask.masked_fill(~allowed, float("-inf"))
        return self.original(module, query, key, value, attention_mask, **kwargs)


@torch.inference_mode()
def main():
    torch.set_num_threads(3)
    torch.set_num_interop_threads(1)
    torch.manual_seed(0)
    verify_mask()
    check_memory(16 * GIB)
    assert torch.cuda.mem_get_info()[0] > 12 * GIB
    torch.cuda.set_per_process_memory_fraction(0.84)
    torch.cuda.reset_peak_memory_stats()

    records = ROOT / "records"
    policy_path = records / "batch416_vqa_head_policy_result.json"
    policy = json.loads(policy_path.read_text())
    assert policy["state"] == "frozen_head_policy_measured_on_vqa_pilot"
    details_path = Path(policy["local_details"])
    assert sha256(details_path) == policy["local_details_sha256"]
    with gzip.open(details_path, "rt") as stream:
        fixed_counts = json.load(stream)
    manifest_path = ROOT / ".cache/model_reference/vqav2_pilot/manifest.json"
    samples = json.loads(manifest_path.read_text())["samples"]
    assert len(samples) == len(policy["cases"]) == len(fixed_counts) == 64

    baseline_path = records / "format346_vqav2_inference.json.gz"
    guard_path = records / "format347_gpu_guard_result.json"
    scoring_path = records / "format348_official_scoring.json"
    baseline_raw = gzip.decompress(baseline_path.read_bytes())
    guard = json.loads(guard_path.read_text())
    assert guard["state"] == "completed" and guard["native_exit_status"] == 0 and guard["input_drift"] == []
    assert hashlib.sha256(baseline_raw).hexdigest() == guard["summary_sha256"]
    baseline = json.loads(baseline_raw)
    assert baseline["state"] == "completed" and baseline["checkpoint_revision"] == policy["checkpoint_revision"]
    archived_answers = {case["question_id"]: case["answer_tokens"] for case in baseline["cases"] if case["mode"] == "floating"}
    assert len(archived_answers) == 64
    archived_score = json.loads(scoring_path.read_text())["results"]["floating"]
    evaluator, normalizer, evaluator_digests = load_official_sources(ROOT)
    original = ALL_ATTENTION_FUNCTIONS["sdpa"]
    software = (Path(inspect.getsourcefile(LlamaAttention)), Path(inspect.getsourcefile(original)))
    paths = (Path(__file__), policy_path, manifest_path, baseline_path, guard_path, scoring_path,
             ROOT / "syn/score_tri_oracle_format326_vqav2.py", *software)
    hashes = policy["source_sha256"] | evaluator_digests | {
        str(path): sha256(path) for path in paths
    } | {str(details_path): policy["local_details_sha256"]}
    assert all(sha256(Path(path)) == digest for path, digest in hashes.items())
    output = records / "batch417_sparse_answers_result.json"
    assert not output.exists()

    model_dir = ROOT / ".cache/model_reference/tiny_llava_v1"
    tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
    processor = LlavaProcessor(
        image_processor=CLIPImageProcessorPil.from_pretrained(model_dir, local_files_only=True),
        tokenizer=tokenizer, patch_size=14, vision_feature_select_strategy="default", num_additional_image_tokens=1,
    )
    model = LlavaForConditionalGeneration.from_pretrained(
        model_dir, local_files_only=True, dtype=torch.float32, attn_implementation="sdpa", use_kernels=False,
    ).to("cuda").eval()
    layers = model.model.language_model.layers
    assert len(layers) == policy["layers_per_question"] == 22
    controller = HeadPolicy(layers, original)
    results = {mode: [] for mode in MODES}
    ALL_ATTENTION_FUNCTIONS["sdpa"] = controller
    try:
        for index, sample in enumerate(samples):
            check_memory(12 * GIB)
            with Image.open(ROOT / sample["image"]) as opened:
                image = opened.convert("RGB")
            prompt = "USER: <image>\n" + sample["question"] + "\nAnswer the question using a single word or phrase.\nASSISTANT:"
            batch = processor(images=image, text=prompt, return_tensors="pt").to("cuda")
            # Unpadded input IDs and mask [1, prefill]; image [1, 3, height, width].
            assert batch["input_ids"].shape[0] == 1 and bool(batch["attention_mask"].all())
            prefill = batch["input_ids"].shape[1]
            question_id = sample["question_id"]
            assert (question_id, prefill) == (policy["cases"][index]["question_id"], policy["cases"][index]["prefill_tokens"])
            for mode in MODES:
                controller.begin(mode, prefill, fixed_counts[index])
                # Generated IDs [1, prefill + answer], with one cached decode query per subsequent token.
                generated = model.generate(**batch, max_new_tokens=16, do_sample=False, use_cache=True)
                answer_ids = generated[0, prefill:].tolist()
                assert 1 <= len(answer_ids) <= 16 and controller.calls == [len(answer_ids)]*len(layers)
                if mode in ("dense", "explicit_dense_mask"):
                    assert answer_ids == archived_answers[question_id], (mode, question_id, answer_ids)
                if mode == "frozen_streaming":
                    assert controller.head_counts == [layer["fixed_streaming"] for layer in fixed_counts[index]]
                answer = processor.batch_decode(generated[:, prefill:], skip_special_tokens=True)[0]
                results[mode].append({
                    "question_id": question_id, "image_id": sample["image_id"], "prefill_tokens": prefill,
                    "answer": answer, "answer_tokens": answer_ids, "heads_streaming": sum(controller.head_counts),
                    "prefill_dense_pairs": controller.prefill_dense, "prefill_kept_pairs": controller.prefill_kept,
                    "decode_dense_pairs": controller.decode_dense, "decode_kept_pairs": controller.decode_kept,
                })
            print(f"BATCH417_CASE case={index} qid={question_id}", flush=True)
    finally:
        ALL_ATTENTION_FUNCTIONS["sdpa"] = original

    scores = {mode: score_cases(samples, cases, evaluator, normalizer) for mode, cases in results.items()}
    assert scores["dense"] == scores["explicit_dense_mask"] == archived_score
    assert all(sha256(Path(path)) == digest for path, digest in hashes.items())
    totals = {}
    for mode, cases in results.items():
        totals[mode] = {key: sum(case[key] for case in cases) for key in
                        ("heads_streaming", "prefill_dense_pairs", "prefill_kept_pairs", "decode_dense_pairs", "decode_kept_pairs")}
        totals[mode]["changed_answer_sequences"] = sum(case["answer_tokens"] != archived_answers[case["question_id"]] for case in cases)
        totals[mode]["official_consensus_percent"] = scores[mode]["official_vqa_consensus_percent_on64"]
    assert totals["frozen_streaming"]["heads_streaming"] == policy["fixed_streaming"]
    result = {
        "state": "sparse_attention_answer_pilot_scored", "scope": __doc__, "checkpoint_revision": policy["checkpoint_revision"],
        "questions": len(samples), "layers": len(layers), "sink_tokens": SINK_TOKENS, "recent_tokens": RECENT_TOKENS,
        "tile_keys": TILE, "local_ratio_threshold": 1, "runtime_token_merging_applied": False,
        "attention_implementation": "floating point scaled dot-product attention with a Boolean mask over a dense tensor",
        "eligible_pairs_are_analytic_not_measured_compute": True, "full_paper_results_matched": False,
        "dense_and_explicit_mask_reproduced_archived_answers_and_scores": True,
        "peak_gpu_bytes": torch.cuda.max_memory_allocated(), "mode_totals": totals,
        "scores": scores, "cases": results, "source_sha256": hashes,
    }
    with output.open("x") as stream:
        stream.write(json.dumps(result, separators=(",", ":")) + "\n")
    print("BATCH417_VERIFIED " + json.dumps(totals, separators=(",", ":")), flush=True)


if __name__ == "__main__":
    main()
