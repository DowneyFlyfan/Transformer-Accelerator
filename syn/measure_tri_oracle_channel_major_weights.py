"""Validate channel-aligned weight images and count whole memory transfers."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil

from audit_tri_oracle_packed_weight_traffic import CHANNELS, HIDDEN, TOKENS, read_rows
from verify_tri_oracle_packed_down_weights import ROOT, sha256 as file_sha256


MODEL = ROOT / ".cache/model_reference"
WEIGHTS = ROOT / "records/batch389_fixture_preparation.json"
TRAFFIC = ROOT / "records/wac_packed_trained_weight_traffic_result.json"
BURST = 64
BRANCHES = ("gate", "up", "down")
GROUP_SIZES = (1, 2, 4, 8, 16)


def read(path):
    return json.loads(path.read_text())


def validate_existing_image(image, entry, matrix, rows, features):
    """Compare the native eight-by-eight transport against row-major weight bytes."""
    with image.open("rb") as stream:
        stream.seek(entry["offset_bytes"])
        packed = stream.read(entry["bytes"])
    assert len(packed) == len(matrix) == rows * features
    assert sha256(packed).hexdigest() == entry["sha256"]
    for group, offset in enumerate(range(0, len(packed), 8 * features)):
        block = packed[offset:offset + 8 * features]
        for lane in range(8):
            channel = group * 8 + lane
            raw = b"".join(block[start + lane * 8:start + (lane + 1) * 8]
                           for start in range(0, len(block), BURST))
            assert raw == matrix[channel * features:(channel + 1) * features], (channel, image)


def write_image(destination, matrix, branch):
    """A channel owns HIDDEN consecutive bytes and starts on a 64-byte boundary."""
    assert HIDDEN % BURST == 0 and len(matrix) == HIDDEN * CHANNELS
    with destination.open("xb") as stream:
        if branch == "down":
            # Down-projection input channels are columns of the canonical matrix.
            for channel in range(CHANNELS):
                stream.write(matrix[channel::CHANNELS])
        else:
            stream.write(matrix)
    packed = destination.read_bytes()
    assert len(packed) == HIDDEN * CHANNELS
    if branch == "down":
        for row in range(HIDDEN):
            assert packed[row::HIDDEN] == matrix[row * CHANNELS:(row + 1) * CHANNELS], row
    else:
        assert packed == matrix


def group_beats(keep, activation, down):
    """Count bursts touched by a group sharing one resident copy of its weights."""
    chunks = []
    for row in activation:
        chunks.append(sum(1 << (start // BURST) for start in range(0, HIDDEN, BURST)
                          if any(row[start:start + BURST])))
    gate_beats = 0
    for retained in zip(*keep, strict=True):
        read_mask = 0
        for enabled, features in zip(retained, chunks, strict=True):
            if enabled:
                read_mask |= features
        gate_beats += read_mask.bit_count()
    down_beats = sum(any(values) for values in zip(*down, strict=True)) * (HIDDEN // BURST)
    return {"gate": gate_beats, "up": gate_beats, "down": down_beats}


def run(output):
    weights, baseline = read(WEIGHTS), read(TRAFFIC)
    assert weights["original_layer"] == 0 and weights["tokens"] == TOKENS
    assert baseline["state"] == "packed_trained_frame_weight_traffic_reconstructed_exactly"
    assert shutil.disk_usage(output.parent).free > 2**30
    output.mkdir()
    evidence = {str(path.relative_to(ROOT)): file_sha256(path) for path in (WEIGHTS, TRAFFIC, Path(__file__).resolve())}
    matrices = {}
    for branch in BRANCHES:
        export = MODEL / f"packed_{'down' if branch == 'down' else 'gate_up'}_export/v1"
        manifest_path = export / "manifest.json"
        manifest = read(manifest_path)
        key = "layers" if branch == "down" else "matrices"
        entry, = (item for item in manifest[key] if item["layer"] == 0 and item.get("branch", "down") == branch)
        fixture = Path(weights["fixture"]) / f"{branch}.hex"
        assert file_sha256(fixture) == weights["files_sha256"][str(fixture)]
        matrix = bytes.fromhex(fixture.read_text())
        shape = (HIDDEN, CHANNELS) if branch == "down" else (CHANNELS, HIDDEN)
        validate_existing_image(export / "weights.bin", entry, matrix, *shape)
        image = output / f"{branch}.bin"
        write_image(image, matrix, branch)
        matrices[branch] = {"bytes": image.stat().st_size, "sha256": file_sha256(image),
                            "native_input_layer_sha256": entry["sha256"]}
        for path in (fixture, manifest_path):
            evidence[str(path.relative_to(ROOT))] = file_sha256(path)

    fixtures = (MODEL / "batch389/keep.hex", MODEL / "batch403/activation.hex", MODEL / "batch407/intermediate.hex")
    for path in fixtures:
        key = str(path.relative_to(ROOT))
        evidence[key] = file_sha256(path)
        assert evidence[key] == baseline["evidence_sha256"][key]
    keep, activation, down = (read_rows(path, width) for path, width in zip(
        fixtures, (CHANNELS, HIDDEN, CHANNELS), strict=True))
    assert all(flag in (0, 1) and (flag or value == 0)
               for mask, data in zip(keep, down, strict=True) for flag, value in zip(mask, data, strict=True))
    assert TOKENS * CHANNELS - sum(map(sum, keep)) == baseline["predicted_skipped_channels"]
    projections = {}
    for size in GROUP_SIZES:
        groups = [group_beats(keep[start:start + size], activation[start:start + size], down[start:start + size])
                  for start in range(0, TOKENS, size)]
        beats = {name: sum(group[name] for group in groups) for name in BRANCHES}
        projections[str(size)] = {"beats_by_projection": beats, "channel_major_weight_bytes": BURST * sum(beats.values()),
                                  "existing_packed_weight_bytes": baseline["weight_payload_bytes_by_group_size_without_cross_group_reuse"][str(size)]}
    report = {
        "state": "trained_weight_images_round_trip_in_channel_major_order", "layer": 0, "tokens": TOKENS,
        "channel_bytes": HIDDEN, "burst_bytes": BURST, "matrices": matrices, "weight_traffic_by_group_size": projections,
        "evidence_sha256": evidence,
        "scope": "Lossless file conversion and projected weight bytes for the pinned frame. "
                 "Sign traffic, hardware scheduling, timing, and model accuracy are outside this experiment.",
    }
    with (output / "receipt.json").open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(report["state"], projections, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=lambda value: Path(value).resolve())
    run(parser.parse_args().output)
