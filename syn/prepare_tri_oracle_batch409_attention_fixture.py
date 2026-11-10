"""Capture trained query/key vectors and score the paper's head-prediction inputs."""

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

from run_tri_oracle_batch396_masks import GIB, check_memory, sha256
from tri_oracle_integer_reference import _dot, _quantize


ROOT = Path(__file__).resolve().parents[1]
HEADS, KEY_HEADS, WIDTH, TILE = 32, 4, 64, 32
ALPHA = 4


def write_codes(path, values, bits):
    with path.open("x") as stream:
        stream.writelines(f"{int(value) & (2**bits-1):0{bits//4}x}\n" for value in values)


@torch.inference_mode()
def main():
    """Capture q[32,T,64], k/v[4,T,64], layer output[T,2048].

    Choose one causal query at each complete tile end. Emit raw integer
    scores[32,R,3,32] for sink, inner, and recent tiles. Both dimensions and
    ratio threshold are local reconstruction choices. The paper depicts
    alpha=4 in scaled score units. No task labels or model fitting are used.
    """
    torch.set_num_threads(4)
    torch.set_num_interop_threads(1)
    check_memory(16 * GIB)
    assert torch.cuda.mem_get_info()[0] > 12 * GIB
    torch.cuda.set_per_process_memory_fraction(0.84)
    torch.cuda.reset_peak_memory_stats()
    cache = ROOT / ".cache/model_reference"
    model_dir = cache / "tiny_llava_v1"
    model_path = ROOT / "records/model_reference_candidate.json"
    model_info = json.loads(model_path.read_text())
    input_path = cache / "ai2d285/inputs.json"
    sample = json.loads(input_path.read_text())["cases"][0]
    image_path = Path(sample["image"])
    assert sha256(image_path) == sample["image_sha256"]
    weights = {ROOT / item["path"]: item["sha256"] for item in model_info["verified_weights"]}
    assert all(sha256(path) == digest for path, digest in weights.items())
    paper, = (ROOT / "Paper").glob("Tri-Oracle - A 17.78*.pdf")
    metadata = [model_path, input_path, image_path, paper, Path(__file__),
                ROOT / "syn/tri_oracle_integer_reference.py", ROOT / "syn/run_tri_oracle_batch396_masks.py"]
    metadata.extend(path for path in sorted(model_dir.iterdir()) if path.is_file() and path not in weights)
    fingerprints = {str(path): sha256(path) for path in metadata} | {str(path): digest for path, digest in weights.items()}

    tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
    processor = LlavaProcessor(
        image_processor=CLIPImageProcessorPil.from_pretrained(model_dir, local_files_only=True),
        tokenizer=tokenizer, patch_size=14, vision_feature_select_strategy="default", num_additional_image_tokens=1,
    )
    model = LlavaForConditionalGeneration.from_pretrained(
        model_dir, local_files_only=True, dtype=torch.float32, attn_implementation="sdpa", use_kernels=False,
    ).to("cuda").eval()
    attention = model.model.language_model.layers[0].self_attn
    capture = {}

    def before(module, args, kwargs):
        """Read the actual projection input[1,T,2048] and rotary cos/sin[1,T,64]."""
        hidden = args[0] if args else kwargs["hidden_states"]
        q = module.q_proj(hidden).view(1, -1, HEADS, WIDTH).transpose(1, 2)
        k = module.k_proj(hidden).view(1, -1, KEY_HEADS, WIDTH).transpose(1, 2)
        v = module.v_proj(hidden).view(1, -1, KEY_HEADS, WIDTH).transpose(1, 2)
        q, k = apply_rotary_pos_emb(q, k, *kwargs["position_embeddings"])
        capture.update(query=q[0], key=k[0], value=v[0])

    def after(_module, _args, output):
        """Save the actual output projection[1,T,2048] from the original layer."""
        capture["output"] = output[0][0]

    handles = [attention.register_forward_pre_hook(before, with_kwargs=True),
               attention.register_forward_hook(after)]
    try:
        with Image.open(image_path) as opened:
            image = opened.convert("RGB")
            prompt = "USER: <image>\n" + sample["question"] + "\nAnswer briefly.\nASSISTANT:"
            batch = processor(images=image, text=prompt, return_tensors="pt").to("cuda")
        logits = model(**batch, use_cache=False, logits_to_keep=1).logits
        assert logits.shape == (1, 1, 32064) and bool(torch.isfinite(logits).all())
    finally:
        for handle in handles:
            handle.remove()

    q, k, v = (capture[name] for name in ("query", "key", "value"))
    sequence = q.shape[1]
    assert q.shape == (HEADS, sequence, WIDTH) and k.shape == v.shape == (KEY_HEADS, sequence, WIDTH)
    blocks = list(range(3, sequence // TILE))
    positions = [(block + 1) * TILE - 1 for block in blocks]
    rows = len(positions)
    assert rows > 10 and attention.scaling == 1 / math.sqrt(WIDTH)
    selected = torch.tensor(positions, device="cuda")
    tile_indices = torch.tensor([
        [list(range(start, start + TILE)) for start in (0, (block - 2) * TILE, block * TILE)]
        for block in blocks
    ], device="cuda")
    assert bool((tile_indices <= selected[:, None, None]).all())
    allowed = torch.arange(sequence, device="cuda")[None, :] <= selected[:, None]
    q_codes, k_codes, counts, scores, alphas, predictions, float_predictions = [], [], [], [], [], [], []
    attended = []
    key_quantized = [_quantize(head) for head in k]
    k_codes.extend(codes.cpu().numpy() for codes, _ in key_quantized)
    for head in range(HEADS):
        key_head = head // (HEADS // KEY_HEADS)
        codes, q_exponent = _quantize(q[head])
        keys, k_exponent = key_quantized[key_head]
        selected_codes = codes[selected]
        padded_keys = torch.nn.functional.pad(keys, (0, 0, 0, (-sequence) % 16))
        raw = _dot(selected_codes, padded_keys)[:, :sequence]
        scalar = selected_codes.cpu().numpy().astype(np.int64) @ keys.cpu().numpy().astype(np.int64).T
        assert np.array_equal(scalar, raw.cpu().numpy())
        fixed_tiles = raw[torch.arange(rows, device="cuda")[:, None, None], tile_indices]
        score_scale = math.ldexp(attention.scaling, int(q_exponent) + int(k_exponent))
        alpha_units = ALPHA / score_scale
        assert alpha_units == int(alpha_units) and 0 < alpha_units < 2**31
        cutoff = fixed_tiles[:, 0].amax(dim=-1, keepdim=True) - int(alpha_units)
        fixed_count = (fixed_tiles[:, 1:] > cutoff[:, None, :]).sum(dim=-1)

        floating = (q[head, selected] @ k[key_head].T) * attention.scaling
        float_tiles = floating[torch.arange(rows, device="cuda")[:, None, None], tile_indices]
        float_cutoff = float_tiles[:, 0].amax(dim=-1, keepdim=True) - ALPHA
        float_count = (float_tiles[:, 1:] > float_cutoff[:, None, :]).sum(dim=-1)
        attended.append(torch.softmax(floating.masked_fill(~allowed, -torch.inf), dim=-1) @ v[key_head])
        q_codes.append(selected_codes.cpu().numpy())
        scores.append(fixed_tiles.cpu().numpy())
        counts.append(fixed_count.cpu().numpy())
        alphas.append(int(alpha_units))
        predictions.append(bool(fixed_count[:, 1].sum() > fixed_count[:, 0].sum()))
        float_predictions.append(bool(float_count[:, 1].sum() > float_count[:, 0].sum()))
    reconstructed = attention.o_proj(torch.stack(attended, dim=1).reshape(rows, HEADS * WIDTH))
    actual = capture["output"][selected]
    torch.testing.assert_close(reconstructed, actual, rtol=1e-4, atol=1e-5)
    assert all(sha256(Path(path)) == digest for path, digest in fingerprints.items())
    directory = cache / "batch409"
    output = ROOT / "records/batch409_attention_fixture.json"
    assert not output.exists()
    directory.mkdir()
    for name, values, bits in (
        ("query", q_codes, 8), ("key", k_codes, 8), ("scores", scores, 32),
        ("alpha", alphas, 32), ("counts", counts, 8), ("streaming", predictions, 8),
    ):
        write_codes(directory / f"{name}.hex", np.asarray(values).flatten(), bits)
    report = {
        "state": "trained_rotary_attention_fixture_cpu_cuda_equal",
        "scope": __doc__, "sequence_tokens": sequence, "query_heads": HEADS, "key_value_heads": KEY_HEADS,
        "head_features": WIDTH, "tile_keys": TILE, "query_positions": positions,
        "tile_positions": tile_indices.tolist(), "checkpoint_revision": model_info["revision"],
        "alpha_scaled_score_units": ALPHA, "integer_alpha_by_head": alphas, "local_ratio_threshold": 1,
        "scalar_cuda_score_comparisons": HEADS * rows * sequence,
        "exact_precomputed_tile_scores": HEADS * rows * 3 * TILE,
        "fixed_streaming_heads": sum(predictions), "float_streaming_heads": sum(float_predictions),
        "head_class_changes_after_quantization": sum(a != b for a, b in zip(predictions, float_predictions)),
        "dense_attention_output_max_abs_delta": float((reconstructed - actual).abs().max()),
        "peak_gpu_bytes": torch.cuda.max_memory_allocated(), "source_sha256": fingerprints,
        "fixture": str(directory), "files_sha256": {str(path): sha256(path) for path in sorted(directory.glob("*.hex"))},
        "hardware_attention_verified": False, "full_paper_results_matched": False,
    }
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"BATCH409_ATTENTION_FIXTURE rows={rows} heads={HEADS} tile_scores={report['exact_precomputed_tile_scores']}", flush=True)


if __name__ == "__main__":
    main()
