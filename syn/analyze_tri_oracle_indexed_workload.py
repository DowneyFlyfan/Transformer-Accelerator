"""Measure the indexed images and write bandwidth on the archived model schedule."""

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
import json
import os
from pathlib import Path
import sys

from audit_tri_oracle_placed_chip_boundary import digest
from prepare_tri_oracle_indexed_weight_image import STREAMING, down_tiles, encode_tile, pair_tiles


MODEL = Path(".cache/model_reference")
TRACE = MODEL / "packed_workload_traffic_v1/packed_traffic.json"
RECORDS = Path("records")
DIMENSIONS = {"paired": (8, 2, 2816), "down": (24, 6, 1536)}


def read(path):
    return json.loads(path.read_text())


def matrix(stream, entry):
    assert stream.tell() == entry["offset_bytes"]
    data = stream.read(entry["bytes"])
    assert len(data) == entry["bytes"] and sha256(data).hexdigest() == entry["sha256"]
    return data


def measure(pool, name, source):
    cluster_stride, part_stride, expected_tiles = DIMENSIONS[name]
    tiles = pair_tiles(source) if name == "paired" else down_tiles(source)
    lanes = [Counter() for _ in range(2)]
    for slot, (payload, raw_bytes, bypass) in enumerate(pool.map(encode_tile, tiles, chunksize=8)):
        cluster = slot // cluster_stride % 5
        part = slot // part_stride % 4
        lane = lanes[int(cluster > 2 or (cluster == 2 and part >= 2))]
        beats = (len(payload) + 63) // 64
        assert 2176 <= len(payload) <= raw_bytes <= 8192 and raw_bytes % 256 == 0
        lane.update(tiles=1, raw_tiles=int(bypass), response_beats=1 + beats,
                    requests=1 + (beats + 62) // 63, write_beats=raw_bytes // 64)
    assert sum(lane["tiles"] for lane in lanes) == expected_tiles
    assert 64 * sum(lane["write_beats"] for lane in lanes) == len(source)
    return lanes


def clocks(lanes, groups_per_write):
    # A request and a response each take one service cycle on their lane.
    # The writes may overlap perfect read service on independently ready ports.
    read = max(lane["requests"] + lane["response_beats"] for lane in lanes)
    write = max(lane["write_beats"] // groups_per_write for lane in lanes)
    assert all(lane["write_beats"] % groups_per_write == 0 for lane in lanes)
    return read, write, max(read, write)


def accumulate(totals, lanes, batches):
    totals.update(batches=batches)
    for lane in lanes:
        totals.update({name: count * batches for name, count in lane.items()})
    reads, writes, overlapped = clocks(lanes, 1)
    totals.update(ideal_fixed_lane_read_cycles=reads * batches,
                  ideal_512_bit_write_cycles=writes * batches,
                  ideal_512_bit_pipelined_cycles=overlapped * batches,
                  ideal_2048_bit_pipelined_cycles=clocks(lanes, 4)[2] * batches)


def audit():
    assert __debug__ and Path("/.dockerenv").is_file()
    pair_dir = MODEL / "packed_gate_up_export/v1"
    down_dir = MODEL / "packed_down_export/v1"
    pair_manifest, down_manifest = (folder / "manifest.json" for folder in (pair_dir, down_dir))
    paired_weights, down_weights = (folder / "weights.bin" for folder in (pair_dir, down_dir))
    paired, down = read(pair_manifest), read(down_manifest)
    assert len(paired["matrices"]) == 44 and len(down["layers"]) == 22
    assert digest(paired_weights) == paired["weights_sha256"]
    assert digest(down_weights) == down["weights_sha256"]
    traced = RECORDS / "wac_packed_workload_traffic_result.json"
    previous = RECORDS / "tri_oracle_indexed_down_workload_service.json"
    paper = RECORDS / "paper_result_targets.json"
    linked = RECORDS / "tri_oracle_indexed_whole_chip_link.json"
    wide_value = RECORDS / "tri_oracle_repaired_wide_attention_value_replay.json"
    visible = RECORDS / "tri_oracle_restored_placed_memory_service.json"
    assert digest(TRACE) == read(traced)["evidence_sha256"][str(TRACE)]
    trace = read(TRACE)
    assert len(trace["layers"]) == 22 and (trace["prefill_tokens"], trace["decode_steps"]) == (600, 60)

    sys.path.insert(0, str(STREAMING.resolve()))
    phases = {phase: {name: Counter() for name in DIMENSIONS} for phase in ("prefill", "decode")}
    layers = []
    with paired_weights.open("rb") as p, down_weights.open("rb") as d, ProcessPoolExecutor(
        max_workers=len(os.sched_getaffinity(0))
    ) as pool:
        for n, usage in enumerate(trace["layers"]):
            gate, up = paired["matrices"][2*n:2*n + 2]
            entry = down["layers"][n]
            assert (gate["layer"], up["layer"], entry["layer"]) == (n, n, n)
            assert (gate["branch"], up["branch"]) == ("gate", "up")
            pair_lanes = measure(pool, "paired", matrix(p, gate) + matrix(p, up))
            down_lanes = measure(pool, "down", matrix(d, entry))
            batches = {"prefill": (usage["prefill"]["rows"] + 15) // 16, "decode": usage["decode_calls"]}
            assert batches["decode"] == 60
            for phase, count in batches.items():
                accumulate(phases[phase]["paired"], pair_lanes, count)
                accumulate(phases[phase]["down"], down_lanes, count)
            layers.append({"layer": n, "batches": batches, "paired_lanes": pair_lanes, "down_lanes": down_lanes})
        assert not p.read(1) and not d.read(1)

    old = read(previous)
    for phase, parts in phases.items():
        assert all(part["batches"] == old["batch_counts"][phase] for part in parts.values())
        assert parts["down"]["response_beats"] == old["indexed_down_response_beats"][phase]
        assert parts["down"]["requests"] == old["indexed_down_requests"][phase]
    total = sum((part for parts in phases.values() for part in parts.values()), Counter())
    latency = read(paper)["system_latency"]
    cycles_per_ms = 1000 * latency["clock_megahertz"]
    paper_cycles = cycles_per_ms * latency["milliseconds"]
    values = read(visible)
    wide = read(wide_value)
    assert wide["baseline_value_response_beats"] == 8 * wide["candidate_value_response_beats"]
    assert values["paper_latency_cycles"] == paper_cycles
    assert values["current_primary_value_response_cycles"] == 8 * values["archived_visible_pairs"]
    value_cycles = values["archived_visible_pairs"]
    scenarios = {}
    for width in (512, 2048):
        weight_cycles = total[f"ideal_{width}_bit_pipelined_cycles"]
        scenarios[f"{width}_bit_write_lane"] = {
            "weight_cycles": weight_cycles,
            "weight_ms": round(weight_cycles / cycles_per_ms, 6),
            "serialized_with_one_beat_values_cycles": weight_cycles + value_cycles,
            "serialized_with_one_beat_values_ms": round((weight_cycles + value_cycles) / cycles_per_ms, 6),
            "remaining_cycles_for_one_beat_values": paper_cycles - weight_cycles - value_cycles,
        }
    sources = (TRACE, traced, previous, paper, linked, wide_value, visible, pair_manifest, down_manifest,
               paired_weights, down_weights, Path(__file__), Path("syn/prepare_tri_oracle_indexed_weight_image.py"),
               STREAMING / "make_stream_fixture.py", STREAMING / "verify_stream_images.py")
    return {
        "state": "all_layer_indexed_read_and_write_service_scenarios_measured",
        "linked_candidate_sha256": read(linked)["candidate_sha256"],
        "paper_cycle_budget": paper_cycles,
        "one_beat_per_archived_value_response_cycles": value_cycles,
        "phases": phases,
        "scenarios": scenarios,
        "layers": layers,
        "evidence_sha256": {str(path): digest(path) for path in sources},
        "scope": "Fixed lane steering with full indexed tiles for each archived batch. Gate and up weights precede down-projection weights. Read and write service overlap within each stage. The value scenario serializes one response beat per archived visible pair with weight service. Model omits value requests, other memory traffic, compute, stalls and extracted timing.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    data = audit()
    with args.output.open("x") as receipt:
        json.dump(data, receipt, indent=2, sort_keys=True)
        receipt.write("\n")
    print(json.dumps(data["scenarios"], indent=2), flush=True)
