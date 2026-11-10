"""Measure the frozen head-prediction policy across the pinned language model."""

import json
import math
import os
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import numpy as np
import torch
from PIL import Image
from transformers import AutoTokenizer, LlavaForConditionalGeneration, LlavaProcessor
from transformers.models.clip.image_processing_pil_clip import CLIPImageProcessorPil
from transformers.models.llama.modeling_llama import apply_rotary_pos_emb

from prepare_tri_oracle_batch409_attention_fixture import ALPHA, HEADS, KEY_HEADS, ROOT, TILE, WIDTH
from run_tri_oracle_batch396_masks import GIB, check_memory, sha256
from tri_oracle_integer_reference import _dot, _quantize


def causal_geometry(sequence):
    """Build key indices and validity [query row, tile, key lane]."""
    positions = np.arange(3*TILE, sequence)
    blocks = positions // TILE * TILE
    starts = np.stack((np.zeros_like(blocks), blocks - 2*TILE, blocks), axis=1)
    indices = starts[:, :, None] + np.arange(TILE)[None, None, :]
    live = indices <= positions[:, None, None]
    assert np.all(live[:, :2]) and np.all(indices[live] < sequence)
    return positions, indices, live


def classify_layer(query, key, scale, geometry, verify_cpu):
    """Score trained query [head, token, feature] and key [key head, token, feature].

    Dense scores have axes [head, query row, key token]. The selected scores
    have axes [head, query row, tile, key lane], and counts retain the inner
    and recent tile totals separately. Quantization scales are scalar per head.
    """
    positions, indices, live = geometry
    sequence = query.shape[1]
    assert query.shape == (HEADS, sequence, WIDTH) and key.shape == (KEY_HEADS, sequence, WIDTH)
    assert scale == 1 / math.sqrt(WIDTH)
    row_start = int(positions[0])
    rows = torch.arange(len(positions), device="cuda")[:, None, None]
    gather = torch.from_numpy(np.where(live, indices, 0)).to("cuda")
    mask = torch.from_numpy(live).to("cuda")
    key_codes = [_quantize(key_head) for key_head in key]
    padded = [torch.nn.functional.pad(codes, (0, 0, 0, (-sequence) % 16)) for codes, _ in key_codes]
    reference_counts = []
    fixed_totals, float_totals = [], []
    for head in range(HEADS):
        group = head // (HEADS // KEY_HEADS)
        query_code, query_exponent = _quantize(query[head])
        query_code = query_code[row_start:]
        scale_code = math.ldexp(scale, int(query_exponent) + int(key_codes[group][1]))
        integer_alpha = ALPHA / scale_code
        assert integer_alpha == int(integer_alpha) and 0 < integer_alpha < 2**31

        # Compute the selected tiles from independent integer and floating point products.
        integer_dense = _dot(query_code, padded[group])[:, :sequence]
        fixed = integer_dense[rows, gather].masked_fill(~mask, 0)
        floating = ((query[head, row_start:] @ key[group].T) * scale)[rows, gather]
        fixed_cutoff = fixed[:, 0].amax(dim=1)[:, None, None] - int(integer_alpha)
        float_cutoff = floating[:, 0].amax(dim=1)[:, None, None] - ALPHA
        fixed_counts = ((fixed[:, 1:] > fixed_cutoff) & mask[:, 1:]).sum(dim=2)
        float_counts = ((floating[:, 1:] > float_cutoff) & mask[:, 1:]).sum(dim=2)
        fixed_totals.append(fixed_counts.sum(dim=0))
        float_totals.append(float_counts.sum(dim=0))

        if verify_cpu:
            # Use one integer product per tile and truncate by causality independently.
            query_cpu = query_code.cpu().numpy().astype(np.int32)
            key_cpu = key_codes[group][0].cpu().numpy().astype(np.int32)
            expected = np.zeros((len(positions), 3, TILE), dtype=np.int32)
            for start in range(0, len(positions), TILE):
                end = min(start+TILE, len(positions))
                for region in range(3):
                    keys = indices[start, region]
                    available = int(np.count_nonzero(keys < sequence))
                    expected[start:end, region, :available] = query_cpu[start:end] @ key_cpu[keys[:available]].T
            expected = np.where(live, expected, 0)
            np.testing.assert_array_equal(expected, fixed.cpu().numpy())
            cutoff = expected[:, 0].max(axis=1)[:, None, None] - int(integer_alpha)
            counts = ((expected[:, 1:] > cutoff) & live[:, 1:]).sum(axis=2)
            np.testing.assert_array_equal(counts, fixed_counts.cpu().numpy())
            reference_counts.append(counts)

    # Columns in each total are [inner, recent]. A ratio of one uses strict comparison.
    fixed_cpu = torch.stack(fixed_totals).cpu().numpy()
    float_cpu = torch.stack(float_totals).cpu().numpy()
    fixed_streaming = fixed_cpu[:, 1] > fixed_cpu[:, 0]
    float_streaming = float_cpu[:, 1] > float_cpu[:, 0]
    result = {
        "fixed_inner_recent": fixed_cpu.tolist(), "float_inner_recent": float_cpu.tolist(),
        "fixed_streaming": int(fixed_streaming.sum()), "float_streaming": int(float_streaming.sum()),
        "changed_head_ids": np.flatnonzero(fixed_streaming != float_streaming).tolist(),
    }
    return result, reference_counts


@torch.inference_mode()
def main():
    torch.set_num_threads(3)
    torch.set_num_interop_threads(1)
    check_memory(16 * GIB)
    assert torch.cuda.mem_get_info()[0] > 12 * GIB
    torch.cuda.set_per_process_memory_fraction(0.84)
    torch.cuda.reset_peak_memory_stats()
    prior_path = ROOT / "records/batch412_tiled_attention_fixture.json"
    prior = json.loads(prior_path.read_text())
    assert prior["state"] == "trained_causal_tile_rows_cpu_cuda_equal"
    assert prior["local_ratio_threshold"] == 1 and prior["alpha_scaled_score_units"] == ALPHA
    output = ROOT / "records/batch414_head_policy_result.json"
    assert not output.exists()
    cache = ROOT / ".cache/model_reference"
    manifest = cache / "ai2d285/inputs.json"
    samples = json.loads(manifest.read_text())["cases"]
    assert len(samples) == 16 and len({sample["global_row"] for sample in samples}) == len(samples)
    hashes = prior["source_sha256"] | prior["files_sha256"] | {str(p): sha256(p) for p in (prior_path, Path(__file__))}
    hashes |= {sample["image"]: sample["image_sha256"] for sample in samples}
    assert all(sha256(Path(path)) == digest for path, digest in hashes.items())

    model_dir = cache / "tiny_llava_v1"
    tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
    processor = LlavaProcessor(
        image_processor=CLIPImageProcessorPil.from_pretrained(model_dir, local_files_only=True),
        tokenizer=tokenizer, patch_size=14, vision_feature_select_strategy="default", num_additional_image_tokens=1,
    )
    model = LlavaForConditionalGeneration.from_pretrained(
        model_dir, local_files_only=True, dtype=torch.float32, attn_implementation="sdpa", use_kernels=False,
    ).to("cuda").eval()
    layers = model.model.language_model.layers
    assert len(layers) == 22
    captured = {}

    def hook(layer_index):
        def before(module, args, kwargs):
            """Capture projections from hidden [1, token, hidden] after rotation."""
            hidden = args[0] if args else kwargs["hidden_states"]
            query = module.q_proj(hidden).reshape(1, -1, HEADS, WIDTH).transpose(1, 2)
            key = module.k_proj(hidden).reshape(1, -1, KEY_HEADS, WIDTH).transpose(1, 2)
            query, key = apply_rotary_pos_emb(query, key, *kwargs["position_embeddings"])
            assert layer_index not in captured
            captured[layer_index] = (query[0], key[0], module.scaling)
        return before

    handles = [layer.self_attn.register_forward_pre_hook(hook(index), with_kwargs=True)
               for index, layer in enumerate(layers)]
    cases = []
    checked_cpu_scores = 0
    try:
        for case_index, sample in enumerate(samples):
            check_memory(12 * GIB)
            with Image.open(sample["image"]) as opened:
                image = opened.convert("RGB")
            prompt = "USER: <image>\n" + sample["question"] + "\nAnswer briefly.\nASSISTANT:"
            inputs = processor(images=image, text=prompt, return_tensors="pt").to("cuda")
            logits = model(**inputs, use_cache=False, logits_to_keep=1).logits
            assert logits.shape == (1, 1, 32064) and bool(torch.isfinite(logits).all())
            assert set(captured) == set(range(len(layers)))
            sequence = captured[0][0].shape[1]
            geometry = causal_geometry(sequence)
            layer_results = []
            for layer_index in range(len(layers)):
                layer_result, reference_counts = classify_layer(*captured.pop(layer_index), geometry, case_index == 0)
                layer_results.append(layer_result)
                if case_index == 0:
                    checked_cpu_scores += HEADS * int(np.count_nonzero(geometry[2]))
                    if layer_index == 0:
                        assert sequence == prior["sequence_tokens"]
                        assert layer_result["fixed_streaming"] == prior["fixed_streaming_heads"]
                        assert layer_result["float_streaming"] == prior["float_streaming_heads"]
                        frozen = Path(prior["fixture"]) / "counts.hex"
                        frozen_counts = np.frombuffer(bytes.fromhex(frozen.read_text()), dtype=np.uint8)
                        np.testing.assert_array_equal(np.asarray(reference_counts).flatten(), frozen_counts)
            case = {
                "manifest_index": case_index, "global_row": sample["global_row"], "prefill_tokens": sequence,
                "selected_queries_per_head": len(geometry[0]),
                "fixed_streaming": sum(layer["fixed_streaming"] for layer in layer_results),
                "float_streaming": sum(layer["float_streaming"] for layer in layer_results),
                "changed_decisions": sum(len(layer["changed_head_ids"]) for layer in layer_results),
                "layers": layer_results,
            }
            cases.append(case)
            print(f"BATCH414_CASE case={case_index} tokens={sequence} fixed={case['fixed_streaming']} "
                  f"float={case['float_streaming']} changed={case['changed_decisions']}", flush=True)
    finally:
        for handle in handles:
            handle.remove()

    assert all(sha256(Path(path)) == digest for path, digest in hashes.items())
    # Keep the full per-head counts local. Track compact layer/case statistics and their source identities.
    details = ROOT / ".cache/model_reference/batch414_head_policy_details.json"
    with details.open("x") as stream:
        json.dump(cases, stream, separators=(",", ":"))
    summary_cases = [{key: value for key, value in case.items() if key != "layers"} | {
        "layer_fixed_streaming": [layer["fixed_streaming"] for layer in case["layers"]],
        "layer_float_streaming": [layer["float_streaming"] for layer in case["layers"]],
        "layer_changed_decisions": [len(layer["changed_head_ids"]) for layer in case["layers"]],
    } for case in cases]
    evaluated = len(cases) * len(layers) * HEADS
    fixed = sum(case["fixed_streaming"] for case in cases)
    floating = sum(case["float_streaming"] for case in cases)
    changed = sum(case["changed_decisions"] for case in cases)
    result = {
        "state": "frozen_head_policy_measured_across_pinned_model", "scope": __doc__,
        "checkpoint_revision": prior["checkpoint_revision"], "images": len(cases), "layers_per_image": len(layers),
        "heads_per_layer": HEADS, "head_decisions": evaluated, "fixed_streaming": fixed,
        "float_streaming": floating, "changed_decisions": changed, "fixed_streaming_fraction": fixed/evaluated,
        "float_streaming_fraction": floating/evaluated, "anchor_cpu_verified_selected_scores": checked_cpu_scores,
        "anchor_frozen_counts_reproduced": HEADS * prior["queries_per_head"] * 2,
        "local_ratio_threshold": 1, "alpha_scaled_score_units": ALPHA, "tile_keys": TILE,
        "runtime_token_merging_applied": False, "task_accuracy_measured": False, "full_paper_results_matched": False,
        "peak_gpu_bytes": torch.cuda.max_memory_allocated(), "cases": summary_cases,
        "local_details": str(details), "local_details_sha256": sha256(details), "source_sha256": hashes,
    }
    with output.open("x") as stream:
        stream.write(json.dumps(result, indent=2) + "\n")
    print(f"BATCH414_VERIFIED decisions={evaluated} fixed={fixed} float={floating} changed={changed}", flush=True)


if __name__ == "__main__":
    main()
