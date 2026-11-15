"""Measure indexed write-image traffic for the frozen calibrated down codes."""

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
import os
from pathlib import Path
import struct
import sys

import numpy as np
import torch

from prepare_tri_oracle_indexed_weight_image import DOWN_PAYLOAD_BASE, STREAMING, down_tiles, write_image
from tri_oracle_integer_reference import _quantize
from verify_tri_oracle_packed_down_weights import ROOT, sha256


MODEL = ROOT / ".cache/model_reference/tiny_llava_v1"
EXPORT = ROOT / ".cache/model_reference/gqa_testdev/down_code_calibration_export"
SHAPE = (2048, 5632)


def read(path):
    return json.loads(path.read_text())


def read_checkpoint_tensor(shard, key):
    """Read one pinned little-endian floating tensor without mapping the whole shard."""
    with shard.open("rb") as stream:
        length, = struct.unpack("<Q", stream.read(8))
        assert 0 < length < 2**24
        entry = json.loads(stream.read(length))[key]
        start, end = entry["data_offsets"]
        assert entry["dtype"] == "F32" and tuple(entry["shape"]) == SHAPE
        assert 0 <= start < end and end - start == 4 * SHAPE[0] * SHAPE[1]
        assert 8 + length + end <= shard.stat().st_size
        stream.seek(8 + length + start)
        tensor = bytearray(end - start)
        assert stream.readinto(tensor) == len(tensor)
    assert sys.byteorder == "little"
    return torch.frombuffer(tensor, dtype=torch.float32).reshape(SHAPE)


def pack(codes):
    """Map [output channel, intermediate feature] to [output group, word, byte]."""
    assert codes.shape == SHAPE and codes.dtype == torch.int8 and codes.device.type == "cpu"
    channel = codes.numpy()  # [2048,5632], row-major weight code matrix
    packed = channel.reshape(256, 8, 704, 8).transpose(0, 2, 1, 3).copy()  # [256,704,8,8]
    np.testing.assert_array_equal(packed.transpose(0, 2, 1, 3).reshape(SHAPE), channel)
    return packed.reshape(256, 704, 64)


def transfer_size(packed):
    """Count exact indexed transport bytes using the image encoder's length rules."""
    observed = np.abs(packed.astype(np.int16))  # [256,704,64], -128 has magnitude 128
    byte_count = np.full(observed.shape[:-1], 64, dtype=np.int16)  # [256,704], raw body size
    for width in range(4, 8):
        escape_count = np.count_nonzero(observed > (1 << (width - 1)) - 1, axis=-1)
        np.minimum(byte_count, width * 8 + escape_count, out=byte_count, casting="unsafe")
    block_bytes = (byte_count + 3) & ~3  # Four-byte body padding, [256,704]
    # Four groups per word contribute two four-byte headers per tile word.
    words = block_bytes.reshape(64, 4, 704).sum(axis=1) + 8  # [64,704]
    tiles = []
    for partition in range(4):
        for start in range(0, 176, 32):
            count = min(32, 176-start)
            begin = partition*176 + start
            compressed = words[:, begin:begin+count].sum(axis=1)  # 64 output banks
            raw = count * 4 * 64
            tiles.append((compressed, raw))
    stored = np.concatenate([np.minimum(encoded, raw) for encoded, raw in tiles])
    return {"tiles": int(stored.size), "raw_tiles": sum(int(np.count_nonzero(encoded >= raw)) for encoded, raw in tiles),
            "payload_bytes": int(stored.sum()), "payload_beats": int(((stored + 63) // 64).sum())}


def exact_image(packed, facts, destination):
    destination.mkdir()
    raw = packed.tobytes()
    with (destination / "raw_down.bin").open("xb") as stream:
        stream.write(raw)
    with ProcessPoolExecutor(max_workers=min(12, len(os.sched_getaffinity(0)))) as pool:
        result = write_image(pool, "down", down_tiles(raw), DOWN_PAYLOAD_BASE, destination)
    assert result["payload_beats"] == facts["payload_beats"]
    assert result["encoded_tiles"] + facts["raw_tiles"] == result["index_entries"] == facts["tiles"] == 1536
    index = (destination / "down_index.bin").read_bytes()
    assert sum(int.from_bytes(index[i+8:i+10], "little") & 0x3fff
               for i in range(0, len(index), 64)) == facts["payload_bytes"]
    return {str(path.relative_to(ROOT)): sha256(path) for path in sorted(destination.iterdir())}


@torch.inference_mode()
def run(output):
    assert __debug__ and Path("/.dockerenv").is_file()
    torch.set_num_threads(3)
    torch.set_num_interop_threads(1)
    sys.path.insert(0, str(STREAMING.resolve()))
    calibration = EXPORT / "receipt.json"
    calibration_result = ROOT / "records/tri_oracle_down_code_calibration.json"
    verified = read(calibration_result)
    assert sha256(calibration) == verified["evidence_sha256"][str(calibration.relative_to(ROOT))]
    frozen = read(calibration)
    config = MODEL / "model.safetensors.index.json"
    mapping = read(config)["weight_map"]
    evidence = {str(path): sha256(path) for path in (calibration, calibration_result, config, Path(__file__).resolve(),
                 ROOT / "syn/prepare_tri_oracle_indexed_weight_image.py",
                 STREAMING / "make_stream_fixture.py", STREAMING / "verify_stream_images.py")}
    paths = {MODEL / name for key, name in mapping.items() if key.endswith(".down_proj.weight")}
    for path in (*paths, config):
        expected = frozen["evidence_sha256"][str(path)]
        assert sha256(path) == expected
        evidence[str(path)] = expected

    output.mkdir()
    layers, fixture_hashes = [], {}
    for index, layer in enumerate(frozen["layers"]):
        assert layer["layer"] == index
        key, = (name for name in mapping if name.endswith(f".layers.{index}.mlp.down_proj.weight"))
        original, expected_scale = _quantize(read_checkpoint_tensor(MODEL / mapping[key], key), per_row=True)
        artifact = EXPORT / f"codes/down_{index:02d}.pt"
        assert sha256(artifact) == layer["codebook_sha256"]
        evidence[str(artifact)] = layer["codebook_sha256"]
        calibrated = torch.load(artifact, weights_only=True, map_location="cpu")
        candidate = calibrated["codes"]
        assert torch.equal(expected_scale, calibrated["scale"])
        assert bool(((candidate.to(torch.int16) - original).abs() <= 1).all())
        assert int(candidate.ne(original).sum()) == layer["changed_codes"]
        row = {"layer": index}
        for tag, codes in (("baseline", original), ("calibrated", candidate)):
            packed = pack(codes)
            facts = transfer_size(packed)
            assert facts["tiles"] == 1536 and 0 < facts["payload_beats"] < (2048*5632)//64
            row[tag] = facts
            if index == 10:
                fixture_hashes.update(exact_image(packed, facts, output / f"layer10_{tag}"))
        layers.append(row)
        print("DOWN_CODE_TRANSPORT_LAYER", index, row, flush=True)
    assert len(layers) == 22 and all(sha256(Path(path)) == checksum for path, checksum in evidence.items())
    totals = {tag: {name: sum(row[tag][name] for row in layers) for name in layers[0][tag]}
              for tag in ("baseline", "calibrated")}
    result = {"state": "calibrated_down_codes_indexed_transport_counted", "layers": layers, "totals": totals,
              "layer10_encoded_image_sha256": fixture_hashes, "input_sha256": evidence,
              "scope": "Exact per-tile payload sizes from the existing code format. Every byte of both layer-10 "
                       "images was checked with the current encoder and its separate software decoder. The all-layer "
                       "totals measure a full read of each indexed matrix. Request reuse, memory service and energy "
                       "require workload and physical evidence."}
    with (output / "receipt.json").open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=lambda value: Path(value).resolve())
    run(parser.parse_args().output)
