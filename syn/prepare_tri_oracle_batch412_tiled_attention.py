"""Build a causal reference for all rows of the selected head-prediction tiles."""

import json
import math
import os
from pathlib import Path
import tempfile

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import numpy as np
import torch
from PIL import Image
from transformers import AutoTokenizer, LlavaForConditionalGeneration, LlavaProcessor
from transformers.models.clip.image_processing_pil_clip import CLIPImageProcessorPil
from transformers.models.llama.modeling_llama import apply_rotary_pos_emb

from prepare_tri_oracle_batch409_attention_fixture import ALPHA, HEADS, KEY_HEADS, ROOT, TILE, WIDTH, write_codes
from run_tri_oracle_batch396_masks import GIB, check_memory, sha256
from tri_oracle_integer_reference import _dot, _quantize


@torch.inference_mode()
def capture_query_and_key(cache):
    """Return first-layer rotary queries [query head, token, feature], keys
    [key head, token, feature], and the checkpoint's scalar score scale.
    """
    model_dir = cache / "tiny_llava_v1"
    sample = json.loads((cache / "ai2d285/inputs.json").read_text())["cases"][0]
    tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
    processor = LlavaProcessor(
        image_processor=CLIPImageProcessorPil.from_pretrained(model_dir, local_files_only=True),
        tokenizer=tokenizer, patch_size=14, vision_feature_select_strategy="default", num_additional_image_tokens=1,
    )
    model = LlavaForConditionalGeneration.from_pretrained(
        model_dir, local_files_only=True, dtype=torch.float32, attn_implementation="sdpa", use_kernels=False,
    ).to("cuda").eval()
    attention = model.model.language_model.layers[0].self_attn
    captured = {}

    def before(module, args, kwargs):
        """Project trained hidden [1, token, hidden] into query/key heads.
        The checkpoint's position pair has shape [1, token, feature] each.
        """
        hidden = args[0] if args else kwargs["hidden_states"]
        query = module.q_proj(hidden).reshape(1, -1, HEADS, WIDTH).transpose(1, 2)
        key = module.k_proj(hidden).reshape(1, -1, KEY_HEADS, WIDTH).transpose(1, 2)
        query, key = apply_rotary_pos_emb(query, key, *kwargs["position_embeddings"])
        captured.update(query=query[0], key=key[0])

    handle = attention.register_forward_pre_hook(before, with_kwargs=True)
    try:
        with Image.open(sample["image"]) as opened:
            image = opened.convert("RGB")
        prompt = "USER: <image>\n" + sample["question"] + "\nAnswer briefly.\nASSISTANT:"
        inputs = processor(images=image, text=prompt, return_tensors="pt").to("cuda")
        # One final vocabulary row [batch=1, token=1, vocabulary] confirms the forward completed.
        logits = model(**inputs, use_cache=False, logits_to_keep=1).logits
        assert logits.shape == (1, 1, 32064) and bool(torch.isfinite(logits).all())
    finally:
        handle.remove()
    return captured["query"], captured["key"], attention.scaling


def read_codes(path, dtype, shape):
    """Read frozen hexadecimal codes using caller-provided semantic axes."""
    if dtype == np.int8:
        return np.frombuffer(bytes.fromhex(path.read_text()), dtype=np.int8).reshape(shape)
    return np.array([int(line, 16) for line in path.read_text().splitlines()], dtype=np.uint32).view(dtype).reshape(shape)


@torch.inference_mode()
def main():
    torch.set_num_threads(4)
    torch.set_num_interop_threads(1)
    check_memory(16 * GIB)
    assert torch.cuda.mem_get_info()[0] > 12 * GIB
    torch.cuda.set_per_process_memory_fraction(0.84)
    torch.cuda.reset_peak_memory_stats()
    prior_path = ROOT / "records/batch409_attention_fixture.json"
    prior = json.loads(prior_path.read_text())
    assert prior["state"] == "trained_rotary_attention_fixture_cpu_cuda_equal"
    assert (prior["query_heads"], prior["key_value_heads"], prior["head_features"], prior["tile_keys"],
            prior["alpha_scaled_score_units"], prior["local_ratio_threshold"]) == (HEADS, KEY_HEADS, WIDTH, TILE, ALPHA, 1)
    hashes = prior["source_sha256"] | prior["files_sha256"] | {str(path): sha256(path) for path in (prior_path, Path(__file__))}
    assert all(sha256(Path(path)) == digest for path, digest in hashes.items())
    cache = ROOT / ".cache/model_reference"
    destination = cache / "batch412"
    output = ROOT / "records/batch412_tiled_attention_fixture.json"
    assert not destination.exists() and not output.exists()
    query, key, scale = capture_query_and_key(cache)
    sequence = prior["sequence_tokens"]
    assert query.shape == (HEADS, sequence, WIDTH) and key.shape == (KEY_HEADS, sequence, WIDTH)
    assert scale == 1 / math.sqrt(WIDTH)

    # Positions [query row] start once sink, inner, and recent tiles are distinct.
    # Tile starts [query row, region]; key indices and masks [query row, region, lane].
    first = 3 * TILE
    positions = np.arange(first, sequence)
    rows = len(positions)
    block_start = (positions // TILE) * TILE
    starts = np.stack((np.zeros_like(positions), block_start - 2*TILE, block_start), axis=1)
    indices = starts[:, :, None] + np.arange(TILE)[None, None, :]
    live = indices <= positions[:, None, None]
    assert np.all(live[:, :2]) and np.all(indices[live] < sequence)
    safe_indices = np.where(live, indices, 0)
    old_rows = np.array(prior["query_positions"]) - first
    assert indices[old_rows].tolist() == prior["tile_positions"] and np.all(live[old_rows])
    old_fixture = Path(prior["fixture"])
    old_query = read_codes(old_fixture / "query.hex", np.int8, (HEADS, len(old_rows), WIDTH))
    old_key = read_codes(old_fixture / "key.hex", np.int8, (KEY_HEADS, sequence, WIDTH))
    old_scores = read_codes(old_fixture / "scores.hex", np.int32, (HEADS, len(old_rows), 3, TILE))
    old_counts = read_codes(old_fixture / "counts.hex", np.int8, (HEADS, len(old_rows), 2))
    quantized_keys = [_quantize(head) for head in key]
    key_codes = np.stack([codes.cpu().numpy() for codes, _ in quantized_keys])
    np.testing.assert_array_equal(key_codes, old_key)

    # Per-head query bytes [row, feature], scores [row, region, lane], counts [row, region-1].
    # Fixed and floating head types are scalar decisions from summed counts.
    query_codes, score_codes, counts, fixed_types, float_types = [], [], [], [], []
    row_ids = np.arange(rows)[:, None, None]
    gpu_rows = torch.from_numpy(row_ids).to("cuda")
    gpu_indices = torch.from_numpy(safe_indices).to("cuda")
    gpu_live = torch.from_numpy(live).to("cuda")
    for head in range(HEADS):
        key_head = head // (HEADS // KEY_HEADS)
        quantized_query, query_exponent = _quantize(query[head])
        quantized_query = quantized_query[first:]
        quantized_key, key_exponent = quantized_keys[key_head]
        alpha = ALPHA / math.ldexp(scale, int(query_exponent) + int(key_exponent))
        assert alpha == prior["integer_alpha_by_head"][head]
        query_cpu = quantized_query.cpu().numpy()
        np.testing.assert_array_equal(query_cpu[old_rows], old_query[head])
        # Both dense products [row, key token] independently select and mask the same tiles.
        cpu_dense = query_cpu.astype(np.int64) @ key_codes[key_head].astype(np.int64).T
        padded_key = torch.nn.functional.pad(quantized_key, (0, 0, 0, (-sequence) % 16))
        gpu_dense = _dot(quantized_query, padded_key)[:, :sequence]
        np.testing.assert_array_equal(cpu_dense, gpu_dense.cpu().numpy())
        tile_scores = np.where(live, cpu_dense[row_ids, safe_indices], 0)
        gpu_tiles = gpu_dense[gpu_rows, gpu_indices].masked_fill(~gpu_live, 0)
        np.testing.assert_array_equal(tile_scores, gpu_tiles.cpu().numpy())
        cutoff = tile_scores[:, 0].max(axis=1)[:, None, None] - int(alpha)
        hits = ((tile_scores[:, 1:] > cutoff) & live[:, 1:]).sum(axis=2)
        gpu_cutoff = gpu_tiles[:, 0].amax(dim=1)[:, None, None] - int(alpha)
        gpu_hits = ((gpu_tiles[:, 1:] > gpu_cutoff) & gpu_live[:, 1:]).sum(dim=2)
        np.testing.assert_array_equal(hits, gpu_hits.cpu().numpy())
        np.testing.assert_array_equal(tile_scores[old_rows], old_scores[head])
        np.testing.assert_array_equal(hits[old_rows], old_counts[head])

        # The trained floating-point counterfactual uses identical causal tiles and ratio.
        floating = ((query[head, first:] @ key[key_head].T) * scale)[gpu_rows, gpu_indices]
        float_cutoff = floating[:, 0].amax(dim=1)[:, None, None] - ALPHA
        float_inner, float_recent = ((floating[:, 1:] > float_cutoff) & gpu_live[:, 1:]).sum(dim=(0, 2)).tolist()
        inner, recent = hits.sum(axis=0)
        fixed_types.append(bool(recent > inner))
        float_types.append(float_recent > float_inner)
        query_codes.append(query_cpu)
        score_codes.append(tile_scores)
        counts.append(hits)

    batches = [{"query_first": start, "queries": min(16, sequence-start),
                "key_starts": starts[start-first].tolist()}
               for start in range(first, sequence, 16)]
    assert all(np.array_equal(starts[entry["query_first"]-first:entry["query_first"]-first+entry["queries"]],
                              np.broadcast_to(entry["key_starts"], (entry["queries"], 3))) for entry in batches)
    assert sum(entry["queries"] for entry in batches) == rows
    assert all(sha256(Path(path)) == digest for path, digest in hashes.items())
    with tempfile.TemporaryDirectory(dir=cache, prefix="batch412_build_") as work:
        staging = Path(work) / "fixture"
        staging.mkdir()
        for name, values, bits in (
            ("query", query_codes, 8), ("key", key_codes, 8), ("scores", score_codes, 32),
            ("alpha", prior["integer_alpha_by_head"], 32), ("counts", counts, 8), ("streaming", fixed_types, 8),
        ):
            write_codes(staging / f"{name}.hex", np.asarray(values).flatten(), bits)
        fixture_hashes = {str(destination / path.name): sha256(path) for path in sorted(staging.glob("*.hex"))}
        staging.rename(destination)
    result = {
        "state": "trained_causal_tile_rows_cpu_cuda_equal", "scope": __doc__, "checkpoint_revision": prior["checkpoint_revision"],
        "sequence_tokens": sequence, "query_heads": HEADS, "key_value_heads": KEY_HEADS, "head_features": WIDTH,
        "first_query_position": first, "queries_per_head": rows, "tile_keys": TILE, "batches": batches,
        "local_ratio_threshold": 1, "alpha_scaled_score_units": ALPHA,
        "cpu_cuda_dense_score_comparisons": HEADS * rows * sequence,
        "selected_causal_scores": HEADS * int(np.count_nonzero(live)),
        "masked_score_slots": HEADS * int(np.count_nonzero(~live)), "intensity_comparisons": HEADS * rows * 2,
        "frozen_sampled_scores_reproduced": prior["exact_precomputed_tile_scores"],
        "fixed_streaming_heads": sum(fixed_types), "float_streaming_heads": sum(float_types),
        "head_class_changes_after_quantization": sum(a != b for a, b in zip(fixed_types, float_types)),
        "fixed_types_by_head": fixed_types, "float_types_by_head": float_types,
        "peak_gpu_bytes": torch.cuda.max_memory_allocated(), "source_sha256": hashes,
        "fixture": str(destination), "files_sha256": fixture_hashes,
        "hardware_tiled_attention_verified": False, "full_paper_results_matched": False,
    }
    with output.open("x") as stream:
        stream.write(json.dumps(result, indent=2) + "\n")
    print(f"BATCH412_FIXTURE_READY rows={rows} heads={HEADS} causal_scores={result['selected_causal_scores']}", flush=True)


if __name__ == "__main__":
    main()
