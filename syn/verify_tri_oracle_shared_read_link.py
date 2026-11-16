"""Verify two shared response lanes with the request link and mapped weight cut."""

import argparse
import json
import mmap
from pathlib import Path
import re
import shlex

from audit_tri_oracle_mapped_redundancy import TOP
from link_tri_oracle_indexed_whole_chip import module_at, signature, spans
from measure_tri_oracle_serial_memory_requests import INDEXED_FIXTURE, digest, read, replace


ROOT = Path(".cache/physical/whole_chip_xcelium_speed")
READ_REQUEST = ROOT / "memory_request_all_reads"
CUT = ROOT / "request_serialization/packed_weight_cut.v"
STIMULUS = READ_REQUEST / "compact_index_replay_tb.sv"
TB = Path("verilog/tri_oracle_shared_read_link_tb.sv")
RTL = Path("verilog/tri_oracle_shared_read_link.sv")
REQUEST_RTL = Path("verilog/tri_oracle_memory_request_link.sv")
CELLS = Path(".cache/physical/library/tcbn28hpcplusbwp12t40p140.v")
INGRESS = Path(".cache/compact_index_io/genus/netlist.v")
RECORDS = Path("records")


def shared_bench(text):
    text = replace(text, "  logic decoded_wide;", """  logic decoded_wide;
  logic [1:0] mem_rsp_valid, mem_rsp_ready, mem_rsp_last, mem_rsp_error;
  logic [1:0][511:0] mem_rsp_data;
  logic [2:0] routed_valid, routed_last, routed_error;
  logic [1087:0] routed_data;
  assign rsp_valid = routed_valid[1:0];
  assign rsp_last = routed_last[1:0];
  assign rsp_error = routed_error[1:0];
  assign rsp_data = routed_data[1023:0];""")
    text = replace(text, "tri_oracle_memory_request_tx request_tx (",
                   "tri_oracle_shared_read_link request_tx (")
    text = replace(text, ".primary_wide(1'b1),\n    .tx_valid",
                   """.primary_wide(1'b1),
    .rsp_valid(routed_valid), .rsp_ready({1'b0, rsp_ready}), .rsp_last(routed_last),
    .rsp_error(routed_error), .rsp_data(routed_data),
    .mem_rsp_valid, .mem_rsp_ready, .mem_rsp_last, .mem_rsp_error, .mem_rsp_data,
    .tx_valid""")
    for name in ("valid", "ready", "last", "error", "data"):
        text = replace(text, f".out_{name}(rsp_{name}[lane])", f".out_{name}(mem_rsp_{name}[lane])")
    return text


def check_fixture_inputs(request):
    rx = READ_REQUEST / "genus_rx/netlist.v"
    liberty = CELLS.with_name("tcbn28hpcplusbwp12t40p140ssg0p9v125c.lib")
    evidence = {str(path): digest(path) for path in (STIMULUS, CUT, rx, CELLS, liberty, INGRESS, REQUEST_RTL)}
    assert all(actual == request["evidence_sha256"][name] for name, actual in evidence.items())
    return rx, evidence


def check_boundary(pin, cold_hash):
    placement = read(pin(RECORDS / "tri_oracle_repacked_whole_chip_cold_reload.json"))
    cold, = (Path(name) for name in placement["evidence_sha256"] if name.endswith("/cold.v"))
    assert digest(cold) == placement["cold_netlist_sha256"] == cold_hash
    with cold.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
        ports = signature(module_at(data, spans(data), TOP))
    widths = {}
    for name, prefix, width in (("primary", "", 512), ("auxiliary", "aux_", 512), ("projection", "proj_", 64)):
        assert ports[prefix + "rsp_data"] == (b"input", f"[{width - 1}:0]".encode())
        assert ports[prefix + "rsp_ready"] == (b"output", b"")
        assert all(ports[prefix + "rsp_" + flag] == (b"input", b"") for flag in ("valid", "last", "error"))
        widths[name] = width
    return widths


def verify(output, request_path):
    proof = {}

    def pin(path):
        proof[str(path)] = digest(path)
        return path

    def replay(folder, sources):
        logfile = output / folder / "console.log"
        log = pin(logfile).read_text()
        history = pin(logfile.with_name("xrun.history")).read_text()
        command = re.findall(r"(?m)^s\d+\([^\n]+\):\s+xrun (.+)$", history)[-1]
        inputs = {(logfile.parent / arg).resolve() for arg in shlex.split(command) if arg.endswith((".sv", ".v"))}
        assert all(source.resolve() in inputs for source in sources)
        assert log.count("Simulation complete via $finish(1)") == 1 and not re.search(r"\*[EF],", log)
        return log

    request = read(pin(request_path))
    rx, fixture_inputs = check_fixture_inputs(request)
    proof.update(fixture_inputs)
    for path in (TB, RTL, Path(__file__).resolve(), Path("syn/tri_oracle_synthesize_memory_request_link.tcl")):
        pin(path)
    mapped = pin(output / "genus/netlist.v")
    contents = mapped.read_bytes()
    mapped_ports = signature(module_at(contents, spans(contents), "tri_oracle_shared_read_link"))
    assert mapped_ports["mem_rsp_data"] == (b"input", b"[1023:0]")
    assert mapped_ports["mem_rsp_ready"] == (b"output", b"[1:0]")
    assert all(mapped_ports["mem_rsp_" + flag] == (b"input", b"[1:0]") for flag in ("valid", "last", "error"))
    assert mapped_ports["tx_data"] == (b"output", b"[21:0]")
    assert "TRI_ORACLE_MEMORY_REQUEST_LINK_GENUS_FINISHED tri_oracle_shared_read_link" in pin(
        output / "genus/console.log").read_text()
    assert "No unresolved references" in pin(output / "genus/mapped_check.rpt").read_text()
    assert re.search(r"(?m)^create_clock .* -period 1\.72414 ", pin(output / "genus/constraints.sdc").read_text())
    slack = min(map(int, re.findall(r"Slack:=\s+(-?\d+)", pin(output / "genus/timing.rpt").read_text())))
    assert slack > 0
    area = pin(output / "genus/area.rpt").read_text()
    assert "Operating conditions:   ssg0p9v125c" in area
    sizes, = re.findall(r"(?m)^\s*tri_oracle_shared_read_link\s+NA\s+(\d+)\s+([\d.]+)", area)

    source_log = replay("rtl", (RTL, REQUEST_RTL, TB))
    mapped_log = replay("mapped", (mapped, rx, CELLS, TB))
    unit = r"(?m)^SHARED_READ_LINK_PASS (.+)$"
    fields, = re.findall(unit, mapped_log)
    assert re.findall(unit, source_log) == [fields]
    directed = {key: int(value) for key, value in (item.split("=") for item in fields.split())}
    assert directed["requests"] == 7 and directed["responses"] == 8
    assert directed["faults"] == 3 and directed["terminal_stalls"] >= 2 and directed["simultaneous"] == 1

    bench = pin(output / STIMULUS.name)
    assert bench.read_text() == shared_bench(STIMULUS.read_text())
    log = replay("fixture", (CUT, INGRESS, mapped, rx, CELLS, bench))
    packets, = re.findall(r"(?m)^MEMORY_REQUEST_HARDWARE_FIXTURE compact=(\d+) full=0$", log)
    cycles, = re.findall(r"(?m)^DUAL_GROUP_MATRIX_WRITES writes=90112 cycles=(\d+)$", log)
    expected = request["trained_down_projection"]
    assert int(packets) == expected["compact_requests"]
    assert f"STAGED_INDEXED_DOWN_MATRIX_PASS cases={expected['tiles']} exact_bytes={expected['exact_weight_bytes']}" in log
    assert "INDEXED_WEIGHT_MODE_PASS switched_to_raw=1" in log
    for name in ("down_index.bin", "down_payload.bin"):
        fixture = pin(INDEXED_FIXTURE / name)
        assert proof[str(fixture)] == request["evidence_sha256"][str(fixture)]
        assert (output / "fixture" / name).resolve() == fixture.resolve()

    cold_hash = request["cold_netlist_sha256"]
    widths = check_boundary(pin, cold_hash)
    pads = read(pin(RECORDS / "tri_oracle_cold_memory_boundary.json"))
    assert pads["cold_netlist_sha256"] == cold_hash
    wires = request["shared_request_wire_data_bits"]
    remaining = pads["narrow_host_candidate"]["sites_after_host_clock_reset_and_512_receive_pads"]
    used = wires + 2 + 2 * 4
    assert remaining == used
    return {
        "state": "mapped_shared_response_link_and_trained_weight_replay_verified",
        "cold_netlist_sha256": cold_hash,
        "cold_chip_response_bits": widths,
        "illustrative_signal_pad_budget": {"response_data_sites": 512, "response_control_sites": 8,
                                          "request_data_and_control_sites": wires + 2, "sites_left": remaining - used},
        "mapped": {"cells": int(sizes[0]), "cell_area_um2": float(sizes[1]),
                   "worst_setup_slack_ps": slack, "target_period_ns": 1.72414},
        "directed_replay": directed,
        "trained_down_projection": {"tiles": expected["tiles"], "exact_weight_bytes": expected["exact_weight_bytes"],
                                    "requests": int(packets), "cycles": int(cycles),
                                    "cycle_change_with_response_ownership": int(cycles) - expected["cycles"]},
        "scope": "The on-chip request serializer and response owner passed mapped replay with the decoded requests "
                 "and two testbench memory-response lanes. The pin budget assumes two data bits per receive site "
                 "per clock. Writes, package, power, physical capture and full-chip timing remain open.",
        "evidence_sha256": proof,
    }


if __name__ == "__main__":
    assert __debug__
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "verify"))
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    request_path = RECORDS / "tri_oracle_mapped_memory_request_link.json"
    if args.phase == "prepare":
        check_fixture_inputs(read(request_path))
        with (args.directory / STIMULUS.name).open("x") as stream:
            stream.write(shared_bench(STIMULUS.read_text()))
    else:
        print(json.dumps(verify(args.directory, request_path), indent=2, sort_keys=True))
