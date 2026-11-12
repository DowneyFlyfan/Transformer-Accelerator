"""Export the down-projection weights for every language layer as packed read beats."""

import argparse
from hashlib import sha256 as digest_bytes
import json
from pathlib import Path
import re

import numpy as np
from safetensors import safe_open
import torch

from tri_oracle_integer_reference import _quantize
from verify_tri_oracle_packed_down_weights import ROOT, sha256


def pinned(pins, path):
    digest = sha256(path)
    assert pins[str(path)] == digest, path
    return digest


def model_sources():
    fixture = ROOT / "records/batch389_fixture_preparation.json"
    inputs = json.loads(fixture.read_text())
    assert inputs["state"] == "complete_trained_layer_fixture_scalar_cuda_equal"
    model = ROOT / ".cache/model_reference/tiny_llava_v1"
    index = model / "model.safetensors.index.json"
    config = model / "config.json"
    reference = ROOT / "syn/tri_oracle_integer_reference.py"
    sources = {path: pinned(inputs["source_sha256"], path) for path in (index, config, reference)}
    text = json.loads(config.read_text())["text_config"]
    layer_count, rows, features = (text[name] for name in ("num_hidden_layers", "hidden_size", "intermediate_size"))
    assert (layer_count, rows, features) == (22, 2048, 5632)
    weight_map = json.loads(index.read_text())["weight_map"]
    keys = {}
    for name, file in weight_map.items():
        match = re.search(r"\.layers\.(\d+)\.mlp\.down_proj\.weight$", name)
        if match:
            layer = int(match[1])
            assert layer not in keys
            keys[layer] = name, model / file
    assert sorted(keys) == list(range(layer_count))
    for shard in {file for _, file in keys.values()}:
        sources[shard] = pinned(inputs["source_sha256"], shard)
    sources[fixture] = sha256(fixture)
    return keys, rows, features, sources


def pack_layer(matrix):
    # Matrix [output row, intermediate feature]. Each 64-byte beat holds
    # eight feature bytes for each of eight output rows, lowest lane first.
    rows, features = matrix.shape
    cpu, cpu_scale = _quantize(matrix)
    gpu, gpu_scale = _quantize(matrix.to("cuda"))
    assert int(cpu_scale) == int(gpu_scale)
    beats = gpu.reshape(rows // 8, 8, features // 8, 8).transpose(1, 2).contiguous().cpu().numpy()
    reference = cpu.numpy()
    for lane in range(8):
        np.testing.assert_array_equal(beats[:, :, lane, :].reshape(-1, features), reference[lane::8])
    return beats.tobytes(), int(cpu_scale)


@torch.inference_mode()
def export(output):
    torch.set_num_threads(6)
    torch.set_num_interop_threads(1)
    assert torch.cuda.is_available() and torch.cuda.mem_get_info()[0] >= 8 * 2**30
    torch.cuda.set_per_process_memory_fraction(0.35)
    torch.cuda.reset_peak_memory_stats()
    keys, rows, features, sources = model_sources()
    packed_record = ROOT / "records/wac_packed_trained_down_fabric_result.json"
    record = json.loads(packed_record.read_text())
    assert record["state"] == "packed_trained_down_weights_checked_on_twenty_compiled_memory_cores"
    layer_zero, = [ROOT / name for name in record["evidence_sha256"] if name.endswith("/packed_down_fabric/packed.bin")]
    assert sha256(layer_zero) == record["evidence_sha256"][str(layer_zero.relative_to(ROOT))]
    for path in (packed_record, layer_zero, Path(__file__).resolve()):
        sources[path] = sha256(path)

    output.mkdir()
    temporary = output / "weights.partial"
    weights = output / "weights.bin"
    layers = []
    try:
        with temporary.open("xb") as destination:
            for layer, (name, shard) in sorted(keys.items()):
                with safe_open(shard, framework="pt", device="cpu") as checkpoint:
                    matrix = checkpoint.get_tensor(name)
                assert matrix.shape == (rows, features) and bool(torch.isfinite(matrix).all())
                payload, exponent = pack_layer(matrix)
                assert len(payload) == rows * features
                offset = destination.tell()
                assert offset == layer * rows * features and offset % 64 == 0
                if layer == 0:
                    assert payload == layer_zero.read_bytes()
                destination.write(payload)
                layers.append({"layer": layer, "checkpoint_key": name, "offset_bytes": offset,
                               "bytes": len(payload), "scale_exponent": exponent,
                               "sha256": digest_bytes(payload).hexdigest()})
                print(f"PACKED_DOWN_LAYER layer={layer} offset={offset} bytes={len(payload)}", flush=True)
        assert temporary.stat().st_size == len(layers) * rows * features
        # Check every stored layer again before publishing the address table.
        with temporary.open("rb") as source:
            for layer in layers:
                assert source.tell() == layer["offset_bytes"]
                assert digest_bytes(source.read(layer["bytes"])).hexdigest() == layer["sha256"]
            assert source.read(1) == b""
        assert all(sha256(path) == digest for path, digest in sources.items())
        temporary.rename(weights)
    finally:
        temporary.unlink(missing_ok=True)

    report = {
        "state": "packed_checkpoint_down_weights_cpu_cuda_exact_for_all_language_layers",
        "device": torch.cuda.get_device_name(),
        "peak_allocated_gpu_bytes": torch.cuda.max_memory_allocated(),
        "rows_per_layer": rows,
        "features_per_row": features,
        "bytes_per_response": 64,
        "total_bytes": weights.stat().st_size,
        "weights_sha256": sha256(weights),
        "layer_zero_matches_hardware_fixture": True,
        "layers": layers,
        "evidence_sha256": {str(path.relative_to(ROOT)): digest for path, digest in sources.items()},
    }
    with (output / "manifest.json").open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(f'PACKED_DOWN_CHECKPOINT_PASS layers={len(layers)} bytes={report["total_bytes"]}', flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    export(parser.parse_args().output.resolve())
