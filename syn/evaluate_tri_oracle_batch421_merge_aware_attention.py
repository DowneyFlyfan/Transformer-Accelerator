"""Apply causal token multiplicities to compact attention keys and score the pilot."""

from dataclasses import dataclass
import inspect
import json
import math
from pathlib import Path
from types import SimpleNamespace

from evaluate_tri_oracle_batch417_sparse_answers import (
    RECENT_TOKENS, SINK_TOKENS, merge_input_digests,
)
from verify_tri_oracle_batch414_head_policy import (
    HEADS, KEY_HEADS, ROOT, TILE, WIDTH, AutoTokenizer, CLIPImageProcessorPil,
    Image, LlavaForConditionalGeneration, LlavaProcessor, causal_geometry, classify_layer, np, torch,
)
from transformers.models.llama.modeling_llama import ALL_ATTENTION_FUNCTIONS, LlamaAttention

from run_tri_oracle_batch396_masks import GIB, check_memory, sha256
from score_tri_oracle_format326_vqav2 import load_official_sources, score_cases
from tri_oracle_token_merging_reference import merge_signs


IMAGE_WIDTH = 24
IMAGE_TOKENS = IMAGE_WIDTH**2
FEATURES = 2048
MINIMUM_MATCHES = 1536
MODES = ("identity", "merging", "merging_and_streaming")


@dataclass
class MergeFrame:
    # Original positions of surviving prefill keys [compact key] and dense image origins [image token].
    key_positions: torch.Tensor
    origins: torch.Tensor
    # Number of original image tokens per visible representative [prefix length, representative].
    prefix_counts: torch.Tensor


def build_frame(origins, image_start, prefill, device):
    """Construct ordered representative positions and causal multiplicities."""
    roots = [index for index, origin in enumerate(origins) if index == origin]
    origin_ranks = {origin: rank for rank, origin in enumerate(roots)}
    ranks = torch.tensor([origin_ranks[origin] for origin in origins], dtype=torch.long, device=device)
    contributions = torch.nn.functional.one_hot(ranks, num_classes=len(roots))
    prefix = torch.nn.functional.pad(contributions.cumsum(dim=0, dtype=torch.float32), (0, 0, 1, 0))
    positions = [*range(image_start), *(image_start+origin for origin in roots), *range(image_start+len(origins), prefill)]
    return MergeFrame(torch.tensor(positions, dtype=torch.long, device=device),
                      torch.tensor(origins, dtype=torch.long, device=device), prefix)


def causal_bias(frame, image_start, query_positions, key_positions):
    """Compute log multiplicity [query, compact key] at original causal positions."""
    image_tokens = frame.origins.numel()
    prefix_indices = (query_positions-image_start+1).clamp(0, image_tokens)
    multiplicities = frame.prefix_counts.index_select(0, prefix_indices)
    bias = torch.zeros((query_positions.numel(), key_positions.numel()), device=key_positions.device)
    bias[:, image_start:image_start+multiplicities.shape[1]] = multiplicities.log()
    return bias.masked_fill(key_positions[None, :] > query_positions[:, None], float("-inf"))


def verify_prefix_bias():
    # Original image 1..4 maps its third position to its first, with text on both sides.
    frame = build_frame([0, 1, 0, 3], 1, 6, "cpu")
    positions = torch.arange(6)
    bias = causal_bias(frame, 1, positions, frame.key_positions)
    assert frame.key_positions.tolist() == [0, 1, 2, 4, 5]
    assert frame.prefix_counts.tolist() == [[0,0,0], [1,0,0], [1,1,0], [2,1,0], [2,1,1]]
    raw = torch.tensor([0.3, -0.1, 0.6, 0.5, -0.2])
    expanded_ranks = [0, 1, 2, 1, 3, 4]
    for position in positions.tolist():
        visible = torch.tensor(expanded_ranks[:position+1])
        expected = torch.zeros_like(raw).scatter_add_(0, visible, torch.softmax(raw[visible], dim=0))
        torch.testing.assert_close(torch.softmax(raw+bias[position], dim=0), expected)


class MergeAwareAttention:
    def __init__(self, layers, original, ratio):
        self.indices = {id(layer.self_attn): index for index, layer in enumerate(layers)}
        self.original = original
        self.ratio = ratio

    def begin(self, mode, image_start, prefill, anchor=None):
        self.mode = mode
        self.image_start = image_start
        self.prefill = prefill
        self.anchor = anchor
        self.frames = {}
        self.head_flags = {}
        self.calls = [0] * len(self.indices)
        self.merged = self.streaming = self.prefill_key_slots = self.prefill_kept_pairs = 0
        self.short_frames = self.expanded_attention_checks = 0

    def capture_signs(self, module, args, kwargs):
        """Use image signs from normalized hidden [1, sequence, feature]."""
        index = self.indices[id(module)]
        hidden = args[0] if args else kwargs["hidden_states"]
        if self.calls[index]:
            assert hidden.shape == (1, 1, FEATURES)
            return
        assert hidden.shape == (1, self.prefill, FEATURES) and index not in self.frames
        if self.mode == "identity":
            origins = list(range(IMAGE_TOKENS))
        else:
            signs = hidden[0, self.image_start:self.image_start+IMAGE_TOKENS] < 0
            packed = np.packbits(signs.cpu().numpy(), axis=1, bitorder="little")
            words = [int.from_bytes(row.tobytes(), "little") for row in packed]
            origins, kinds = merge_signs(words, IMAGE_WIDTH, FEATURES, MINIMUM_MATCHES)
            if index == 0 and self.anchor is not None:
                assert [(kind << 10) | origin for origin,kind in zip(origins,kinds,strict=True)] == self.anchor
        frame = build_frame(origins, self.image_start, self.prefill, hidden.device)
        self.merged += self.prefill-frame.key_positions.numel()
        self.frames[index] = frame

    def verify_expansion(self, frame, query, key, value, compact_key, compact_value, bias, scaling):
        """Compare a sampled head against explicit copies of each representative at original positions."""
        positions = torch.tensor([self.image_start, self.image_start+23, self.image_start+288,
                                  self.image_start+575, self.prefill-1], device=query.device)
        original = torch.arange(self.prefill, device=query.device)
        expanded = original.clone()
        expanded[self.image_start:self.image_start+IMAGE_TOKENS] = self.image_start+frame.origins
        q = query[0, 0].index_select(0, positions).double()
        expanded_scores = (q @ key[0, 0].index_select(0, expanded).double().T) * scaling
        expanded_scores = expanded_scores.masked_fill(original[None, :] > positions[:, None], float("-inf"))
        expanded_value = value[0, 0].index_select(0, expanded).double()
        compact_scores = (q @ compact_key[0, 0].double().T)*scaling + bias.index_select(0, positions).double()
        torch.testing.assert_close(torch.softmax(expanded_scores, dim=1) @ expanded_value,
                                   torch.softmax(compact_scores, dim=1) @ compact_value[0, 0].double(),
                                   rtol=1e-6, atol=1e-7)
        self.expanded_attention_checks += len(positions)

    def __call__(self, module, query, key, value, attention_mask, **kwargs):
        """Preserve original query positions, and gather compact key/value columns for this attention call."""
        index = self.indices.get(id(module))
        if index is None:
            return self.original(module, query, key, value, attention_mask, **kwargs)
        calls = self.calls[index]
        q_count, k_count = query.shape[2], key.shape[2]
        assert query.shape == (1, HEADS, q_count, WIDTH) and key.shape == value.shape == (1, KEY_HEADS, k_count, WIDTH)
        assert (q_count, k_count) == ((1, self.prefill+calls) if calls else (self.prefill, self.prefill))
        frame = self.frames[index]
        positions = torch.arange(k_count-q_count, k_count, device=query.device)
        keys = frame.key_positions if calls == 0 else torch.cat((frame.key_positions, torch.arange(self.prefill, k_count, device=query.device)))
        compact_key = key.index_select(2, keys)
        compact_value = value.index_select(2, keys)
        bias = causal_bias(frame, self.image_start, positions, keys)
        if calls == 0:
            if index == 0 and self.anchor is not None and self.mode != "identity":
                self.verify_expansion(frame, query, key, value, compact_key, compact_value, bias, kwargs["scaling"])
            self.prefill_key_slots += keys.numel()
            flags = [False]*HEADS
            if self.mode == "merging_and_streaming":
                if keys.numel() > 3*TILE:
                    compact_queries = query[0].index_select(1, keys)
                    decision, _ = classify_layer(compact_queries, compact_key[0], kwargs["scaling"],
                                                 causal_geometry(keys.numel()), False)
                    numerator, denominator = self.ratio
                    flags = [recent*denominator > inner*numerator for inner,recent in decision["fixed_inner_recent"]]
                else:
                    self.short_frames += 1
            self.streaming += sum(flags)
            self.head_flags[index] = torch.tensor(flags, dtype=torch.bool, device=query.device)
        self.calls[index] += 1
        bias = bias[None, None]
        if self.mode == "merging_and_streaming":
            visible = torch.searchsorted(keys, positions, right=True)
            rank = torch.arange(keys.numel(), device=query.device)
            keep = (rank[None, :] < SINK_TOKENS) | (rank[None, :] >= visible[:, None]-RECENT_TOKENS)
            allowed = ~self.head_flags[index][:, None, None] | keep[None, :, :]
            bias = bias.masked_fill(~allowed[None], float("-inf"))
        if attention_mask is not None:
            current = attention_mask.index_select(-1, keys)
            bias = bias.masked_fill(~current, float("-inf")) if current.dtype == torch.bool else bias + current
        if calls == 0:
            self.prefill_kept_pairs += int(bias.isfinite().sum()) * (HEADS // bias.shape[1])
        return self.original(module, query, compact_key, compact_value, bias, **kwargs)


def verify_decode_mask():
    attention = object()
    def observe(_module, _query, key, value, bias, **_kwargs):
        return key[0,0,:,0].tolist(), value[0,0,:,0].tolist(), bias

    controller = MergeAwareAttention([SimpleNamespace(self_attn=attention)], observe, (8, 1))
    # Original positions 39..42 merge position 41 into position 39.
    prefill = 70
    frame = build_frame([0, 1, 0, 3], 39, prefill, "cpu")
    query = torch.zeros((1, HEADS, 1, WIDTH))
    key = torch.arange(prefill+1, dtype=torch.float32).reshape(1,1,-1,1).expand(1,KEY_HEADS,-1,WIDTH)
    expected_keys = [position for position in range(71) if position != 41]
    # At compact rank 38 the recent window starts at original position 38.
    streaming_keys = set(range(32)) | (set(range(38, 71)) - {41})
    for additive in (False, True):
        controller.begin("merging_and_streaming", 39, prefill)
        controller.calls[0] = 1
        controller.frames[0] = frame
        controller.head_flags[0] = torch.tensor([False, True] + [False]*(HEADS-2))
        if additive:
            upstream = torch.zeros((1,1,1,71))
            upstream[...,9] = float("-inf")
            upstream[...,70] = -0.75
        else:
            upstream = torch.ones((1,1,1,71), dtype=torch.bool)
            upstream[...,9] = False
        positions, values, bias = controller(attention, query, key, key+100, upstream)
        assert positions == expected_keys and values == [position+100 for position in expected_keys]
        assert controller.calls == [2]
        for head in (0, 1):
            allowed = set(expected_keys) if head == 0 else streaming_keys
            expected_bias = []
            for position in expected_keys:
                weight = math.log(2) if position == 39 else 0.0
                if additive and position == 70:
                    weight -= 0.75
                expected_bias.append(weight if position in allowed and position != 9 else float("-inf"))
            torch.testing.assert_close(bias[0,head,0], torch.tensor(expected_bias))


@torch.inference_mode()
def main():
    torch.set_num_threads(3)
    torch.set_num_interop_threads(1)
    torch.manual_seed(0)
    verify_prefix_bias()
    verify_decode_mask()
    check_memory(16*GIB)
    assert torch.cuda.mem_get_info()[0] > 12*GIB
    torch.cuda.set_per_process_memory_fraction(0.84)
    torch.cuda.reset_peak_memory_stats()
    records = ROOT / "records"
    fixture_path, native_path, pilot_path, calibrated_path = (records / name for name in
        ("batch419_trained_merger_fixture.json", "batch420_trained_merger_result.json", "batch417_sparse_answers_result.json",
         "batch418_vqa_ratio_result.json"))
    fixture, native, pilot, calibrated = (json.loads(path.read_text()) for path in (fixture_path,native_path,pilot_path,calibrated_path))
    assert native["state"] == "trained_image_token_merger_and_causal_prefixes_verified" and native["inventory"]["maps"] == 76032
    assert MINIMUM_MATCHES in native["thresholds"] and fixture["local_tie_priority"] == "up"
    assert pilot["state"] == "sparse_attention_answer_pilot_scored" and calibrated["state"] == "separately_selected_ratio_scored_on_fixed_vqa_pilot"
    assert fixture["checkpoint_revision"] == pilot["checkpoint_revision"] == calibrated["checkpoint_revision"]
    ratio = tuple(calibrated["selected_ratio"])
    assert ratio == (8, 1)
    original = ALL_ATTENTION_FUNCTIONS["sdpa"]
    software = (Path(inspect.getsourcefile(LlamaAttention)), Path(inspect.getsourcefile(original)))
    manifest_path = ROOT / ".cache/model_reference/vqav2_pilot/manifest.json"
    evaluator, normalizer, evaluator_digests = load_official_sources(ROOT)
    hashes = pilot["source_sha256"].copy()
    for bindings in (calibrated["source_sha256"], fixture["source_sha256"], native["source_and_fixture_sha256"], evaluator_digests):
        merge_input_digests(hashes, bindings)
    paths = (Path(__file__), fixture_path, native_path, pilot_path, calibrated_path, manifest_path, *software,
             ROOT / "syn/score_tri_oracle_format326_vqav2.py", ROOT / "syn/tri_oracle_token_merging_reference.py")
    merge_input_digests(hashes, {str(path): sha256(path) for path in paths})
    assert all(sha256(Path(path)) == digest for path,digest in hashes.items())
    anchor_file = Path(fixture["fixture"]) / f"map_{MINIMUM_MATCHES}.hex"
    assert hashes[str(anchor_file)] == sha256(anchor_file)
    anchor_map = [int(word, 16) for word in anchor_file.read_text().splitlines()[:IMAGE_TOKENS]]
    samples = json.loads(manifest_path.read_text())["samples"]
    baseline = {case["question_id"]: case["answer_tokens"] for case in pilot["cases"]["dense"]}
    assert len(samples) == len(baseline) == 64 and samples[0]["question_id"] == fixture["anchor_question_id"]
    output = records / "batch421_merge_aware_attention_result.json"
    assert not output.exists()

    model_dir = ROOT / ".cache/model_reference/tiny_llava_v1"
    tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
    processor = LlavaProcessor(image_processor=CLIPImageProcessorPil.from_pretrained(model_dir, local_files_only=True),
        tokenizer=tokenizer, patch_size=14, vision_feature_select_strategy="default", num_additional_image_tokens=1)
    model = LlavaForConditionalGeneration.from_pretrained(
        model_dir, local_files_only=True, dtype=torch.float32, attn_implementation="sdpa", use_kernels=False,
    ).to("cuda").eval()
    layers = model.model.language_model.layers
    assert len(layers) == 22
    controller = MergeAwareAttention(layers, original, ratio)
    handles = [layer.self_attn.register_forward_pre_hook(controller.capture_signs, with_kwargs=True) for layer in layers]
    results = {mode: [] for mode in MODES}
    ALL_ATTENTION_FUNCTIONS["sdpa"] = controller
    try:
        for index, sample in enumerate(samples):
            check_memory(12*GIB)
            with Image.open(ROOT / sample["image"]) as opened:
                image = opened.convert("RGB")
            prompt = "USER: <image>\n" + sample["question"] + "\nAnswer the question using a single word or phrase.\nASSISTANT:"
            batch = processor(images=image, text=prompt, return_tensors="pt").to("cuda")
            assert bool(batch["attention_mask"].all())
            image_positions = (batch["input_ids"][0] == model.config.image_token_index).nonzero().flatten().tolist()
            assert len(image_positions) == IMAGE_TOKENS and image_positions == list(range(image_positions[0],image_positions[0]+IMAGE_TOKENS))
            image_start, prefill = image_positions[0], batch["input_ids"].shape[1]
            for mode in MODES:
                controller.begin(mode, image_start, prefill, anchor_map if index == 0 else None)
                # Original query/answer token IDs [1, prefill + generated], append-only decode cache.
                generated = model.generate(**batch, max_new_tokens=16, do_sample=False, use_cache=True)
                tokens = generated[0, prefill:].tolist()
                assert 1 <= len(tokens) <= 16 and controller.calls == [len(tokens)]*len(layers)
                assert controller.prefill_key_slots + controller.merged == prefill*len(layers)
                if mode == "identity":
                    assert controller.merged == controller.streaming == 0 and tokens == baseline[sample["question_id"]]
                results[mode].append({"question_id": sample["question_id"], "image_id": sample["image_id"],
                    "answer": processor.batch_decode(generated[:,prefill:], skip_special_tokens=True)[0], "answer_tokens": tokens,
                    "prefill_tokens": prefill, "merged": controller.merged, "heads_streaming": controller.streaming,
                    "prefill_key_slots": controller.prefill_key_slots, "prefill_kept_pairs": controller.prefill_kept_pairs,
                    "short_frames": controller.short_frames, "expanded_attention_checks": controller.expanded_attention_checks})
            print(f"BATCH421_CASE case={index} qid={sample['question_id']}", flush=True)
    finally:
        ALL_ATTENTION_FUNCTIONS["sdpa"] = original
        for handle in handles:
            handle.remove()

    scores = {mode: score_cases(samples, items, evaluator, normalizer) for mode,items in results.items()}
    assert scores["identity"] == pilot["scores"]["dense"]
    totals = {}
    for mode, items in results.items():
        totals[mode] = {key: sum(item[key] for item in items) for key in
                        ("merged", "heads_streaming", "prefill_key_slots", "prefill_kept_pairs", "short_frames", "expanded_attention_checks")}
        totals[mode]["consensus_percent"] = scores[mode]["official_vqa_consensus_percent_on64"]
        totals[mode]["changed_answers"] = sum(item["answer_tokens"] != baseline[item["question_id"]] for item in items)
    assert totals["merging"]["expanded_attention_checks"] == totals["merging_and_streaming"]["expanded_attention_checks"] == 5
    assert all(sha256(Path(path)) == digest for path,digest in hashes.items())
    report = {"state": "causal_merge_aware_attention_pilot_scored", "scope": __doc__, "checkpoint_revision": fixture["checkpoint_revision"],
              "local_minimum_matches": MINIMUM_MATCHES, "local_ratio": ratio, "sink_tokens": SINK_TOKENS, "recent_tokens": RECENT_TOKENS,
              "questions": len(samples), "language_layers": len(layers), "image_tokens_per_layer": IMAGE_TOKENS,
              "retained_original_queries_and_cache_slots": True, "compact_key_and_value_tensors_used_in_attention": True,
              "streaming_windows_coordinate": "chronological compact representative rank",
              "ratio_reused_from_unmerged_calibration": True, "decode_mask_controls": 2,
              "attention_precision": "floating point with logarithmic causal multiplicity bias", "full_paper_results_matched": False,
              "peak_gpu_bytes": torch.cuda.max_memory_allocated(), "totals": totals, "cases": results, "scores": scores, "source_sha256": hashes}
    with output.open("x") as stream:
        stream.write(json.dumps(report,separators=(",",":")) + "\n")
    print("BATCH421_VERIFIED " + json.dumps(totals,separators=(",",":")), flush=True)


if __name__ == "__main__":
    main()
