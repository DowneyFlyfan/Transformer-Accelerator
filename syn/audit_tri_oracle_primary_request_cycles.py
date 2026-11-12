"""Charge serialized requests and responses to the primary memory-port budget."""

import argparse
from hashlib import file_digest
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def read(path):
    return json.loads(path.read_text())


def audit(cache_path, native_log):
    burst_path = ROOT / "records/wac_weight_burst_schedule_result.json"
    budget_path = ROOT / "records/wac_dual_lane_burst_budget_result.json"
    cache, burst, budget = map(read, (cache_path, burst_path, budget_path))
    assert cache["state"] == "normalized_sign_cache_requests_modeled_with_native_address_control"
    assert cache["native_control"]["ordered_misses_match"] is True
    assert cache["evidence_sha256"][str(burst_path.relative_to(ROOT))] == sha(burst_path)
    assert burst["evidence_sha256"][str(budget_path.relative_to(ROOT))] == sha(budget_path)
    for record in (cache, burst, budget):
        assert all(sha(ROOT / path) == digest for path, digest in record["evidence_sha256"].items())

    chip = ROOT / ".cache/physical/wide_weight_loader/parallel_chip_v3/prepared.json"
    owner = chip.parents[1] / "unified_decoder/tri_oracle_scalar_request_owner.sv"
    mux = ROOT / "verilog/tri_oracle_packed_read_mux.sv"
    bench = ROOT / "verilog/tri_oracle_packed_read_mux_tb.sv"
    for path in (owner, mux):
        assert read(chip)["input_sha256"][str(path.relative_to(ROOT))] == sha(path)
    owner_code, mux_code = owner.read_text(), mux.read_text()
    assert "assign request_valid = !active && client_valid[owner];" in owner_code
    assert "assign active = state == Active;" in owner_code
    assert "if (terminal_transfer) state <= Idle;" in owner_code
    assert "else if (request_valid && request_ready) begin" in owner_code and "state <= Active;" in owner_code
    assert "assign mem_rsp_ready = active && (owner ? wide_rsp_ready : narrow_rsp_ready);" in mux_code
    assert ".terminal_transfer(mem_rsp_valid && mem_rsp_ready && mem_rsp_last)" in mux_code
    log = native_log.read_text()
    assert log.count("Simulation complete via $finish(1)") == 1 and not re.search(r"\*[EF],", log)
    assert log.splitlines().count("PACKED_READ_MUX_PASS requests=4 narrow_beats=3 wide_beats=36 stalled_beats=5") == 1
    assert all(f"file: {path}" in log for path in (owner, mux, bench))

    weights = burst["minimum_primary_weight_beats_after_optimistic_reuse"]
    max_burst = budget["native_burst_probe"]["max_beats"]
    requests = (weights + max_burst - 1) // max_burst
    clock = budget["clock_megahertz"]
    cycle_budget = budget["paper_latency_cycle_budget"]
    logical = burst["uncached_narrow_sign_response_beats"]
    ideal = logical - cache["ideal_command_local_responses_avoided"]
    scenarios = {"uncached": logical, "ideal_command_local": ideal}
    for entries, layouts in cache["summary"].items():
        for layout, result in layouts.items():
            assert ideal <= result["external"] <= logical
            scenarios[f"{entries}_entries_{layout}"] = result["external"]
    # The mux accepts requests only while idle and responses only while
    # active. Every sign miss consumes one request and one response cycle.
    bounds = {}
    for name, sign_beats in scenarios.items():
        cycles = weights + requests + 2 * sign_beats
        bounds[name] = {"sign_reads": sign_beats, "minimum_cycles": cycles,
                        "minimum_ms_at_paper_clock": cycles / (1000 * clock),
                        "fits_paper_cycle_budget": cycles <= cycle_budget}
    paths = (cache_path, burst_path, budget_path, native_log, chip, owner, mux, bench, Path(__file__).resolve())
    return {
        "state": "serialized_primary_memory_port_cycles_bounded",
        "paper_clock_mhz": clock, "paper_latency_cycle_budget": cycle_budget,
        "minimum_primary_weight_response_beats": weights, "minimum_primary_weight_requests": requests,
        "maximum_sign_reads_in_remaining_port_budget": max(0, (cycle_budget - weights - requests) // 2),
        "scenarios": bounds,
        "scope": "Local archived workload and current single-outstanding primary port. Grants maximum-length weight "
                 "bursts, optimistic weight reuse, immediate responses, and zero cost for every other client. "
                 "The ideal command-local scenario eliminates every repeated sign read within each frame.",
        "evidence_sha256": {str(path.relative_to(ROOT)): sha(path) for path in paths},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cache_receipt", type=Path)
    parser.add_argument("native_log", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = audit(args.cache_receipt.resolve(), args.native_log.resolve())
    with args.output.open("x") as output:
        json.dump(result, output, indent=2, sort_keys=True)
        output.write("\n")
    print(result["state"], result["scenarios"]["ideal_command_local"])
