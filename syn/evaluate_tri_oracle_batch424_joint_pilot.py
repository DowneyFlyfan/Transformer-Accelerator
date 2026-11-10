"""Score cumulative token compaction, streaming heads, and integer feed-forward together."""

import gzip
import hashlib
import json
from pathlib import Path

from transformers.models.llama.modeling_llama import ALL_ATTENTION_FUNCTIONS

from evaluate_tri_oracle_batch417_sparse_answers import merge_input_digests
from evaluate_tri_oracle_batch422_compact_decoder import CompactDecoder
from evaluate_tri_oracle_batch421_merge_aware_attention import FEATURES, IMAGE_TOKENS, MINIMUM_MATCHES
from verify_tri_oracle_batch414_head_policy import (
    ROOT, AutoTokenizer, CLIPImageProcessorPil, Image, LlavaForConditionalGeneration, LlavaProcessor, torch,
)
from run_tri_oracle_batch396_masks import GIB, check_memory, sha256
from score_tri_oracle_format326_vqav2 import load_official_sources, score_cases
from tri_oracle_format345_first_token import evaluate_protected
from tri_oracle_integer_reference import IntegerFeedForwardReference


MODES = {
    "unmerged_integer_dense": ("identity", True, False),
    "unmerged_integer_pruned": ("identity", True, True),
    "compact_streaming_float": ("compact_and_streaming", False, False),
    "compact_streaming_integer_dense": ("compact_and_streaming", True, False),
    "all_three": ("compact_and_streaming", True, True),
}
UNMERGED_ARCHIVE_MODES = {
    "unmerged_integer_dense": "integer_dense",
    "unmerged_integer_pruned": "integer_predicted",
}
CHANNELS = 5632


class FeedForward:
    def __init__(self, layer, decoder, first, ordinary):
        self.module = layer.mlp
        self.original = self.module.forward
        self.norm = layer.post_attention_layernorm
        self.decoder = decoder
        self.first = first
        self.ordinary = ordinary
        self.reference = IntegerFeedForwardReference(layer.mlp.gate_proj.weight, layer.mlp.up_proj.weight,
            layer.mlp.down_proj.weight, self.norm.variance_epsilon)
        self.enabled = False
        self.handle = self.norm.register_forward_pre_hook(self.capture)
        self.module.forward = self.forward

    def close(self):
        self.handle.remove()
        self.module.forward = self.original

    def begin(self, enabled, prune):
        self.enabled, self.prune = enabled, prune
        self.residual = None
        self.positions = []
        self.prefill_rows = self.decode_rows = self.prefill_skipped = self.decode_skipped = 0
        self.prefill_predicted = self.decode_predicted = 0

    def capture(self, _module, arguments):
        """Capture pre-scale residual [1, retained token, feature] before normalization."""
        if self.enabled:
            assert self.residual is None
            self.residual = arguments[0][0]

    def forward(self, hidden):
        """Evaluate unchanged integer arithmetic on normalized activations [1, retained token, feature]."""
        if not self.enabled:
            return self.original(hidden)
        rows = hidden.shape[1]
        assert hidden.shape == (1, rows, FEATURES) and self.residual.shape == (rows, FEATURES)
        position = int(self.decoder.positions[0])
        assert position == (0 if self.decoder.prefill_active else self.decoder.prefill_length+self.decoder.decode_steps)
        raw, output, stats = evaluate_protected(self.reference, hidden[0], self.residual, self.ordinary,
                                                self.first, position, prune=self.prune)
        self.residual = None
        assert raw.shape == output.shape == (rows, FEATURES) and bool(torch.isfinite(output).all())
        self.positions.append(position)
        predicted = int(stats["skip_count"].sum())
        assert 0 <= predicted <= rows*CHANNELS
        skipped = predicted if self.prune else 0
        if self.decoder.prefill_active:
            self.prefill_rows += rows
            self.prefill_predicted += predicted
            self.prefill_skipped += skipped
        else:
            self.decode_rows += rows
            self.decode_predicted += predicted
            self.decode_skipped += skipped
        return output[None].to(hidden.dtype)


@torch.inference_mode()
def main():
    torch.set_num_threads(3)
    torch.set_num_interop_threads(1)
    torch.manual_seed(0)
    check_memory(16*GIB)
    assert torch.cuda.mem_get_info()[0] > 12*GIB
    torch.cuda.set_per_process_memory_fraction(0.84)
    torch.cuda.reset_peak_memory_stats()
    records = ROOT / "records"
    compact_path = records / "batch422_compact_decoder_result.json"
    compact = json.loads(compact_path.read_text())
    assert compact["state"] == "cumulative_compact_decoder_pilot_scored" and compact["minimum_matching_signs"] == MINIMUM_MATCHES
    ff_archive = records / "format346_vqav2_inference.json.gz"
    ff_guard = records / "format347_gpu_guard_result.json"
    ff_scoring = records / "format348_official_scoring.json"
    guard = json.loads(ff_guard.read_text())
    ff_raw = gzip.decompress(ff_archive.read_bytes())
    assert guard["state"] == "completed" and guard["native_exit_status"] == 0 and guard["input_drift"] == []
    assert hashlib.sha256(ff_raw).hexdigest() == guard["summary_sha256"]
    ff = json.loads(ff_raw)
    assert ff["state"] == "completed" and ff["sample_count"] == 64
    dense_baselines = json.loads(ff_scoring.read_text())["results"]
    manifest_path = ROOT / ".cache/model_reference/vqav2_pilot/manifest.json"
    samples = json.loads(manifest_path.read_text())["samples"]
    assert len(samples) == 64

    ordinary_path = ROOT / ".cache/model_reference/format335/layer_policy.json"
    first_path = ROOT / ".cache/model_reference/format322/layer_policy.json"
    ordinary = json.loads(ordinary_path.read_text())
    first = json.loads(first_path.read_text())
    assert ordinary["state"] == "row_balanced_exponent_bucket_policy"
    assert len(ordinary["layers"]) == len(first["layers"]) == 22
    evaluator, normalizer, evaluator_digests = load_official_sources(ROOT)
    hashes = compact["source_sha256"].copy()
    paths = (Path(__file__), compact_path, ff_archive, ff_guard, ff_scoring, manifest_path, ordinary_path, first_path,
             ROOT / "syn/evaluate_tri_oracle_batch422_compact_decoder.py", ROOT / "syn/tri_oracle_integer_reference.py",
             ROOT / "syn/tri_oracle_format335_policy.py", ROOT / "syn/tri_oracle_format345_first_token.py")
    merge_input_digests(hashes, evaluator_digests)
    merge_input_digests(hashes, {str(path):sha256(path) for path in paths})
    frozen = {str((ROOT/filename).resolve()):digest for filename,digest in ff["source_sha256"].items()}
    for path in paths[6:8]+paths[9:]:
        assert hashes[str(path)] == frozen[str(path.resolve())], path
    assert all(sha256(Path(path))==digest for path,digest in hashes.items())
    output = records / "batch424_joint_pilot_result.json"
    assert not output.exists()

    model_dir = ROOT / ".cache/model_reference/tiny_llava_v1"
    tokenizer = AutoTokenizer.from_pretrained(model_dir,local_files_only=True)
    processor = LlavaProcessor(image_processor=CLIPImageProcessorPil.from_pretrained(model_dir,local_files_only=True),
                              tokenizer=tokenizer,patch_size=14,vision_feature_select_strategy="default",num_additional_image_tokens=1)
    model = LlavaForConditionalGeneration.from_pretrained(model_dir,local_files_only=True,dtype=torch.float32,
                                                        attn_implementation="sdpa",use_kernels=False).to("cuda").eval()
    assert model.generation_config.eos_token_id == 2 and model.generation_config.num_beams in (None,1)
    assert ff["checkpoint_revision"] == json.loads((records/"batch419_trained_merger_fixture.json").read_text())["checkpoint_revision"]
    original = ALL_ATTENTION_FUNCTIONS["sdpa"]
    decoder = CompactDecoder(model,original,tuple(compact["local_ratio"]))
    layers = decoder.language.layers
    assert len(layers) == 22
    replacements = [FeedForward(layer,decoder,first["layers"][index],ordinary["layers"][index]) for index,layer in enumerate(layers)]
    archived = {(item["mode"],item["question_id"]):item["answer_tokens"] for item in ff["cases"]}
    compact_archive = {item["question_id"]:item for item in compact["cases"]["compact_and_streaming"]}
    results = {mode:[] for mode in MODES}
    ALL_ATTENTION_FUNCTIONS["sdpa"] = decoder.attend
    try:
        for index,sample in enumerate(samples):
            check_memory(12*GIB)
            question = sample["question_id"]
            with Image.open(ROOT/sample["image"]) as opened:
                image = opened.convert("RGB")
            prompt = "USER: <image>\n" + sample["question"] + "\nAnswer the question using a single word or phrase.\nASSISTANT:"
            batch = processor(images=image,text=prompt,return_tensors="pt").to("cuda")
            ids = batch["input_ids"]
            positions = (ids[0]==model.config.image_token_id).nonzero().flatten().tolist()
            assert len(positions)==IMAGE_TOKENS and positions==list(range(positions[0],positions[0]+IMAGE_TOKENS))
            assert ids.shape[0]==1 and bool(batch["attention_mask"].all())
            # Original embeddings [1, prompt token, feature] include the projected image grid.
            embeddings = model.model.get_input_embeddings()(ids)
            image_states = torch.cat(model.model.get_image_features(batch["pixel_values"],return_dict=True).pooler_output,dim=0)
            assert image_states.shape == (IMAGE_TOKENS, FEATURES)
            image_states = image_states.to(embeddings.device,embeddings.dtype)
            embeddings = embeddings.masked_scatter(model.model.get_placeholder_mask(ids,embeddings,image_states),image_states)
            for mode,(decoder_mode,enabled,prune) in MODES.items():
                for replacement in replacements:
                    replacement.begin(enabled,prune)
                tokens = decoder.generate(embeddings,positions[0],decoder_mode,{2},None)
                if mode in UNMERGED_ARCHIVE_MODES:
                    assert tokens == archived[(UNMERGED_ARCHIVE_MODES[mode],question)], (mode,question,tokens)
                elif mode=="compact_streaming_float":
                    assert tokens == compact_archive[question]["answer_tokens"]
                    assert decoder.layer_slots == compact_archive[question]["layer_cache_slots"]
                    assert decoder.pairs == compact_archive[question]["prefill_kept_pairs"]
                if enabled:
                    expected = [0]+list(range(ids.shape[1],ids.shape[1]+len(tokens)-1))
                    for layer_index,replacement in enumerate(replacements):
                        assert replacement.positions == expected and replacement.residual is None
                        assert replacement.prefill_rows == decoder.layer_slots[layer_index]
                        assert replacement.decode_rows == len(tokens)-1
                        assert replacement.prefill_skipped == (replacement.prefill_predicted if prune else 0)
                        assert replacement.decode_skipped == (replacement.decode_predicted if prune else 0)
                stats = {key:sum(getattr(layer,key) for layer in replacements) for key in
                         ("prefill_rows","decode_rows","prefill_skipped","decode_skipped","prefill_predicted","decode_predicted")}
                results[mode].append({"question_id":question,"image_id":sample["image_id"],"answer_tokens":tokens,
                    "answer":tokenizer.decode(tokens,skip_special_tokens=True),"prefill_tokens":ids.shape[1],
                    "prefill_slots":sum(decoder.layer_slots),"prefill_pairs":decoder.pairs,"streaming_heads":decoder.streaming_count,
                    "final_image_roots":decoder.layer_roots[-1]} | stats)
            print(f"BATCH424_CASE case={index} qid={question}",flush=True)
    finally:
        ALL_ATTENTION_FUNCTIONS["sdpa"] = original
        for replacement in replacements:
            replacement.close()

    scores = {mode:score_cases(samples,items,evaluator,normalizer) for mode,items in results.items()}
    for mode, archived_mode in UNMERGED_ARCHIVE_MODES.items():
        assert scores[mode] == dense_baselines[archived_mode]
    assert scores["compact_streaming_float"] == compact["scores"]["compact_and_streaming"]
    totals = {}
    for mode,items in results.items():
        totals[mode] = {key:sum(item[key] for item in items) for key in
                        ("prefill_slots","prefill_pairs","streaming_heads","final_image_roots","prefill_rows","decode_rows",
                         "prefill_skipped","decode_skipped","prefill_predicted","decode_predicted")}
        totals[mode]["consensus_percent"] = scores[mode]["official_vqa_consensus_percent_on64"]
    assert totals["all_three"]["prefill_skipped"]>0 and all(sha256(Path(path))==digest for path,digest in hashes.items())
    report = {"state":"joint_compact_streaming_integer_pilot_scored","scope":__doc__,"questions":len(samples),
              "checkpoint_revision":ff["checkpoint_revision"],"language_layers":len(layers),"channels_per_row":CHANNELS,
              "local_ratio":compact["local_ratio"],"minimum_matching_signs":MINIMUM_MATCHES,
              "fixed_point_feedforward_with_floating_normalization_input":True,"floating_point_attention":True,
              "skip_counts_are_applied_reference_masks":True,"full_paper_results_matched":False,
              "peak_gpu_bytes":torch.cuda.max_memory_allocated(),"totals":totals,"cases":results,"scores":scores,"source_sha256":hashes}
    with output.open("x") as stream:
        stream.write(json.dumps(report,separators=(",",":"))+"\n")
    print("BATCH424_VERIFIED "+json.dumps(totals,separators=(",",":")),flush=True)


if __name__ == "__main__":
    main()
