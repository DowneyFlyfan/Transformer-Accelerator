"""Prepare raw residuals and sign planes for the existing hardware predictor.

Use the same first sixteen captured rows and quantized weight matrices as
batch 389. Verify that signed 16-bit residual quantization preserves every
outlier decision, then compare independently reconstructed masks to batch 389.
"""

import hashlib
import json
from pathlib import Path

import numpy as np
import torch


ROOT = Path(__file__).resolve().parents[1]
TOKENS = 16
FEATURES = 2048
CHANNELS = 5632
GROUPS = CHANNELS // 32
FRACTION_BITS = 13


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_words(path, words, digits):
    with path.open("x") as stream:
        stream.writelines(f"{int(word):0{digits}x}\n" for word in words)


def pack_bits(bits):
    return int.from_bytes(np.packbits(bits, bitorder="little").tobytes(), "little")


def main():
    """Residual/codes/outliers are [token,feature], weights are [channel,feature].

    Each plane packs [group,feature_pair,half,channel_in_group] into 64-bit
    words. Branch masks are [token,group] and use the original channel order.
    """
    torch.set_num_threads(4)
    torch.set_num_interop_threads(1)
    reference_path = ROOT / "records/batch389_fixture_preparation.json"
    reference = json.loads(reference_path.read_text())
    assert reference["state"] == "complete_trained_layer_fixture_scalar_cuda_equal"
    assert (reference["tokens"], reference["input_features"], reference["intermediate_features"]) == (
        TOKENS, FEATURES, CHANNELS
    )
    captured = ROOT / ".cache/model_reference/format320/captured_rows.pt"
    config = ROOT / ".cache/model_reference/tiny_llava_v1/config.json"
    fixture = Path(reference["fixture"])
    inputs = {str(path): sha256(path) for path in (
        Path(__file__), reference_path, captured, config,
        fixture / "gate.hex", fixture / "up.hex", fixture / "keep.hex",
    )}
    for path in (captured, config):
        assert inputs[str(path)] == reference["source_sha256"][str(path)]
    for name in ("gate", "up", "keep"):
        key = str(fixture / f"{name}.hex")
        assert inputs[key] == reference["files_sha256"][key]

    residual = torch.load(captured, map_location="cpu", weights_only=True)[0]["residual"][:TOKENS].double().numpy()
    assert residual.shape == (TOKENS, FEATURES)
    epsilon = json.loads(config.read_text())["text_config"]["rms_norm_eps"]
    scale = 2 ** FRACTION_BITS
    raw = (np.sign(residual) * np.floor(np.abs(residual) * scale + 0.5)).astype(np.int64)
    epsilon_q16 = int(epsilon * scale * scale * 65536 + 0.5)
    assert raw.min() >= -32768 and raw.max() <= 32767 and 0 < epsilon_q16 < 2**32

    # Round-half-up signed normalized magnitudes cross 768 at 768.5.
    # Integer arithmetic can compare the squared magnitudes without a quotient.
    exact_outliers = np.abs(residual) * 256 >= 768.5 * np.sqrt(
        np.mean(residual**2, axis=1, keepdims=True) + epsilon
    )
    energy = np.sum(raw**2, axis=1).tolist()
    quantized_outliers = np.array([
        [int(value)**2 * FEATURES * 2**34 >= 1537**2 * (total * 65536 + FEATURES * epsilon_q16)
         for value in row]
        for row, total in zip(raw, energy)
    ])
    assert np.array_equal(exact_outliers, quantized_outliers)
    assert np.array_equal(raw[exact_outliers] < 0, residual[exact_outliers] < 0)

    negative_weights = []
    planes = []
    for name in ("gate", "up"):
        # A high hexadecimal nibble of 8 through f denotes a negative signed byte.
        source = np.frombuffer((fixture / f"{name}.hex").read_bytes(), dtype=np.uint8)
        assert source.size == CHANNELS * FEATURES * 3
        negative = (source[::3] >= ord("8")).reshape(CHANNELS, FEATURES)
        negative_weights.append(negative)
        pairs = negative.reshape(GROUPS, 32, FEATURES // 2, 2).transpose(0, 2, 3, 1)
        planes.append(np.packbits(pairs.reshape(-1, 64), axis=1, bitorder="little").view("<u8").ravel())

    archived_keep = np.frombuffer((fixture / "keep.hex").read_bytes(), dtype=np.uint8)[1::3]
    assert set(archived_keep) == {ord("0"), ord("1")}
    archived_skip = (archived_keep == ord("0")).reshape(TOKENS, CHANNELS)
    branch_words = []
    for token, mask in enumerate(exact_outliers):
        residual_negative = raw[token, mask] < 0
        gate_margin, up_margin = [
            2 * (weights[:, mask] == residual_negative).sum(axis=1) - int(mask.sum())
            for weights in negative_weights
        ]
        gate = (gate_margin <= 0) & bool(mask.any())
        up = (up_margin == 0) & bool(mask.any())
        skip = gate & up
        assert np.array_equal(skip, archived_skip[token])
        branch_words.extend(
            pack_bits(gate[group:group + 32]) << 64
            | pack_bits(up[group:group + 32]) << 32
            | pack_bits(skip[group:group + 32])
            for group in range(0, CHANNELS, 32)
        )

    directory = ROOT / ".cache/model_reference/batch396"
    record = ROOT / "records/batch396_mask_fixture.json"
    assert not record.exists()
    directory.mkdir()
    raw_words = [
        sum((int(value) & 65535) << (16 * lane) for lane, value in enumerate(strip))
        for strip in raw.reshape(-1, 8)
    ]
    outlier_pairs = exact_outliers.reshape(TOKENS, FEATURES // 2, 2).any(axis=2)
    write_words(directory / "raw.hex", raw_words, 32)
    write_words(directory / "gate_sign.hex", planes[0], 16)
    write_words(directory / "up_sign.hex", planes[1], 16)
    write_words(directory / "branch_masks.hex", branch_words, 24)
    write_words(directory / "outlier_pairs.hex", (pack_bits(row) for row in outlier_pairs), FEATURES // 8)
    write_words(directory / "outlier_counts.hex", exact_outliers.sum(axis=1), 4)
    files = {str(path): sha256(path) for path in sorted(directory.glob("*.hex"))}
    report = {
        "state": "trained_residuals_and_weight_signs_match_archived_masks",
        "scope": __doc__,
        "tokens": TOKENS,
        "features": FEATURES,
        "channels": CHANNELS,
        "residual_fraction_bits": FRACTION_BITS,
        "epsilon_q16": epsilon_q16,
        "outlier_counts": exact_outliers.sum(axis=1).tolist(),
        "outlier_pair_counts": outlier_pairs.sum(axis=1).tolist(),
        "compared_skip_bits": int(archived_skip.size),
        "skipped_channels": int(archived_skip.sum()),
        "fixture": str(directory),
        "source_sha256": inputs,
        "files_sha256": files,
    }
    record.write_text(json.dumps(report, indent=2) + "\n")
    print(f"BATCH396_FIXTURE_READY exact_skip_bits={archived_skip.size} skipped={archived_skip.sum()}")


if __name__ == "__main__":
    main()
