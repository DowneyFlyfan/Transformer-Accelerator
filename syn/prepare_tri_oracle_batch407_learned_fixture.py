"""Bind full trained intermediate and output scores for generated activations."""

import json
from pathlib import Path

import numpy as np
import torch

from run_tri_oracle_batch396_masks import GIB, check_memory, sha256
from tri_oracle_integer_reference import _dot, _requantize
from tri_oracle_model_reference import silu_code


ROOT = Path(__file__).resolve().parents[1]
TOKENS, HIDDEN, CHANNELS = 16, 2048, 5632


def byte_codes(path, shape):
    """Read archived two-hex-digit signed bytes with the original tensor shape."""
    text = np.frombuffer(path.read_bytes(), dtype=np.uint8).reshape(-1, 3)
    assert text.shape[0] == int(np.prod(shape)) and np.all(text[:, 2] == 10)
    digits = np.full(256, 255, dtype=np.uint8)
    for value, character in enumerate(b"0123456789abcdef"):
        digits[character] = value
    hi, lo = digits[text[:, 0]], digits[text[:, 1]]
    assert np.all(hi < 16) and np.all(lo < 16)
    return ((hi << 4) | lo).view(np.int8).reshape(shape)


def word_codes(path):
    values = np.array([int(line, 16) for line in path.read_text().splitlines()], dtype=np.uint32)
    return values.view(np.int32).reshape(TOKENS, HIDDEN)


def cpu_round(values, shifts, bits):
    magnitude = np.abs(values)
    rounding = np.where(shifts == 0, 0, np.left_shift(np.ones_like(shifts), np.maximum(0, shifts - 1)))
    rounded = np.right_shift(magnitude + rounding, shifts)
    return np.clip(np.where(values < 0, -rounded, rounded), -2**(bits - 1), 2**(bits - 1) - 1)


@torch.inference_mode()
def main():
    """Use activations [token,hidden], gate/up [channel,hidden], down [hidden,channel].

    Both implementations emit gated bytes [token,channel] and exact output
    accumulations [token,hidden]. Published fixture 403 provides the output
    archive and fixture 389 provides frozen weight, shift, and keep arrays.
    """
    check_memory(12 * GIB)
    assert torch.cuda.mem_get_info()[0] > 10 * GIB
    torch.cuda.set_per_process_memory_fraction(0.50)
    torch.cuda.reset_peak_memory_stats()
    original_path = ROOT / "records/batch389_fixture_preparation.json"
    learned_path = ROOT / "records/batch403_activation_precision.json"
    native_path = ROOT / "records/batch403_native_activation.json"
    masks_path = ROOT / "records/batch396_mask_fixture.json"
    original, learned, native, masks = [
        json.loads(path.read_text()) for path in (original_path, learned_path, native_path, masks_path)
    ]
    assert original["state"] == "complete_trained_layer_fixture_scalar_cuda_equal"
    assert learned["state"] == "trained_fixed_normalization_and_output_effect_characterized"
    assert native["state"] == "trained_native_learned_activation_matches_fixed_point_reference"
    assert native["source_sha256"][str(learned_path)] == sha256(learned_path)
    assert learned["source_sha256"][str(original_path)] == sha256(original_path)
    assert masks["source_sha256"][str(original_path)] == sha256(original_path)
    assert learned["predictor_outlier_and_sign_drift"] == 0
    hashes = original["files_sha256"] | learned["files_sha256"] | masks["files_sha256"] | {
        str(path): sha256(path) for path in (original_path, learned_path, native_path, masks_path, Path(__file__),
            ROOT / "syn/tri_oracle_integer_reference.py", ROOT / "syn/tri_oracle_model_reference.py",
            ROOT / "syn/run_tri_oracle_batch396_masks.py")
    }
    assert all(sha256(Path(path)) == digest for path, digest in hashes.items())
    base = Path(original["fixture"])
    fixed = Path(learned["fixture"])
    activations = [byte_codes(path / "activation.hex", (TOKENS, HIDDEN)) for path in (base, fixed)]
    gate = byte_codes(base / "gate.hex", (CHANNELS, HIDDEN))
    up = byte_codes(base / "up.hex", (CHANNELS, HIDDEN))
    down = byte_codes(base / "down.hex", (HIDDEN, CHANNELS))
    shifts = byte_codes(base / "shifts.hex", (TOKENS, 3)).astype(np.int64)
    assert shifts.tolist() == original["hardware_shifts"]
    keep = byte_codes(base / "keep.hex", (TOKENS, CHANNELS)).astype(bool)
    assert np.count_nonzero(~keep) == original["predicted_skipped_pairs"] == masks["skipped_channels"]
    table = np.array([silu_code(code) for code in range(-32768, 32768)], dtype=np.int64)

    def gpu(array):
        return torch.from_numpy(array).to("cuda")

    gate_gpu, up_gpu, down_gpu, shift_gpu, keep_gpu, table_gpu = map(gpu, (gate, up, down, shifts, keep, table))
    old_intermediate = byte_codes(base / "intermediate.hex", (TOKENS, CHANNELS))
    expected_outputs = [word_codes(path / "expected.hex") for path in (base, fixed)]
    for sample, activation in enumerate(activations):
        activation_gpu = gpu(activation)
        gate_raw = _dot(activation_gpu, gate_gpu)
        up_raw = _dot(activation_gpu, up_gpu)
        gate_q = _requantize(gate_raw, shift_gpu[:, 0:1], 16)
        up_q = _requantize(up_raw, shift_gpu[:, 1:2], 16)
        products = table_gpu[gate_q + 32768] * up_q
        gated = _requantize(products, torch.full((TOKENS, 1), 8, device="cuda", dtype=torch.int64), 16)
        intermediate_gpu = _requantize(gated, shift_gpu[:, 2:3], 8).to(torch.int8).masked_fill(~keep_gpu, 0)
        output_gpu = _dot(intermediate_gpu, down_gpu)
        assert np.array_equal(output_gpu.cpu().numpy(), expected_outputs[sample])
        if sample == 0:
            assert np.array_equal(intermediate_gpu.cpu().numpy(), old_intermediate)
    gate_cpu = activations[1].astype(np.int64) @ gate.astype(np.int64).T
    up_cpu = activations[1].astype(np.int64) @ up.astype(np.int64).T
    assert np.array_equal(gate_cpu, gate_raw.cpu().numpy())
    assert np.array_equal(up_cpu, up_raw.cpu().numpy())
    products = table[cpu_round(gate_cpu, shifts[:, 0:1], 16) + 32768] * cpu_round(up_cpu, shifts[:, 1:2], 16)
    intermediate = cpu_round(cpu_round(products, np.array([[8]], dtype=np.int64), 16), shifts[:, 2:3], 8)
    intermediate = np.where(keep, intermediate, 0).astype(np.int8)
    assert np.array_equal(intermediate, intermediate_gpu.cpu().numpy())
    assert np.array_equal(intermediate.astype(np.int64) @ down.astype(np.int64).T, expected_outputs[1])
    assert all(sha256(Path(path)) == digest for path, digest in hashes.items())
    directory = ROOT / ".cache/model_reference/batch407"
    output = ROOT / "records/batch407_learned_fixture.json"
    assert not output.exists()
    directory.mkdir()
    words = directory / "intermediate.hex"
    with words.open("x") as stream:
        stream.writelines(f"{value & 255:02x}\n" for value in intermediate.flatten().tolist())
    result = {
        "state": "complete_learned_layer_golden_fixed_point_cpu_cuda_equal",
        "scope": __doc__,
        "tokens": TOKENS, "hidden": HIDDEN, "intermediate": CHANNELS,
        "original_checkpoint_layer": 0, "exact_learned_intermediate_bytes": TOKENS * CHANNELS,
        "exact_learned_output_words": TOKENS * HIDDEN,
        "changed_intermediate_bytes_vs_prepared": int(np.count_nonzero(intermediate != old_intermediate)),
        "baseline_intermediate_and_output_archives_matched": True,
        "peak_gpu_bytes": torch.cuda.max_memory_allocated(),
        "fixture": str(directory), "files_sha256": {str(words): sha256(words)},
        "source_sha256": hashes, "joined_hardware_verified": False, "full_paper_results_matched": False,
    }
    output.write_text(json.dumps(result, indent=2) + "\n")
    print("BATCH407_FIXTURE_READY intermediate_bytes=90112 output_words=32768", flush=True)


if __name__ == "__main__":
    main()
