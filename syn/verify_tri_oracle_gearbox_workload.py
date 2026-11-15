"""Recompute burst padding for the archived weight encoding at 448 bits per cycle."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

import numpy as np

from audit_tri_oracle_placed_fanout import GIB, memory, sha


ROOT = Path.cwd()
DATA = ROOT / ".cache/model_reference"
ENCODING = DATA / "lossless_weight_burst_probe"
BEAT_BYTES = 64
BLOCK_BYTES = 2048
WORDS_PER_RESPONSE = 8
WORDS_PER_FRAGMENT = 7


def read(path):
    return json.loads(path.read_text())


def chunks(beats):
    return (beats * WORDS_PER_RESPONSE + WORDS_PER_FRAGMENT - 1) // WORDS_PER_FRAGMENT


def gate_cycles(weights, manifest, trace, proof):
    totals = Counter()
    with weights.open("rb") as source:
        for matrix in manifest["matrices"]:
            raw = source.read(matrix["bytes"])
            assert len(raw) == matrix["bytes"] and hashlib.sha256(raw).hexdigest() == matrix["sha256"]
            blocks = np.frombuffer(raw,dtype=np.int8).reshape(-1,BLOCK_BYTES)
            shortest = np.full(len(blocks),BLOCK_BYTES//BEAT_BYTES)
            for bits in (4,5,6,7):
                limit = (1 << (bits - 1)) - 1
                literal_bytes = np.count_nonzero((blocks < -limit) | (blocks > limit),axis=1)
                beats = (BLOCK_BYTES*bits//8 + literal_bytes + BEAT_BYTES-1)//BEAT_BYTES
                shortest = np.minimum(shortest,beats)
            index,branch = matrix["layer"],matrix["branch"]
            assert int(shortest.sum()) == proof["layer_branch_results"][f"{index}/{branch}"]["payload_beats"]
            layer = trace[index]
            batch_count = (layer["prefill_rows"]+15)//16 + layer["decode_rows"]
            totals.update(
                payload_beats=batch_count * int(shortest.sum()),
                payload_chunks=batch_count * int(chunks(shortest).sum()),
                payload_bursts=batch_count * len(blocks),
            )
        assert not source.read(1)
    return totals


def verify():
    assert Path("/.dockerenv").is_file() and __debug__ and memory()[0] >= 7*GIB
    evidence = {}

    def pin(path, expected=None):
        actual = sha(path)
        assert expected is None or actual == expected, path
        evidence[str(path.relative_to(ROOT))] = actual
        return path

    prior = read(pin(ROOT/"records/tri_oracle_physical_io_budget.json"))
    targets = read(pin(ROOT/"records/paper_result_targets.json"))
    transport = read(pin(ENCODING/"transport_receipt.json"))
    assert transport["state"] == "lossless_encoding_external_and_local_bandwidth_reconciled"
    encoding = read(pin(ENCODING/"receipt.json",transport["input_sha256"][str((ENCODING/"receipt.json").relative_to(ROOT))]))
    assert encoding["state"] == "trained_weight_block_encoding_round_trip_verified"
    archive = DATA/"packed_gate_up_export/v1"
    manifest_path, weights = (archive/name for name in ("manifest.json","weights.bin"))
    for path in (manifest_path,weights):
        pin(path,encoding["input_sha256"][str(path.relative_to(ROOT))])
    manifest = read(manifest_path)
    trace_path = DATA/"normalized_workload_trace/receipt.json"
    schedule_path = DATA/"normalized_weight_burst_schedule_v2/receipt.json"
    trace = read(pin(trace_path,encoding["input_sha256"][str(trace_path.relative_to(ROOT))]))["layers"]["compact_streaming_pruned"]
    schedule = read(pin(schedule_path))
    assert len(manifest["matrices"]) == 44 and len(trace) == 22
    gate = gate_cycles(weights,manifest,trace,encoding)
    observed_lanes = transport["fixed_lane_traffic"]
    assert gate["payload_bursts"] == sum(lane["gate_blocks"] for lane in observed_lanes)
    assert gate["payload_beats"] == sum(lane["encoded_gate_payload_beats"] for lane in observed_lanes)

    down = Counter()
    for phase in schedule["phases"].values():
        for count, bursts in phase["down"].items():
            beats = int(count)
            down.update(payload_beats=beats*bursts,payload_chunks=chunks(beats)*bursts,payload_bursts=bursts)
    assert down["payload_beats"] == sum(lane["unencoded_down_beats"] for lane in observed_lanes)
    indexes = gate["payload_bursts"]
    responses = gate["payload_beats"] + down["payload_beats"] + indexes
    assert responses == transport["encoded_weight_response_beats"]
    actual_chunks = gate["payload_chunks"] + down["payload_chunks"] + chunks(1)*indexes
    contiguous_chunks = chunks(responses)
    assert actual_chunks > contiguous_chunks
    frames = gate["payload_bursts"] + down["payload_bursts"] + indexes
    # A request accepted on a lane is followed by its response, before that lane
    # can accept another request. Perfectly balanced lanes give a lower bound.
    lane_cycles_balanced = (actual_chunks+frames+1)//2
    target = targets["system_latency"]
    target_cycles = target["clock_megahertz"]*1000*target["milliseconds"]
    assert target_cycles == prior["target_cycles"]
    serial_path = ROOT / ".cache/physical/wide_weight_loader/joined_chip_partition/serial_projection_budget.json"
    serial = read(pin(serial_path, transport["input_sha256"][str(serial_path.relative_to(ROOT))]))
    assert serial["state"] == "archived_workload_serial_projection_budget_checked"
    assert serial["target_cycles"] == target_cycles
    assert serial["paper_clock_megahertz"] == target["clock_megahertz"]
    serial_cycles = lane_cycles_balanced + serial["minimum_projection_issue_cycles"]
    pin(Path(__file__).resolve())
    return dict(state="archived_weight_burst_padding_verified_for_memory_response_gearbox",
        gate_up=dict(gate),down_projection=dict(down),
        modeled_single_response_index_bursts=indexes,
        unpadded_aggregate_fragments=contiguous_chunks,
        burst_aligned_aggregate_fragments=actual_chunks,
        slice_padding_aggregate_fragments=actual_chunks-contiguous_chunks,
        one_request_cycle_per_burst=frames,
        two_lane_ideal_balanced_service_cycles=lane_cycles_balanced,
        two_lane_ideal_balanced_weight_service_ms=lane_cycles_balanced/(target["clock_megahertz"]*1000),
        paper_system_latency_ms=target["milliseconds"],
        cycles_remaining_in_paper_budget_after_modeled_weight_service=target_cycles-lane_cycles_balanced,
        conditional_serial_weight_and_projection_ms=serial_cycles/(target["clock_megahertz"]*1000),
        conditional_serial_cycles_over_paper_budget=serial_cycles-target_cycles,
        scope="Archived encoding and weight reads only. Each burst ends on a chunk boundary. The balanced "
              "cycle estimate allows one accepted request per burst and no other overhead. It excludes "
              "fixed lane imbalance, sign and attention traffic, compute, physical capture and stalls. "
              "The serial scenario separately charges projection issue cycles without overlapping them.",
        evidence_sha256=evidence)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output",type=Path)
    args=parser.parse_args()
    proof=verify()
    with args.output.open("x") as stream:
        json.dump(proof,stream,indent=2,sort_keys=True)
        stream.write("\n")
    print("GEARBOX_WORKLOAD_COUNTS",proof["slice_padding_aggregate_fragments"],
          proof["two_lane_ideal_balanced_weight_service_ms"],flush=True)
