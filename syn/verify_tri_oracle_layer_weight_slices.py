"""Verify packed gate, up and down matrices for a trained decoder layer."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import struct

import numpy as np

from verify_tri_oracle_packed_down_weights import ROOT, sha256 as file_sha256


DATA = ROOT / ".cache/model_reference"
MODEL = DATA / "tiny_llava_v1"
SHAPES = {"gate": (5632, 2048), "up": (5632, 2048), "down": (2048, 5632)}


def read(path):
    return json.loads(path.read_text())


def quantized_matrix(matrix):
    assert matrix.dtype == np.float32 and np.isfinite(matrix).all()
    maximum = np.abs(matrix).max()
    fraction, exponent = np.frexp(maximum)
    scale = int(exponent) - 7 + int(fraction > 127 / 128) if maximum else 0
    scaled = np.ldexp(matrix, -scale)
    return (np.sign(scaled) * np.floor(np.abs(scaled) + np.float32(0.5))).clip(-128, 127).astype(np.int8), scale


def unpack_slice(payload, shape):
    rows, features = shape
    return np.frombuffer(payload, dtype=np.int8).reshape(
        rows // 8, features // 8, 8, 8).transpose(0, 2, 1, 3).reshape(shape)


def checkpoint_matrix(path, key, shape):
    """Read only one float32 matrix from a verified SafeTensors shard."""
    with path.open("rb") as shard:
        header_size, = struct.unpack("<Q", shard.read(8))
        assert 0 < header_size <= 100_000_000
        entry = json.loads(shard.read(header_size))[key]
        assert entry["dtype"] == "F32" and entry["shape"] == list(shape)
        start, stop = entry["data_offsets"]
        assert 0 <= start < stop and stop - start == 4 * shape[0] * shape[1]
        assert 8 + header_size + stop <= path.stat().st_size
        shard.seek(8 + header_size + start)
        data = shard.read(stop - start)
    assert len(data) == stop - start
    return np.frombuffer(data, dtype="<f4").reshape(shape)


def verify(layer, output):
    assert __debug__ and Path("/.dockerenv").is_file()
    model_record = ROOT / "records/model_reference_candidate.json"
    model = read(model_record)
    index = MODEL / "model.safetensors.index.json"
    weight_map = read(index)["weight_map"]
    checkpoints = {item["file"]: item for item in model["weight_files"]}
    sources = {path: file_sha256(path) for path in (model_record, index, Path(__file__).resolve())}
    rows = {}
    for archive_name, record_name, array_name, branches in (
        ("packed_gate_up_export", "wac_packed_checkpoint_gate_up_result.json", "matrices", ("gate", "up")),
        ("packed_down_export", "wac_packed_checkpoint_down_result.json", "layers", ("down",)),
    ):
        archive = DATA / archive_name / "v1"
        manifest_path, weights = archive / "manifest.json", archive / "weights.bin"
        record_path = ROOT / "records" / record_name
        record, manifest = read(record_path), read(manifest_path)
        manifest_digest = file_sha256(manifest_path)
        assert manifest_digest == record["evidence_sha256"][str(manifest_path.relative_to(ROOT))]
        sources[record_path], sources[manifest_path] = file_sha256(record_path), manifest_digest
        assert weights.stat().st_size == manifest["total_bytes"]
        for branch in branches:
            entry, = (item for item in manifest[array_name]
                      if item["layer"] == layer and item.get("branch", "down") == branch)
            shape = SHAPES[branch]
            key = f"language_model.model.layers.{layer}.mlp.{branch}_proj.weight"
            assert entry["checkpoint_key"] == key and entry["bytes"] == shape[0] * shape[1]
            offset = (layer * len(branches) + branches.index(branch)) * entry["bytes"]
            assert entry["offset_bytes"] == offset
            checkpoint = MODEL / weight_map[key]
            checkpoint_record = checkpoints[checkpoint.name]
            if checkpoint not in sources:
                assert checkpoint.stat().st_size == checkpoint_record["bytes"]
                sources[checkpoint] = file_sha256(checkpoint)
                assert sources[checkpoint] == checkpoint_record["lfs_sha256"]
            with weights.open("rb") as stream:
                stream.seek(offset)
                payload = stream.read(entry["bytes"])
            assert len(payload) == entry["bytes"] and sha256(payload).hexdigest() == entry["sha256"]
            codes, scale = quantized_matrix(checkpoint_matrix(checkpoint, key, shape))
            assert scale == entry["scale_exponent"]
            np.testing.assert_array_equal(unpack_slice(payload, shape), codes)
            rows[branch] = dict(shape=list(shape), scale_exponent=scale, bytes=len(payload),
                                packed_sha256=entry["sha256"], checkpoint_key=key, offset_bytes=offset)
    assert rows.keys() == SHAPES.keys()
    for path, checksum in sources.items():
        assert file_sha256(path) == checksum, path
    result = dict(state="trained_layer_packed_weights_match_checkpoint_byte_for_byte",
                  layer=layer, model_revision=model["revision"], branches=rows,
                  exact_bytes=sum(row["bytes"] for row in rows.values()),
                  input_sha256={str(path.relative_to(ROOT)): checksum for path, checksum in sources.items()})
    with output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print("LAYER_PACKED_WEIGHTS_PASS", layer, result["exact_bytes"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("layer", type=int, choices=range(22))
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    verify(args.layer, args.output)
