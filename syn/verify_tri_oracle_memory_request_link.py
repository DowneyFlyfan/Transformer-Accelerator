"""Replay the cold chip's mapped weight cut through the synthesized request link."""

import argparse
import json
from pathlib import Path
import re
import shlex

from measure_tri_oracle_serial_memory_requests import (INDEXED_FIXTURE, SERIAL_REQUESTS, digest, read, replace)


ROOT = Path(".cache/physical/whole_chip_xcelium_speed")
REFERENCE = ROOT / "request_serialization"
RECORDS = Path("records")

CUT_LINK = """  logic wire_valid, wire_ready;
  logic [21:0] wire_data;
  logic [1:0] decoded_valid, decoded_ready;
  logic [1:0][63:0] decoded_address;
  logic [1:0][5:0] decoded_length;
  int compact_requests, full_requests, packet_flits_left;

  tri_oracle_memory_request_tx request_tx (
    .clk, .rst_n, .req_valid, .req_ready, .req_address, .req_length,
    .tx_valid(wire_valid), .tx_ready(wire_ready), .tx_data(wire_data)
  );
  tri_oracle_memory_request_rx request_rx (
    .clk, .rst_n, .rx_valid(wire_valid), .rx_ready(wire_ready), .rx_data(wire_data),
    .req_valid(decoded_valid), .req_ready(decoded_ready),
    .req_address(decoded_address), .req_length(decoded_length)
  );
  always @(posedge clk) if (rst_n && wire_valid && wire_ready) begin
    if (packet_flits_left != 0)
      packet_flits_left--;
    else if (wire_data[0]) begin
      compact_requests++;
      packet_flits_left = 1;
    end else begin
      full_requests++;
      packet_flits_left = 3;
    end
  end
"""


def make_bench(text):
    text = replace(text, SERIAL_REQUESTS, CUT_LINK)
    text = replace(text, "assign req_ready[lane]=request_mode==0 ? !active[lane] && cycle%5!=lane :\n"
                         "        pending && lane_selected==lane && flits_remaining==1;",
                   "assign decoded_ready[lane]=!active[lane] && cycle%5!=lane;")
    start = "      if (req_valid[lane] && req_ready[lane]) begin"
    begin = text.index(start)
    end = text.index("      if(rsp_valid[lane]", begin)
    memory = text[begin:end]
    for old, new in (("req_valid", "decoded_valid"), ("req_ready", "decoded_ready"),
                     ("req_address", "decoded_address"), ("req_length", "decoded_length")):
        memory = memory.replace(old, new)
    text = text[:begin] + memory + text[end:]
    return replace(text, '      $display("MEMORY_REQUEST_FORMAT mode=%0d compact=%0d full=%0d",\n'
                         "               request_mode,packed_requests,full_requests);",
                   '      $display("MEMORY_REQUEST_HARDWARE_FIXTURE compact=%0d full=%0d",\n'
                   "               compact_requests,full_requests);")


def prepare(output, previous):
    bench = REFERENCE / "compact_index_replay_tb.sv"
    cut = REFERENCE / "packed_weight_cut.v"
    assert all(digest(path) == previous["evidence_sha256"][str(path)] for path in (bench, cut))
    with (output / bench.name).open("x") as stream:
        stream.write(make_bench(bench.read_text()))


def summarize(output, previous, previous_path):
    proof = {}

    def pin(path):
        proof[str(path)] = digest(path)
        return path

    def replay(path, sources):
        log = pin(path).read_text()
        history = pin(path.with_name("xrun.history")).read_text()
        command = re.findall(r"(?m)^s\d+\([^\n]+\):\s+xrun (.+)$", history)[-1]
        inputs = {(path.parent / arg).resolve() for arg in shlex.split(command) if arg.endswith((".sv", ".v"))}
        assert all(source.resolve() in inputs for source in sources)
        assert log.count("Simulation complete via $finish(1)") == 1 and not re.search(r"\*[EF],", log)
        return log

    rtl = Path("verilog/tri_oracle_memory_request_link.sv")
    unit_bench = Path("verilog/tri_oracle_memory_request_link_tb.sv")
    tx_netlist = output / "genus_tx/netlist.v"
    rx_netlist = output / "genus_rx/netlist.v"
    cell_models = pin(Path(".cache/physical/library/tcbn28hpcplusbwp12t40p140.v"))
    liberty = pin(cell_models.with_name("tcbn28hpcplusbwp12t40p140ssg0p9v125c.lib"))
    assert proof[str(cell_models)] == previous["evidence_sha256"][str(cell_models)]
    for path in (previous_path, Path(__file__).resolve(), Path("syn/tri_oracle_synthesize_memory_request_link.tcl"),
                 rtl, unit_bench):
        pin(path)
    baselines = {}
    for mode, sources in (("rtl", (rtl, unit_bench)), ("mapped", (tx_netlist, rx_netlist, cell_models, unit_bench))):
        log = replay(output / mode / "console.log", sources)
        fields, = re.findall(r"(?m)^MEMORY_REQUEST_LINK_PASS (.*)$", log)
        baselines[mode] = dict((key, int(value)) for key, value in (word.split("=") for word in fields.split()))
    assert baselines["mapped"] == baselines["rtl"]
    assert baselines["mapped"]["packets"] == 246

    timing = {}
    for endpoint in ("tx", "rx"):
        folder = output / f"genus_{endpoint}"
        master = f"tri_oracle_memory_request_{endpoint}"
        assert f"TRI_ORACLE_MEMORY_REQUEST_LINK_GENUS_FINISHED {master}" in pin(folder / "console.log").read_text()
        assert "No unresolved references" in pin(folder / "mapped_check.rpt").read_text()
        netlist = pin(folder / "netlist.v")
        assert re.search(rf"(?m)^module {master}\s*\(", netlist.read_text())
        report = pin(folder / "timing.rpt").read_text()
        worst = min(map(int, re.findall(r"Slack:=\s+(-?\d+)", report)))
        assert worst > 0
        area = pin(folder / "area.rpt").read_text()
        assert liberty.stem in area and "Operating conditions:   ssg0p9v125c" in area
        counts, = re.findall(rf"(?m)^\s*{master}\s+.+?\s+(\d+)\s+([\d.]+)(?:\s|$)", area)
        timing[endpoint] = {"worst_setup_slack_ps": worst, "mapped_cells": int(counts[0]),
                            "cell_area_um2": float(counts[1])}
        constraints = pin(folder / "constraints.sdc").read_text()
        assert re.search(r"(?m)^create_clock .* -period 1\.72414 ", constraints)

    bench = pin(output / "compact_index_replay_tb.sv")
    original = pin(REFERENCE / bench.name)
    assert proof[str(original)] == previous["evidence_sha256"][str(original)]
    assert bench.read_text() == make_bench(original.read_text())
    cut = pin(REFERENCE / "packed_weight_cut.v")
    assert proof[str(cut)] == previous["evidence_sha256"][str(cut)]
    ingress = pin(Path(".cache/compact_index_io/genus/netlist.v"))
    assert proof[str(ingress)] == previous["evidence_sha256"][str(ingress)]
    sources = (cut, bench, tx_netlist, rx_netlist, cell_models, ingress)
    log = replay(output / "fixture/console.log", sources)
    rejected = replay(output / "fixture_bad/console.log", sources)
    assert re.search(r"(?m)^COMPACT_INDEX_BAD_RESERVED_REJECTED compact0=1 compact1=1$", rejected)
    packets, = re.findall(r"(?m)^MEMORY_REQUEST_HARDWARE_FIXTURE compact=(\d+) full=(\d+)$", log)
    compact, full = map(int, packets)
    assert compact == previous["down_projection_fixture"]["aligned_address"]["compact_requests"] and full == 0
    assert "STAGED_INDEXED_DOWN_MATRIX_PASS cases=78 exact_bytes=11534336" in log
    assert "INDEXED_WEIGHT_MODE_PASS switched_to_raw=1" in log
    cycles, = re.findall(r"(?m)^DUAL_GROUP_MATRIX_WRITES writes=90112 cycles=(\d+)$", log)
    for name in ("down_index.bin", "down_payload.bin"):
        fixture = pin(INDEXED_FIXTURE / name)
        assert proof[str(fixture)] == previous["evidence_sha256"][str(fixture)]
        assert all((output / run / name).resolve() == fixture.resolve() for run in ("fixture", "fixture_bad"))
    return {
        "state": "mapped_request_link_and_trained_weight_replay_verified",
        "cold_netlist_sha256": previous["cold_netlist_sha256"],
        "shared_request_wire_data_bits": 22,
        "unit_replay": baselines["mapped"],
        "trained_down_projection": {"tiles": 78, "exact_weight_bytes": 11534336,
                                    "compact_requests": compact, "full_requests": full, "cycles": int(cycles),
                                    "reserved_index_errors_rejected": 2},
        "synthesis": {"target_period_ns": 1.72414, "slow_corner": "0.9 V, 125 C", "endpoints": timing},
        "scope": "Synthesized wide-read request endpoints and a mapped down projection cut in Xcelium. Timing "
                 "checks were disabled for mapped replay. Narrow reads, memory writes, physical pads, the external "
                 "memory controller and complete model execution require separate evidence. Synthesis timing "
                 "excludes placement and routing.",
        "evidence_sha256": proof,
    }


if __name__ == "__main__":
    assert __debug__
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "summarize"))
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    previous_path = RECORDS / "tri_oracle_serial_memory_requests.json"
    previous = read(previous_path)
    if args.phase == "prepare":
        prepare(args.directory, previous)
    else:
        print(json.dumps(summarize(args.directory, previous, previous_path), indent=2, sort_keys=True))
