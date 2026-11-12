"""Export packed gate and up weights for every trained language layer."""

import argparse
from hashlib import sha256 as digest_bytes
from io import BytesIO
import json
from pathlib import Path

from safetensors import safe_open
import torch

from pack_tri_oracle_checkpoint_down import model_sources, pack_layer, pinned
from pack_tri_oracle_weights import pack_weights
from verify_tri_oracle_packed_down_weights import ROOT, sha256


BRANCHES = ("gate", "up")


def archive_reference(inputs, rows, features):
    """Pack the archived first-layer signed bytes [channel row, hidden feature]."""
    payloads, pins = {}, {}
    for branch in BRANCHES:
        path = Path(inputs["fixture"]) / f"{branch}.hex"
        pins[path] = pinned(inputs["files_sha256"], path)
        data = BytesIO()
        with path.open("rb") as source:
            pack_weights(source, data, rows, features)
        payloads[branch] = data.getvalue()
    return payloads, pins


@torch.inference_mode()
def export(output):
    torch.set_num_threads(6)
    torch.set_num_interop_threads(1)
    assert torch.cuda.is_available() and torch.cuda.mem_get_info()[0] >= 8 * 2**30
    torch.cuda.set_per_process_memory_fraction(0.35)
    torch.cuda.reset_peak_memory_stats()
    down_keys, features, rows, pins = model_sources()
    assert (rows, features) == (5632, 2048)
    fixture_record = ROOT / "records/batch389_fixture_preparation.json"
    inputs = json.loads(fixture_record.read_text())
    archived, archive_pins = archive_reference(inputs, rows, features)
    pins.update(archive_pins)
    pins[Path(__file__).resolve()] = sha256(Path(__file__))
    for name in ("pack_tri_oracle_checkpoint_down.py", "pack_tri_oracle_weights.py"):
        path = Path(__file__).with_name(name)
        pins[path] = sha256(path)
    model = ROOT / ".cache/model_reference/tiny_llava_v1"
    weight_map = json.loads((model / "model.safetensors.index.json").read_text())["weight_map"]

    output.mkdir()
    temporary = output / "weights.partial"
    weights = output / "weights.bin"
    matrices = []
    try:
        with temporary.open("xb") as destination:
            for layer, (down_key, _) in sorted(down_keys.items()):
                for branch in BRANCHES:
                    key = down_key.removesuffix("down_proj.weight") + f"{branch}_proj.weight"
                    shard = model / weight_map[key]
                    if shard not in pins:
                        pins[shard] = pinned(inputs["source_sha256"], shard)
                    with safe_open(shard, framework="pt", device="cpu") as checkpoint:
                        matrix = checkpoint.get_tensor(key)  # [intermediate channel, hidden feature]
                    assert matrix.shape == (rows, features) and bool(torch.isfinite(matrix).all())
                    payload, exponent = pack_layer(matrix)
                    assert len(payload) == rows * features
                    if layer == 0:
                        assert payload == archived[branch]
                    offset = destination.tell()
                    assert offset == len(matrices) * rows * features and offset % 64 == 0
                    destination.write(payload)
                    matrices.append({"layer": layer, "branch": branch, "checkpoint_key": key,
                                     "offset_bytes": offset, "bytes": len(payload), "scale_exponent": exponent,
                                     "sha256": digest_bytes(payload).hexdigest()})
        assert len(matrices) == 44 and temporary.stat().st_size == len(matrices) * rows * features
        with temporary.open("rb") as source:
            for entry in matrices:
                assert source.tell() == entry["offset_bytes"]
                assert digest_bytes(source.read(entry["bytes"])).hexdigest() == entry["sha256"]
            assert source.read(1) == b""
        assert all(sha256(path) == digest for path, digest in pins.items())
        temporary.rename(weights)
    finally:
        temporary.unlink(missing_ok=True)
    report = {
        "state": "packed_checkpoint_gate_up_weights_cpu_cuda_exact_for_all_language_layers",
        "device": torch.cuda.get_device_name(),
        "peak_allocated_gpu_bytes": torch.cuda.max_memory_allocated(),
        "rows_per_matrix": rows, "features_per_row": features, "bytes_per_response": 64,
        "total_bytes": weights.stat().st_size, "weights_sha256": sha256(weights),
        "first_layer_matrices_match_hardware_fixture": True,
        "matrices": matrices,
        "evidence_sha256": {str(path.relative_to(ROOT)): digest for path, digest in pins.items()},
    }
    (output / "manifest.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f'PACKED_GATE_UP_CHECKPOINT_PASS matrices={len(matrices)} bytes={report["total_bytes"]}', flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    export(parser.parse_args().output.resolve())
