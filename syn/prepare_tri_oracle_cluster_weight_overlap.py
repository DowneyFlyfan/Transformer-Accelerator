"""Build a signed integer reference for two consecutive trained weight tiles."""

import argparse
from hashlib import file_digest
import json
from pathlib import Path

import numpy as np
import torch


SOURCE = Path(".cache/model_reference/packed_down_export/v1/weights.bin")
FIRST_ROW = 64
TILES, STRIPS, TOKENS, CORES, ROWS, LANES = 2, 32, 16, 4, 32, 8


def weights():
    result = np.empty((TILES, STRIPS, CORES, ROWS, LANES), dtype=np.int8)
    with SOURCE.open("rb") as stream:
        for core in range(CORES):
            for group in range(ROWS // 8):
                stream.seek(64 * ((FIRST_ROW // 8 + group) * 704 + core * 176))
                packed = np.frombuffer(stream.read(TILES * STRIPS * 64), dtype=np.int8)
                result[:, :, core, 8*group:8*(group+1)] = packed.reshape(TILES, STRIPS, 8, LANES)
    return result


def compute(weight, activation, enabled):
    # compute_weights[tile, strip, core, row, lane]
    # compute_inputs[tile, strip, token, core, lane]
    compute_weights = torch.as_tensor(weight, device="cuda", dtype=torch.int32)
    compute_inputs = torch.as_tensor(activation, device="cuda", dtype=torch.int32)
    keep = torch.as_tensor(enabled, device="cuda")
    products = compute_inputs[:, :, :, :, None, :] * compute_weights[:, :, None, :, :, :]
    partials = products.sum(dim=(3, 5), dtype=torch.int64) * keep
    ordered = partials.reshape(TILES*STRIPS, TOKENS, ROWS)
    sums = ordered.cumsum(dim=0).cpu().numpy()

    independent = np.einsum("tsncl,tscrl->tsnr", activation.astype(np.int64), weight.astype(np.int64))
    expected = (independent * enabled).reshape(TILES*STRIPS, TOKENS, ROWS).cumsum(axis=0)
    if not np.array_equal(sums, expected) or np.max(np.abs(sums)) >= 2**31:
        raise ValueError("Host and device integer reference results disagree or overflow")
    return sums.astype("<i4")


def write_hex(path, array):
    with path.open("w") as output:
        for word in array:
            output.write(word.tobytes()[::-1].hex() + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    output = parser.parse_args().output
    assert not Path("/.dockerenv").is_file()
    available, _ = torch.cuda.mem_get_info()
    if available < 512 * 1024**2:
        raise RuntimeError("Insufficient graphics memory for the two-tile reference")
    torch.cuda.reset_peak_memory_stats()
    rng = np.random.default_rng(318601)
    activation = rng.integers(-128, 128, (TILES, STRIPS, TOKENS, CORES, LANES), dtype=np.int8)
    enabled = (np.arange(TOKENS)[:, None]*3 + np.arange(ROWS)[None, :]) % 7 != 0
    weight = weights()
    sums = compute(weight, activation, enabled)
    output.mkdir(parents=True, exist_ok=True)
    write_hex(output / "initial_weights.hex", weight[0].transpose(1, 0, 2, 3).reshape(CORES*STRIPS, ROWS*LANES))
    write_hex(output / "activations.hex", activation.reshape(-1, LANES))
    # Each row needs one byte, whose eight bits enable its eight lanes.
    write_hex(output / "masks.hex", np.uint8(enabled)*255)
    write_hex(output / "accumulators.hex", sums.reshape(-1, ROWS))
    evidence = {}
    for path in (SOURCE, Path(__file__), *sorted(output.glob("*.hex"))):
        with path.open("rb") as stream:
            evidence[str(path)] = file_digest(stream, "sha256").hexdigest()
    result = {"reference_values": sums.size, "fixture_first_row": FIRST_ROW, "trained_layer": 0,
              "seeded_signed_activations": True, "device": torch.cuda.get_device_name(),
              "gpu_peak_tensor_bytes": torch.cuda.max_memory_allocated(), "evidence_sha256": evidence}
    with (output / "reference.json").open("w") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(f"CLUSTER_WEIGHT_REFERENCE_PASS integer_results={sums.size}")


if __name__ == "__main__":
    main()
