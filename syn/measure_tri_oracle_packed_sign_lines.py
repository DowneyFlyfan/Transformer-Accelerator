"""Evaluate 512-bit sign lines for the archived workload and current port budget."""

import argparse
import json
from pathlib import Path

import numpy as np

import measure_tri_oracle_packed_workload_traffic as traffic
from measure_tri_oracle_sign_cache_workload import GROUPS, PAIRS, PREFILL_BATCH, check_native_fixture, misses
from verify_tri_oracle_packed_down_weights import ROOT, sha256


LINE_BYTES = 64
PAIRS_PER_LINE = 4
LINES_PER_GROUP = PAIRS // PAIRS_PER_LINE
CAPACITIES = (0, 64, 128, 256)


def read(path):
    return json.loads(path.read_text())


def packed_line_requests(mask, base):
    """Keep group, token and pair order, with both branches in each line."""
    assert base % LINE_BYTES == 0 and mask.ndim == 2 and mask.shape[1] == PAIRS
    strips = mask.reshape(len(mask), LINES_PER_GROUP, PAIRS_PER_LINE).any(axis=2)
    strip_indices = np.nonzero(strips)[1].astype(np.uint64)  # [active token-strip positions].
    groups = np.arange(GROUPS, dtype=np.uint64) * LINES_PER_GROUP  # [channel groups].
    return (base // LINE_BYTES + groups[:, None] + strip_indices[None, :]).reshape(-1)


def check_line_layout():
    # Verify that every old sign word maps to a unique line and word slot,
    # including the tail of one channel group and the first word of the next.
    words = np.arange(GROUPS * PAIRS, dtype=np.uint64).reshape(GROUPS, PAIRS)
    lines = np.arange(GROUPS, dtype=np.uint64)[:, None] * LINES_PER_GROUP
    pairs = np.arange(PAIRS, dtype=np.uint64)
    slots = (lines + pairs[None, :] // PAIRS_PER_LINE) * 8 + (pairs[None, :] % PAIRS_PER_LINE) * 2
    assert np.array_equal(slots, 2 * words)
    assert np.array_equal((slots + 1).reshape(-1), np.arange(1, GROUPS * PAIRS * 2, 2))


def run(output):
    bound_path = ROOT / "records/wac_primary_request_cycle_bound_result.json"
    cache_path = traffic.DATA / "normalized_sign_cache_workload/receipt.json"
    baseline_path = traffic.DATA / "packed_workload_traffic_v1/packed_traffic.json"
    bound, cache, baseline = map(read, (bound_path, cache_path, baseline_path))
    assert bound["state"] == "serialized_primary_memory_port_cycles_bounded"
    assert bound["evidence_sha256"][str(cache_path.relative_to(ROOT))] == sha256(cache_path)
    assert cache["evidence_sha256"][str(baseline_path.relative_to(ROOT))] == sha256(baseline_path)
    pins = {str(path.relative_to(ROOT)): sha256(path) for path in (
        bound_path, cache_path, baseline_path, Path(__file__).resolve(), Path(misses.__code__.co_filename).resolve(),
    )}
    check_line_layout()
    fixture, _, _ = check_native_fixture(pins)
    layouts = {"trained_fixture": fixture[0], "aligned_example": 0x10000000}
    phases = {name: {"frames": 0, "sign_words": 0, "ideal_lines": 0,
                     "misses": {size: {layout: 0 for layout in layouts} for size in CAPACITIES}}
              for name in ("prefill", "decode")}
    original = traffic.reconstruct

    def capture(reference, activation, stats):
        result = original(reference, activation, stats)
        norms = stats["norm_codes"]  # [token rows, hidden features] from the verified integer policy.
        rows = len(norms)
        masks = (norms.abs() > 768).reshape(rows, PAIRS, 2).any(dim=2).cpu().numpy()  # [rows, pairs].
        name = "decode" if rows == 1 else "prefill"
        phase = phases[name]
        words = 0
        for first in range(0, rows, PREFILL_BATCH):
            mask = masks[first:first + PREFILL_BATCH]  # [frame rows, pairs].
            words += int(mask.sum()) * GROUPS * 2
            line_mask = mask.reshape(len(mask), LINES_PER_GROUP, PAIRS_PER_LINE).any(axis=(0, 2))
            phase["ideal_lines"] += int(line_mask.sum()) * GROUPS
            phase["frames"] += 1
            for layout, base in layouts.items():
                addresses = packed_line_requests(mask, base)
                phase["misses"][0][layout] += addresses.size
                for size in CAPACITIES[1:]:
                    phase["misses"][size][layout] += misses(addresses, size).size
        phase["sign_words"] += words
        assert words * 8 == result[-1]
        return result

    output.mkdir()
    traffic.reconstruct = capture
    try:
        traffic.run(output / "replay")
    finally:
        traffic.reconstruct = original
    replay_path = output / "replay/packed_traffic.json"
    replay = read(replay_path)
    assert all(replay[key] == baseline[key] for key in ("layers", "prefill_by_batch_size", "decode"))
    for phase, counts in phases.items():
        assert counts["frames"] == cache["phases"][phase]["frames"]
        assert counts["sign_words"] == cache["phases"][phase]["logical"]
    primary = bound["minimum_primary_weight_response_beats"] + bound["minimum_primary_weight_requests"]
    frequency = bound["paper_clock_mhz"] * 1000
    cycle_budget = bound["paper_latency_cycle_budget"]
    ideal = sum(phase["ideal_lines"] for phase in phases.values())
    summary = {}
    for size in CAPACITIES:
        summary[size] = {}
        for layout in layouts:
            reads = sum(phase["misses"][size][layout] for phase in phases.values())
            assert ideal <= reads
            cycles = primary + 2 * reads
            summary[size][layout] = {"external_line_reads": reads, "primary_minimum_ms": cycles / frequency,
                                     "remaining_port_cycles": cycle_budget - cycles}
    assert all(sha256(ROOT / name) == digest for name, digest in pins.items())
    pins[str(replay_path.relative_to(ROOT))] = sha256(replay_path)
    result = {
        "state": "packed_sign_line_traffic_modeled_on_archived_workload",
        "sign_line_bytes": LINE_BYTES, "feature_pairs_per_line": PAIRS_PER_LINE,
        "layouts_byte_addresses": layouts, "phases": phases, "summary": summary,
        "ideal_command_local_line_reads": ideal, "paper_latency_cycle_budget": cycle_budget,
        "scope": "Modeled combined gate/up sign layout and cold direct-mapped line caches. Each line takes one "
                 "request and one response cycle on the serialized primary port. Weight reuse is optimistic. "
                 "The line reader, cache and whole-chip workload are not measured in hardware.",
        "peak_gpu_bytes": replay["peak_gpu_bytes"], "evidence_sha256": pins,
    }
    with (output / "receipt.json").open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(result["state"], summary, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=lambda path: Path(path).resolve())
    run(parser.parse_args().output)
