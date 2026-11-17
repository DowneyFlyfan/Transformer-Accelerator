"""Verify response ownership in the placed read core and bound archived traffic."""

import argparse
import json
import mmap
from pathlib import Path
import re

from link_tri_oracle_indexed_whole_chip import module_at, pins, spans
from prepare_tri_oracle_booth_packet_replay import replace_once
from verify_tri_oracle_booth_request_encoder import INTERCONNECT, RTL
from verify_tri_oracle_booth_response_packing import BUDGET, CELLS, ROOT, TERMINAL
from verify_tri_oracle_corrected_booth_roundtrip import digest


CORE = "tri_oracle_shared_read_core"
ENCODER = "tri_oracle_memory_request_tx"
TOP = "tri_oracle_shared_read_link_tb"
BENCH = Path(f"verilog/{TOP}.sv")
REFERENCE = Path("records/tri_oracle_shared_read_link.json")
LINK = Path("records/tri_oracle_corrected_booth_trained_request_link.json")
LANES = Path("records/tri_oracle_corrected_booth_fixed_lane_credit_budget.json")
SIGNS = Path("records/tri_oracle_ranked_sign_workload_bounds.json")
TARGET = Path("records/paper_result_targets.json")
MIXED = Path("records/tri_oracle_corrected_booth_feedforward_replay.json")
WORKLOAD = Path(".cache/memory_response_gearbox/workload_serial.json")


DRAIN_TEST = """    mem_rsp_valid = 0;
    // Each physical response lane owns one transaction until its tail is accepted.
    offer_request(0, 64'h2200000, 6'd2, 1);
    accept_request(0, 1);
    offer_request(1, 64'h2400000, 6'd2, 1);
    accept_request(1, 1);
    offer_request(2, 64'h2500008, 6'd1, 0);
    offer_request(1, 64'h2600000, 6'd1, 1);
    for (int phase = 0; phase < 3; phase++) begin
      // Exercise no response, an accepted nonterminal beat, and a held tail.
      rsp_ready = phase == 2 ? 3'b000 : 3'b111;
      if (phase != 0) begin
        offer_beat(0, 12, phase == 2, 0);
        offer_beat(1, 13, phase == 2, 0);
      end
      @(posedge clk);
      if (tx_valid !== 1'b0 || (|req_ready) !== 1'b0)
        $fatal(1, "PENDING_READ_STARTED_BEFORE_TAIL phase=%0d", phase);
      if ((phase != 0 && rsp_valid !== 3'b011) ||
          (phase == 1 && mem_rsp_ready !== 2'b11) ||
          (phase == 2 && mem_rsp_ready !== 2'b00))
        $fatal(1, "RESPONSE_OWNERSHIP_STIMULUS phase=%0d", phase);
      @(negedge clk);
    end
    // Each lane can make progress as soon as its own terminal beat is accepted.
    rsp_ready[0] = 1;
    @(posedge clk);
    if (!tx_valid || mem_rsp_ready !== 2'b01)
      $fatal(1, "PRIMARY_TAIL_DID_NOT_RELEASE");
    @(negedge clk);
    mem_rsp_valid[0] = 0;
    accept_request(2, 0);
    @(posedge clk);
    if (tx_valid !== 1'b0 || req_ready !== '0)
      $fatal(1, "PRIMARY_TAIL_RELEASED_AUXILIARY");
    @(negedge clk);
    rsp_ready[1] = 1;
    @(posedge clk);
    if (!tx_valid || mem_rsp_ready !== 2'b10)
      $fatal(1, "AUXILIARY_TAIL_DID_NOT_RELEASE");
    @(negedge clk);
    mem_rsp_valid[1] = 0;
    accept_request(1, 1);
    rsp_ready = '1;
    offer_beat(0, 14, 1, 0);
    offer_beat(1, 15, 1, 0);
    @(posedge clk);
    check_response(2, 0, 1);
    check_response(1, 1, 1);
    @(negedge clk);
    mem_rsp_valid = 0;
    $display("PLACED_RESPONSE_OWNERSHIP_PASS blocked_phases=3 independent_tail_releases=2");
"""


def setup():
    evidence = {}

    def pin(path):
        evidence[str(path)] = digest(path)
        return path

    interconnect, link, lanes = (json.loads(pin(path).read_text()) for path in (INTERCONNECT, LINK, LANES))
    cold, = (Path(path) for path in interconnect["evidence_sha256"] if path.endswith("/cold/cold.v"))
    pin(cold)
    assert evidence[str(cold)] == interconnect["evidence_sha256"][str(cold)]
    assert evidence[str(cold)] == link["cold_netlist_sha256"] == lanes["cold_netlist_sha256"]
    assert interconnect["packed_memory_boundary_bits"]["transmit_data"] == 8
    packing_record = Path("records/tri_oracle_corrected_booth_request_encoder.json")
    packing = json.loads(pin(packing_record).read_text())
    for path in (RTL, CELLS):
        assert digest(pin(path)) == packing["evidence_sha256"][str(path)]
    assert packing["encoded_flits_per_read"]["compact"] == 2 and packing["ideal_pad_data_cycles_per_read"]["compact"] == 6
    assert link["pad_beats"] == 3 * link["request_flits"]
    pin(REFERENCE)
    assert digest(pin(BENCH)) == json.loads(REFERENCE.read_text())["evidence_sha256"][str(BENCH)]

    with cold.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as source:
        index = spans(source)
        link_module = module_at(source, index, "tri_oracle_memory_io_link")
        assert pins(link_module, CORE, "reads")["mem_rsp_last"] == b"mem_rsp_last"
        owner = module_at(source, index, CORE)
        encode = pins(owner, ENCODER, "request_tx")
        assert encode["req_valid"] == b"permitted_valid" and encode["req_ready"] == b"req_ready"
        assert b".Q(shared_active)" in owner and b".Q(auxiliary_active)" in owner
        # Innovus eliminated pass-through payload and status connections
        # from this module. The response owner drives valid and ready here.
        assert all(len(re.findall(rb"\b" + name + rb"\b", owner)) == 2
                   for name in (b"rsp_data", b"rsp_last", b"rsp_error"))
        cut = owner + b"\n" + module_at(source, index, ENCODER) + b"\n"
    source = BENCH.read_text()
    revised = replace_once(source, "tri_oracle_shared_read_link dut (.*);",
                           "tri_oracle_shared_read_core dut (.block_new_shared(1'b0), .shared_can_write(), .*);")
    start = revised.index("    logic [511:0] actual;")
    end = revised.index("      $fatal(1, \"LOGICAL_RESPONSE_MISMATCH", start)
    revised = (revised[:start] + "    if (rsp_valid[port_id] !== 1'b1 || mem_rsp_ready[bus_lane] !== ready)\n"
               + revised[end:])
    revised = replace_once(revised, " || faults != 3", "")
    revised = replace_once(revised, " faults=%0d terminal_stalls=", " terminal_stalls=")
    revised = replace_once(revised, "responses, faults, terminal_stalls, simultaneous_responses);",
                           "responses, terminal_stalls, simultaneous_responses);")
    revised = replace_once(revised, "    $finish;", DRAIN_TEST + "    $finish;")
    rx = RTL.read_text()
    first = rx.index("module tri_oracle_memory_request_rx (")
    folder = cold.parents[1] / "request_response_overlap"
    generated = {folder / "placed_read_core.v": cut,
                 folder / "request_receiver.sv": ("`timescale 1ns/1ps\n" + rx[first:]).encode(),
                 folder / f"{TOP}.sv": revised.encode()}
    return folder, generated, evidence, link, lanes


def verify():
    folder, generated, evidence, link, lanes = setup()

    def pin(path):
        evidence[str(path)] = digest(path)
        return path

    for path, contents in generated.items():
        assert pin(path).read_bytes() == contents
    assert int(pin(folder / "exit_status").read_text()) == 0
    log = pin(folder / "xrun.log").read_text()
    assert log.count(TERMINAL) == 1 and not re.search(r"\*(?:E|F|SE),", log)
    assert f"\t-top {TOP}\n" in log
    assert all(f"\t{path.resolve()}\n" in log for path in (*generated, CELLS))
    assert "SHARED_READ_LINK_PASS requests=7 responses=8 terminal_stalls=" in log
    assert log.splitlines().count("PLACED_RESPONSE_OWNERSHIP_PASS blocked_phases=3 independent_tail_releases=2") == 1

    budget, targets, signs, feedforward, workload = (json.loads(pin(path).read_text()) for path in
                                                     (BUDGET, TARGET, SIGNS, MIXED, WORKLOAD))
    assert feedforward["cold_netlist_sha256"] == link["cold_netlist_sha256"]
    assert feedforward["native"]["exit_status"] == 0
    assert evidence[str(WORKLOAD)] == budget["evidence_sha256"][str(WORKLOAD)]
    assert evidence[str(SIGNS)] == budget["evidence_sha256"][str(SIGNS)]
    clock = targets["system_latency"]["clock_megahertz"] * 1000
    window = targets["system_latency"]["milliseconds"] * clock
    assert budget["paper_window_cycles"] == window == signs["paper_latency_cycle_budget"]
    weight_requests = workload["one_request_cycle_per_burst"]
    sign_requests = signs["modeled_sign_line_reads"]
    response_chunks = lanes["weight_and_sign_fragments"]
    assert response_chunks + lanes["compact_index_fragments"] == (
        budget["archived_workload_lower_bounds"]["encoded_weight_fragments"] +
        budget["archived_workload_lower_bounds"]["sign_fragments"])
    # Grant one cycle where a lane's terminal response and its successor's
    # first request byte overlap. Every accepted transaction on that lane
    # still requires five outgoing byte cycles disjoint from response capture.
    requests = weight_requests + sign_requests
    request_cycles = 6 * requests
    disjoint = request_cycles - requests
    floor = (response_chunks + disjoint + 1) // 2
    weight_chunks = response_chunks - budget["archived_workload_lower_bounds"]["sign_fragments"]
    weight_only_floor = (weight_chunks + 5 * weight_requests + 1) // 2
    overlap_required = response_chunks + request_cycles - 2 * window
    assert overlap_required > requests and floor >= weight_only_floor > window
    pin(Path(__file__).resolve().relative_to(ROOT))
    return {
        "state": "placed_read_response_ownership_and_archive_latency_floor_verified",
        "cold_netlist_sha256": link["cold_netlist_sha256"],
        "logical_read_ports": 3,
        "physical_response_lanes": 2,
        "independent_rerequest_release_cases": 2,
        "archived_weight_read_requests": weight_requests,
        "archived_sign_line_read_requests": sign_requests,
        "archived_response_fragments_after_compact_indexes": response_chunks,
        "minimum_request_pad_cycles_assuming_all_compact": request_cycles,
        "maximum_same_lane_request_response_overlap_cycles_granted": requests,
        "required_same_lane_request_response_overlap_cycles": overlap_required,
        "paper_window_cycles": window,
        "minimum_weight_only_transport_ms_at_paper_clock": weight_only_floor / clock,
        "minimum_read_transport_cycles": floor,
        "minimum_read_transport_ms_at_paper_clock": floor / clock,
        "scope": "Placed read ownership exercised at the mapped request encoder and internal response "
                 "boundary. Uses archived weight and sign requests, compact indices, perfect traffic "
                 "balance, and ideal pad service. It excludes computation, writes, attention, and "
                 "off-chip delays. Traffic estimates are conditional on the archived transfer granularity.",
        "evidence_sha256": evidence,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "verify"))
    args = parser.parse_args()
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").is_file()
    if args.phase == "prepare":
        folder, generated, _, _, _ = setup()
        folder.mkdir()
        for path, contents in generated.items():
            path.write_bytes(contents)
        print(folder)
    else:
        print(json.dumps(verify(), indent=2, sort_keys=True))
