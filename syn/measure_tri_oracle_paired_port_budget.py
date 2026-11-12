"""Bound decode weight service time for the paired chip's serial bursts."""

import argparse
from fractions import Fraction
import json
from pathlib import Path

from verify_tri_oracle_packed_down_weights import ROOT, sha256


BASE = ROOT / ".cache/physical/wide_weight_loader"
RECORDS = ROOT / "records"
TRACE = ROOT / ".cache/model_reference/packed_read_traffic_trace/run/per_token_reads.json"
READ_BUDGET = RECORDS / "wac_unified_decode_read_budget_result.json"
TARGETS = RECORDS / "paper_result_targets.json"
PAIRED = RECORDS / "wac_paired_chip_feedforward_result.json"
FRAME = BASE / "paired_chip/tri_oracle_batched_frame393.sv"
PREPARED = BASE / "paired_chip/prepared.json"
SCHEDULE = ROOT / "verilog/tri_oracle_packed_weight_schedule.sv"
LOADER = ROOT / "verilog/tri_oracle_wide_weight_loader.sv"

ROWS_PER_RESPONSE = 8
MAX_BURST_RESPONSES = 32
# The scheduler's Find, Offer, and Await and the loader's Request each
# require a separate cycle from payload transfer. Await retires after the
# last response, and the single scheduler cannot issue a second burst then.
CONTROL_CYCLES_PER_BURST = 4


def blocks(count, width):
    return (count + width - 1) // width


def count_transfers(layers):
    gate_up_responses = gate_up_bursts = down_responses = down_bursts = 0
    for layer in layers:
        for row in layer:
            groups = blocks(row["retained_channels"], ROWS_PER_RESPONSE)
            gate = row["gate_up_words"]
            down = row["down_words"]
            assert 0 <= groups <= 5632 // ROWS_PER_RESPONSE
            assert 0 <= gate <= 2048 // 8 and 0 <= down <= 5632 // 8
            gate_up_responses += 2 * groups * gate
            gate_up_bursts += 2 * groups * blocks(gate, MAX_BURST_RESPONSES)
            down_groups = 2048 // ROWS_PER_RESPONSE
            down_responses += down_groups * down
            down_bursts += down_groups * blocks(down, MAX_BURST_RESPONSES)
    return {
        "gate_up": {"responses": gate_up_responses, "bursts": gate_up_bursts},
        "down": {"responses": down_responses, "bursts": down_bursts},
    }


def measure():
    def read(path):
        return json.loads(path.read_text())

    def pin(record, path, key="evidence_sha256"):
        assert record[key][str(path.relative_to(ROOT))] == sha256(path), path

    original = read(READ_BUDGET)
    for path in (TRACE, TARGETS):
        pin(original, path)
    candidate = read(PAIRED)
    assert candidate["state"] == "paired_weight_schedule_mapped_and_directed_chip_frames_exact"
    pin(candidate, PREPARED)
    prepared = read(PREPARED)
    for path in (FRAME, SCHEDULE, LOADER):
        pin(prepared, path, "input_sha256")
    target = read(TARGETS)["system_latency"]
    layers = read(TRACE)
    assert len(layers) == original["layers"] == 22
    assert target["decode_tokens"] == original["decode_steps"] == 60
    assert target["prefill_tokens"] == original["prefill_tokens"] == 600
    assert all([row["position"] for row in layer] == list(range(600, 660)) for layer in layers)

    counts = count_transfers(layers)
    assert counts["down"]["responses"] == original["logical_responses_before_optimistic_reuse"]["down_responses"]
    assert counts["gate_up"]["responses"] * ROWS_PER_RESPONSE >= original[
        "logical_responses_before_optimistic_reuse"]["gate_up_responses"]
    serial = {key: value["responses"] + CONTROL_CYCLES_PER_BURST * value["bursts"]
              for key, value in counts.items()}
    rate = target["clock_megahertz"] * 1000
    cycles = {
        "one_port_payload_only": sum(value["responses"] for value in counts.values()),
        "one_port_serial_bursts": sum(serial.values()),
        "dual_gate_up_single_down_serial_bursts": Fraction(serial["gate_up"], 2) + serial["down"],
        "dual_gate_up_dual_down_serial_bursts": Fraction(sum(serial.values()), 2),
    }
    assert cycles["dual_gate_up_dual_down_serial_bursts"] < target["milliseconds"] * rate
    assert cycles["dual_gate_up_single_down_serial_bursts"] > target["milliseconds"] * rate

    return {
        "state": "dual_gate_up_only_exceeds_budget_with_current_serial_bursts",
        "paper_clock_megahertz": target["clock_megahertz"],
        "paper_end_to_end_milliseconds": target["milliseconds"],
        "control_cycles_per_burst": CONTROL_CYCLES_PER_BURST,
        "decode_transfer_minimum": counts,
        "minimum_service_milliseconds": {key: float(value / rate) for key, value in cycles.items()},
        "scope": (
            "Lower bounds for the current packed representation on the archived local software workload. "
            "Gate and up each need a burst for every retained group of eight output rows. Down begins "
            "after the feed-forward intermediates are committed. Each lane accepts one response per "
            "clock with ideal readiness. The bounds assume no persistent weight reuse and exclude "
            "prefill, attention, compute, sparse mask fragmentation, and channel imbalance. Two-lane "
            "estimates assume perfectly balanced work within a projection and preserve serialized "
            "bursts per lane."
        ),
        "evidence_sha256": {str(path.relative_to(ROOT)): sha256(path) for path in (
            READ_BUDGET, TARGETS, PAIRED, TRACE, FRAME, PREPARED, SCHEDULE, LOADER, Path(__file__).resolve(),
        )},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = measure()
    with args.output.open("x") as output:
        json.dump(result, output, indent=2, sort_keys=True)
        output.write("\n")
    for name, value in result["minimum_service_milliseconds"].items():
        print(f"{name} {value:.3f} ms")
