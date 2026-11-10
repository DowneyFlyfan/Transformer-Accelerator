"""Run cumulative image-token compaction through queries, residuals and layer caches."""

import inspect
import json
from pathlib import Path
import tempfile

from transformers.cache_utils import DynamicCache
from transformers.models.llama.modeling_llama import ALL_ATTENTION_FUNCTIONS, LlamaAttention, LlamaDecoderLayer
from transformers.models.llava.modeling_llava import LlavaModel

from evaluate_tri_oracle_batch417_sparse_answers import RECENT_TOKENS, SINK_TOKENS, merge_input_digests
from evaluate_tri_oracle_batch421_merge_aware_attention import (
    FEATURES, IMAGE_TOKENS, IMAGE_WIDTH, MINIMUM_MATCHES, build_frame, causal_bias,
)
from verify_tri_oracle_batch414_head_policy import (
    HEADS, KEY_HEADS, ROOT, TILE, WIDTH, AutoTokenizer, CLIPImageProcessorPil, Image,
    LlavaForConditionalGeneration, LlavaProcessor, causal_geometry, classify_layer, np, torch,
)
from run_tri_oracle_batch396_masks import GIB, check_memory, sha256
from score_tri_oracle_format326_vqav2 import load_official_sources, score_cases
from tri_oracle_token_merging_reference import merge_signs


MODES = ("identity", "compact", "compact_and_streaming")


def refine_origins(previous, signs, image_width, sign_width, minimum_matches):
    """Merge surviving image roots without splitting groups from earlier layers.

    The original raster still identifies the upper and left semantic neighbors.
    A removed cell inherits its previous group's updated representative.
    """
    roots = []
    for position, origin in enumerate(previous):
        if origin != position:
            roots.append(roots[origin])
            continue
        upper = roots[position-image_width] if position >= image_width else None
        left = roots[position-1] if position % image_width else None
        chosen = position
        for neighbor in (upper, left):
            if neighbor is not None and sign_width-(signs[position]^signs[neighbor]).bit_count() >= minimum_matches:
                chosen = neighbor
                break
        roots.append(chosen)
    return roots


def verify_origin_refinement():
    previous = [0, 1, 0, 3]
    assert refine_origins(previous, {0: 0, 1: 15, 3: 15}, 2, 4, 4) == [0, 1, 0, 1]
    assert refine_origins(previous, {0: 0, 1: 0, 3: 0}, 2, 4, 4) == [0, 0, 0, 0]
    signs = [5, 9, 4, 13, 3, 4, 0, 4, 5, 15, 2, 7]
    for threshold in range(5):
        assert refine_origins(list(range(len(signs))), signs, 4, 4, threshold) == merge_signs(signs, 4, 4, threshold)[0]


class CompactDecoder:
    def __init__(self, model, original_attention, ratio):
        self.model = model
        self.language = model.model.language_model
        self.layer_ids = {id(layer.self_attn) for layer in self.language.layers}
        self.attention = original_attention
        self.ratio = ratio

    def attend(self, module, query, key, value, attention_mask, **kwargs):
        """Attention sees only retained queries [1, head, query, feature] and compact keys."""
        if id(module) not in self.layer_ids:
            return self.attention(module, query, key, value, attention_mask, **kwargs)
        assert module is self.current_attention and attention_mask is None
        queries, keys = self.positions, self.key_positions
        assert query.shape == (1, HEADS, queries.numel(), WIDTH)
        assert key.shape == value.shape == (1, KEY_HEADS, keys.numel(), WIDTH)
        if self.mode == "identity":
            if self.prefill_active:
                self.pairs += HEADS * queries.numel() * (queries.numel()+1)//2
            return self.attention(module, query, key, value, None, **kwargs)

        bias = causal_bias(self.frames[self.layer_index], self.image_start, queries, keys)[None,None]
        if self.mode == "compact_and_streaming":
            if self.prefill_active:
                prompt_keys = int(torch.searchsorted(keys, self.prompt_length))
                if prompt_keys > 3*TILE:
                    decision, _ = classify_layer(query[0,:,:prompt_keys], key[0,:,:prompt_keys], kwargs["scaling"],
                                                 causal_geometry(prompt_keys), False)
                    numerator, denominator = self.ratio
                    flags = [recent*denominator > inner*numerator for inner,recent in decision["fixed_inner_recent"]]
                else:
                    flags = [False]*HEADS
                self.streaming[self.layer_index] = torch.tensor(flags, dtype=torch.bool, device=query.device)
                self.streaming_count += sum(flags)
            visible = torch.searchsorted(keys, queries, right=True)
            rank = torch.arange(keys.numel(), device=query.device)
            window = (rank[None,:] < SINK_TOKENS) | (rank[None,:] >= visible[:,None]-RECENT_TOKENS)
            allowed = ~self.streaming[self.layer_index][:,None,None] | window[None,:,:]
            bias = bias.masked_fill(~allowed[None], float("-inf"))
        if self.prefill_active:
            self.pairs += int(bias.isfinite().sum()) * (HEADS//bias.shape[1])
        return self.attention(module, query, key, value, bias, **kwargs)

    def layer_forward(self, index, hidden, positions, key_positions):
        self.layer_index = index
        layer = self.language.layers[index]
        self.current_attention = layer.self_attn
        self.positions = positions
        self.key_positions = key_positions
        position_ids = positions[None]
        rotary = self.language.rotary_emb(hidden, position_ids)
        result = layer(hidden, position_ids=position_ids, position_embeddings=rotary,
                       past_key_values=self.cache, use_cache=True)
        assert result.shape == (1, positions.numel(), FEATURES)
        assert self.cache.get_seq_length(index) == key_positions.numel()
        return result

    def prefill(self, embeddings, image_start, mode, prompt_length, anchor=None):
        """Compact the retained hidden [1, token, feature] before each decoder layer."""
        hidden = embeddings
        self.mode = mode
        self.prompt_length = prompt_length
        self.prefill_length = hidden.shape[1]
        self.prefill_active = True
        self.image_start = image_start
        self.cache = DynamicCache(config=self.language.config)
        self.frames, self.streaming, self.layer_slots, self.layer_roots = [], {}, [], []
        self.trace = []
        self.streaming_count = self.pairs = 0
        positions = torch.arange(self.prefill_length, device=hidden.device)
        origins = list(range(IMAGE_TOKENS))
        roots = list(range(IMAGE_TOKENS))
        for index, layer in enumerate(self.language.layers):
            if mode != "identity":
                normalized = layer.input_layernorm(hidden[:,image_start:image_start+len(roots)])
                packed = np.packbits((normalized[0]<0).cpu().numpy(), axis=1, bitorder="little")
                signs = {root: int.from_bytes(row.tobytes(), "little") for root,row in zip(roots,packed,strict=True)}
                previous = origins
                origins = refine_origins(previous, signs, IMAGE_WIDTH, FEATURES, MINIMUM_MATCHES)
                assert all(origin <= i and origins[origin] == origin and origin == origins[previous[i]]
                           for i,origin in enumerate(origins))
                roots = [i for i,origin in enumerate(origins) if i==origin]
                assert all(root in signs for root in roots)
                if index == 0 and anchor is not None:
                    assert origins == anchor
                if anchor is not None:
                    self.trace.append((signs, origins))
                frame = build_frame(origins, image_start, self.prefill_length, hidden.device)
                selection = torch.searchsorted(positions, frame.key_positions)
                assert torch.equal(positions.index_select(0,selection), frame.key_positions)
                hidden = hidden.index_select(1, selection)
                positions = frame.key_positions
            else:
                frame = None
            self.frames.append(frame)
            self.layer_slots.append(positions.numel())
            self.layer_roots.append(len(roots))
            hidden = self.layer_forward(index, hidden, positions, positions)
        self.prefill_active = False
        self.decode_steps = 0
        return self.model.lm_head(self.language.norm(hidden)[:,-1:])[0,0]

    def decode(self, token):
        """Append a single original-position text token to every compact layer cache."""
        hidden = self.language.embed_tokens(token.reshape(1,1))
        device = hidden.device
        end = self.prefill_length+self.decode_steps+1
        position = torch.tensor([end-1], device=device)
        for index, frame in enumerate(self.frames):
            appended = torch.arange(self.prefill_length, end, device=device)
            keys = torch.arange(end, device=device) if frame is None else torch.cat((frame.key_positions, appended))
            assert self.cache.get_seq_length(index) == keys.numel()-1
            hidden = self.layer_forward(index, hidden, position, keys)
        self.decode_steps += 1
        return self.model.lm_head(self.language.norm(hidden))[0,0]

    def generate(self, embeddings, image_start, mode, eos, anchor):
        prefill = embeddings.shape[1]
        logits = self.prefill(embeddings, image_start, mode, prefill, anchor)
        answer = []
        for step in range(16):
            token = logits.argmax()
            answer.append(int(token))
            if answer[-1] in eos or step == 15:
                break
            logits = self.decode(token)
        assert self.decode_steps == len(answer)-1
        return answer


@torch.inference_mode()
def main():
    torch.set_num_threads(3)
    torch.set_num_interop_threads(1)
    torch.manual_seed(0)
    verify_origin_refinement()
    check_memory(16*GIB)
    assert torch.cuda.mem_get_info()[0] > 12*GIB
    torch.cuda.set_per_process_memory_fraction(0.84)
    torch.cuda.reset_peak_memory_stats()
    records = ROOT / "records"
    previous_path = records / "batch421_merge_aware_attention_result.json"
    previous = json.loads(previous_path.read_text())
    assert previous["state"] == "causal_merge_aware_attention_pilot_scored"
    assert previous["local_minimum_matches"] == MINIMUM_MATCHES and previous["local_ratio"] == [8,1]
    fixture_path = records / "batch419_trained_merger_fixture.json"
    fixture = json.loads(fixture_path.read_text())
    anchor_path = Path(fixture["fixture"]) / f"map_{MINIMUM_MATCHES}.hex"
    original = ALL_ATTENTION_FUNCTIONS["sdpa"]
    manifest_path = ROOT / ".cache/model_reference/vqav2_pilot/manifest.json"
    evaluator, normalizer, evaluator_digests = load_official_sources(ROOT)
    hashes = previous["source_sha256"].copy()
    paths = [Path(__file__), previous_path, fixture_path, anchor_path, manifest_path]
    paths.extend(Path(inspect.getsourcefile(item)) for item in (DynamicCache, original, LlavaModel, LlamaAttention, LlamaDecoderLayer))
    merge_input_digests(hashes, evaluator_digests)
    merge_input_digests(hashes, {str(path):sha256(path) for path in paths})
    assert all(sha256(Path(path)) == digest for path,digest in hashes.items())
    anchor = [int(word,16)&1023 for word in anchor_path.read_text().splitlines()[:IMAGE_TOKENS]]
    samples = json.loads(manifest_path.read_text())["samples"]
    baseline = {case["question_id"]:case["answer_tokens"] for case in previous["cases"]["identity"]}
    assert len(samples) == len(baseline) == 64 and samples[0]["question_id"] == fixture["anchor_question_id"]
    output = records / "batch422_compact_decoder_result.json"
    fixture_dir = ROOT / ".cache/model_reference/batch422"
    assert not output.exists() and not fixture_dir.exists()

    model_dir = ROOT / ".cache/model_reference/tiny_llava_v1"
    tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
    processor = LlavaProcessor(
        image_processor=CLIPImageProcessorPil.from_pretrained(model_dir, local_files_only=True),
        tokenizer=tokenizer, patch_size=14, vision_feature_select_strategy="default", num_additional_image_tokens=1,
    )
    model = LlavaForConditionalGeneration.from_pretrained(
        model_dir, local_files_only=True, dtype=torch.float32, attn_implementation="sdpa", use_kernels=False,
    ).to("cuda").eval()
    executor = CompactDecoder(model, original, tuple(previous["local_ratio"]))
    assert len(executor.language.layers)==22
    generation = model.generation_config
    assert generation.eos_token_id == 2 and generation.num_beams in (None, 1)
    eos = {generation.eos_token_id}
    results = {mode:[] for mode in MODES}
    native_traces = {}
    replay_checks = 0
    ALL_ATTENTION_FUNCTIONS["sdpa"] = executor.attend
    try:
        for index, sample in enumerate(samples):
            check_memory(12*GIB)
            with Image.open(ROOT/sample["image"]) as opened:
                image = opened.convert("RGB")
            prompt = "USER: <image>\n" + sample["question"] + "\nAnswer the question using a single word or phrase.\nASSISTANT:"
            batch = processor(images=image,text=prompt,return_tensors="pt").to("cuda")
            assert bool(batch["attention_mask"].all()) and batch["input_ids"].shape[0]==1
            ids = batch["input_ids"]
            image_positions = (ids[0]==model.config.image_token_id).nonzero().flatten().tolist()
            assert len(image_positions)==IMAGE_TOKENS and image_positions==list(range(image_positions[0],image_positions[0]+IMAGE_TOKENS))
            image_start, prefill = image_positions[0], ids.shape[1]
            embeddings = model.model.get_input_embeddings()(ids)
            image_states = torch.cat(model.model.get_image_features(batch["pixel_values"], return_dict=True).pooler_output,dim=0)
            assert image_states.shape==(IMAGE_TOKENS,FEATURES)
            image_states = image_states.to(embeddings.device,embeddings.dtype)
            embeddings = embeddings.masked_scatter(model.model.get_placeholder_mask(ids,embeddings,image_states), image_states)
            for mode in MODES:
                tokens = executor.generate(embeddings,image_start,mode,eos,anchor if index==0 else None)
                roots, slots = executor.layer_roots.copy(), executor.layer_slots.copy()
                assert all(left>=right for left,right in zip(roots,roots[1:])) and all(
                    count==prefill-IMAGE_TOKENS+survivors for count,survivors in zip(slots,roots,strict=True))
                if mode=="identity":
                    assert tokens==baseline[sample["question_id"]]
                results[mode].append({"question_id":sample["question_id"],"image_id":sample["image_id"],
                    "answer":tokenizer.decode(tokens,skip_special_tokens=True),"answer_tokens":tokens,"prefill_tokens":prefill,
                    "layer_roots":roots,"layer_cache_slots":slots,"streaming_heads":executor.streaming_count,"prefill_kept_pairs":executor.pairs})
                if index==0:
                    if mode!="identity":
                        native_traces[mode] = executor.trace
                    # Teacher replay appends the same first token and recomputes all layers from scratch.
                    executor.prefill(embeddings,image_start,mode,prefill,anchor)
                    token = torch.tensor(tokens[0],device=ids.device)
                    cached = executor.decode(token).clone()
                    extra = model.model.get_input_embeddings()(token.reshape(1,1))
                    replay = executor.prefill(torch.cat((embeddings,extra),dim=1),image_start,mode,prefill,anchor)
                    assert roots==executor.layer_roots
                    torch.testing.assert_close(cached,replay,rtol=2e-4,atol=3e-4)
                    replay_checks += 1
            print(f"BATCH422_CASE case={index} qid={sample['question_id']}",flush=True)
    finally:
        ALL_ATTENTION_FUNCTIONS["sdpa"] = original
    assert replay_checks == len(MODES)
    scores = {mode:score_cases(samples,items,evaluator,normalizer) for mode,items in results.items()}
    assert scores["identity"]==previous["scores"]["identity"]
    totals = {}
    for mode, items in results.items():
        totals[mode] = {"prefill_layer_cache_slots":sum(sum(item["layer_cache_slots"]) for item in items),
                        "prefill_pairs_kept":sum(item["prefill_kept_pairs"] for item in items),
                        "final_image_roots":sum(item["layer_roots"][-1] for item in items),
                        "streaming_heads":sum(item["streaming_heads"] for item in items),
                        "changed_answers":sum(item["answer_tokens"]!=baseline[item["question_id"]] for item in items),
                        "consensus_percent":scores[mode]["official_vqa_consensus_percent_on64"]}
    assert all(sha256(Path(path)) == digest for path,digest in hashes.items())
    assert list(native_traces)==list(MODES[1:]) and all(len(trace)==22 for trace in native_traces.values())
    with tempfile.TemporaryDirectory(dir=fixture_dir.parent,prefix="batch422_build_") as folder:
        staging = Path(folder) / "fixture"
        staging.mkdir()
        for index, trace in enumerate(native_traces.values()):
            with (staging/f"signs_{index}.hex").open("x") as stream:
                stream.writelines(f"{signs.get(position,0):0512x}\n" for signs,_ in trace for position in range(IMAGE_TOKENS))
            with (staging/f"map_{index}.hex").open("x") as stream:
                stream.writelines(f"{origin:03x}\n" for _,origins in trace for origin in origins)
        native_digests = {str(fixture_dir/path.name):sha256(path) for path in sorted(staging.glob("*.hex"))}
        staging.rename(fixture_dir)
    report = {"state":"cumulative_compact_decoder_pilot_scored","scope":__doc__,"questions":len(samples),
              "minimum_matching_signs":MINIMUM_MATCHES,"local_ratio":previous["local_ratio"],
              "merge_refinement":"Existing groups cannot split. Surviving roots compare with the updated representatives of original upper and left cells.",
              "decoder_precision":"floating point except fixed-point head decisions","prefill_compact_query_and_cache":True,
              "original_rotary_positions_preserved":True,"decode_replay_checks":replay_checks,"full_paper_results_matched":False,
              "peak_gpu_bytes":torch.cuda.max_memory_allocated(),"totals":totals,"scores":scores,"cases":results,"source_sha256":hashes,
              "native_fixture":str(fixture_dir),"native_fixture_modes":list(native_traces),"native_fixture_sha256":native_digests}
    with output.open("x") as stream:
        stream.write(json.dumps(report,separators=(",",":"))+"\n")
    print("BATCH422_VERIFIED " + json.dumps(totals,separators=(",",":")),flush=True)


if __name__ == "__main__":
    main()
