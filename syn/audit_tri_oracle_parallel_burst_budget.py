"""Lower-bound the packed weight transfer time using the two-lane loader's handshake."""

import argparse
from fractions import Fraction
import json
from math import ceil
from pathlib import Path
import re

from check_tri_oracle_paper300_gate import PAPER_RELATIVE, PAPER_SHA256, sha


ROOT = Path(__file__).resolve().parents[1]
WIDE = ROOT / ".cache/physical/wide_weight_loader"
NATIVE_PASS = "WEIGHT_BURST_BUDGET_PASS"


def read(path):
    return json.loads(path.read_text())


def audit():
    model = ROOT / "records/wac_packed_workload_traffic_result.json"
    batches = ROOT / "records/wac_channel_packing_bound_result.json"
    capacity = ROOT / "records/wac_assembled_context_chip_structure_result.json"
    paper = ROOT / PAPER_RELATIVE
    targets = ROOT / "records/paper_result_targets.json"
    assert sha(paper) == PAPER_SHA256
    latency = read(targets)["system_latency"]
    traffic, workload, memory = map(read, (model, batches, capacity))
    assert traffic["state"] == "normalized_workload_packed_weight_traffic_independently_reconciled"
    assert workload["state"] == "fixed_predictor_channel_packing_upper_bound_measured"
    assert memory["state"] == "assembled_mapped_chip_local_architecture_and_memory_census_verified"
    assert workload["evidence_sha256"][str(model.relative_to(ROOT))] == sha(model)
    assert traffic["evidence_sha256"][str(targets.relative_to(ROOT))] == sha(targets)
    assert latency["external_memory_access_included"]
    assert (traffic["prefill_tokens"], traffic["decode_steps"]) == (latency["prefill_tokens"], latency["decode_tokens"])
    weight_bytes = traffic["combined_sixteen_row_prefill_and_single_row_decode"]["with_predictor_weight_bytes"]
    assert weight_bytes == sum(item["with_predictor_weight_bytes"] for item in
                               (traffic["prefill_by_batch_size"]["16"], traffic["decode"]))
    batch_count = workload["combined"]["batches"]
    assert batch_count == workload["prefill"]["batches"] + workload["decode"]["batches"]
    assert workload["prefill_batch_rows"] == 16 and workload["decode_batch_rows"] == 1
    macros = memory["structure"]["memory"]
    capacity_bytes = macros["compiled_bytes"]
    assert capacity_bytes == sum(item["bytes"] for item in macros["by_master"].values())

    chip = WIDE / "parallel_chip_v3/tri_oracle_chip_command_layer.sv"
    tensor = chip.with_name("tri_oracle_batched_tensor390.sv")
    loader = ROOT / "verilog/tri_oracle_wide_weight_loader.sv"
    parallel = ROOT / "verilog/tri_oracle_parallel_weight_loader.sv"
    candidate_path = chip.with_name("prepared.json")
    candidate = read(candidate_path)
    for path in (chip, tensor, loader, parallel):
        assert candidate["input_sha256"][str(path.relative_to(ROOT))] == sha(path), path
    response_ports = ("rsp_data", "aux_rsp_data")
    widths = [int(msb) + 1 for msb, name in
              re.findall(r"(?m)^  input logic \[(\d+):0\] (\w+),$", chip.read_text())
              if name in response_ports]
    assert widths == [512, 512]
    assert ".rsp_valid({aux_rsp_valid,wide_rsp_valid})" in tensor.read_text()
    assert re.search(r"for \(genvar lane = 0; lane < 2; lane\+\+\) begin", parallel.read_text())
    limit, = re.findall(r"end_word > 7'd(\d+)", loader.read_text())

    bench = ROOT / "verilog/tri_oracle_weight_burst_budget_tb.sv"
    log = WIDE / "burst_budget/console.log"
    text = log.read_text()
    fields, = re.findall(rf"(?m)^{NATIVE_PASS} (.+)$", text)
    native = {name: int(value) for name, value in (word.split("=") for word in fields.split())}
    assert native["max_beats"] == int(limit) and native["payload_beats"] == 2 * int(limit)
    assert native["oversize_rejected"] == 1 and native["inter_burst_cycles"] == 3
    assert text.count("Simulation complete via $finish(1)") == 1 and not re.search(r"\*[EF],", text)
    assert all(f"file: {path}" in text for path in (bench, loader))

    # Give every batch the entire SRAM capacity as preexisting reusable weights.
    reuse_bytes = batch_count * capacity_bytes
    remaining = weight_bytes - reuse_bytes
    bytes_per_beat = widths[0] // 8
    busiest_lane_beats = ceil(Fraction(remaining, len(widths) * bytes_per_beat))
    longest_burst = int(limit)
    burst_count = ceil(Fraction(busiest_lane_beats, longest_burst))
    gap = native["inter_burst_cycles"]
    # The first and last bursts need no leading or trailing idle time in this bound.
    cycle_floor = busiest_lane_beats + (burst_count - 1) * gap
    frequency = latency["clock_megahertz"] * 10**6
    cycle_budget = latency["milliseconds"] * frequency // 1000
    bursts_in_budget = (cycle_budget - busiest_lane_beats) // gap + 1
    assert 0 < bursts_in_budget < burst_count and cycle_floor > cycle_budget
    evidence = (model, batches, capacity, targets, paper, candidate_path, chip, tensor,
                loader, parallel, bench, log, Path(__file__))
    return {
        "state": "dual_lane_weight_transport_exceeds_paper_latency_on_local_trace",
        "paper_latency_ms": latency["milliseconds"],
        "clock_megahertz": latency["clock_megahertz"],
        "paper_latency_cycle_budget": cycle_budget,
        "projected_weight_bytes": weight_bytes,
        "optimistic_reuse_bytes": reuse_bytes,
        "minimum_payload_beats_on_busiest_lane": busiest_lane_beats,
        "payload_only_latency_floor_ms": float(Fraction(1000 * busiest_lane_beats, frequency)),
        "minimum_weight_cycles_with_burst_gaps": cycle_floor,
        "minimum_weight_latency_with_burst_gaps_ms": float(Fraction(1000 * cycle_floor, frequency)),
        "minimum_burst_length_to_fit_paper_budget_at_measured_gap": ceil(Fraction(busiest_lane_beats, bursts_in_budget)),
        "native_burst_probe": native,
        "scope": "One archived local 600-prefill and 60-decode trajectory with current uncompressed packed weights. "
                 "The bound gives both lanes ideal balance and immediate responses, and counts only weight transport.",
        "evidence_sha256": {str(path.relative_to(ROOT)): sha(path) for path in evidence},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    result = audit()
    with parser.parse_args().output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(result["state"], result["minimum_weight_latency_with_burst_gaps_ms"], "ms")
