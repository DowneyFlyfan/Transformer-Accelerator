"""Check the jointly mapped capture and both memory response decoders."""

import argparse
import json
from pathlib import Path
import re

from link_tri_oracle_chip_packet_io import ROOT
from measure_tri_oracle_serial_memory_requests import digest, read, replace
from verify_tri_oracle_compact_response_lane import MAPPED_IO
from verify_tri_oracle_dual_edge_memory_capture import RTL as CAPTURE
from verify_tri_oracle_host_rotary import MODEL
from verify_tri_oracle_host_status import arguments


TOP = "tri_oracle_dual_edge_memory_ingress"
DESIGN = Path(f"verilog/{TOP}.sv")
SYNTH = Path(f"syn/tri_oracle_synthesize_dual_edge_memory_ingress.tcl")
BASE = ROOT / "dual_edge_capture"
REPLAY = "tri_oracle_compact_response_lane_joint_tb"
BURST_TOP = f"{TOP}_burst_tb"
BURST_TEST = Path(f"verilog/{BURST_TOP}.sv")


def joint_bench(source):
    source = replace(source, "module tri_oracle_compact_response_lane_captured_tb;", f"module {REPLAY};")
    begin = source.index("  logic [1:0] in_valid,")
    end = source.index("  logic [1:0] pad_valid", begin)
    source = replace(source, source[begin:end], "")
    begin = source.index("  tri_oracle_dual_edge_memory_capture capture (")
    end = source.index("  int checks=", begin)
    source = replace(source, source[begin:end], "")
    begin = source.index("  for (genvar lane=0; lane<2; lane++)")
    end = source.index("  function automatic logic [447:0]", begin)
    return replace(source, source[begin:end], f"""  {TOP} ingress (
    .clk,.rst_n,.pad_valid,.pad_ready,.pad_last,.pad_error,.pad_compact,.pad_words,.pad_data,
    .out_valid(mem_rsp_valid),.out_ready(mem_rsp_ready),.out_last(mem_rsp_last),
    .out_error(mem_rsp_error),.out_data(mem_rsp_data)
  );

""")


def prepare(directory, phase, pin):
    captured = read(pin(Path("records/tri_oracle_dual_edge_memory_capture.json")))["evidence_sha256"]
    compact = read(pin(Path("records/tri_oracle_compact_response_lane.json")))["evidence_sha256"]
    before = BASE / "coupled_tb.sv"
    for item in (CAPTURE, before, MODEL, MAPPED_IO):
        pin(item, captured[str(item)])
    for item in (ROOT / "compact_responses/tri_oracle_compact_response_lane.sv",
                 Path("verilog/tri_oracle_memory_response_gearbox.sv")):
        pin(item, compact[str(item)])
    pin(SYNTH)
    pin(DESIGN)
    bench = directory / "joint_tb.sv"
    text = joint_bench(before.read_text())
    if phase == "prepare":
        with bench.open("x") as stream:
            stream.write(text)
    else:
        assert pin(bench).read_text() == text
    return bench


def verify(directory, bench, pin):
    mapped = directory / "joint_genus/netlist.v"
    native = directory / "joint_mapped"
    argv = arguments(pin(native / "xrun.history"))
    assert argv[argv.index("-top") + 1] == REPLAY
    assert all(str(pin(path).resolve()) in argv for path in (mapped, bench, MODEL, MAPPED_IO))
    log = pin(native / "console.log").read_text()
    (overlap,) = re.findall(r"(?m)^COMPACT_RESPONSE_LANE_PASS wide=2 indexes=2 scalar=3 write_acks=1 overlap=(\d+)$", log)
    assert int(overlap) > 0 and log.count("Simulation complete via $finish(1)") == 1
    assert not re.search(r"\*[EF],", log)
    burst = directory / "joint_burst"
    argv = arguments(pin(burst / "xrun.history"))
    assert argv[argv.index("-top") + 1] == BURST_TOP
    assert all(str(pin(path).resolve()) in argv for path in (mapped, MODEL, BURST_TEST))
    log = pin(burst / "console.log").read_text()
    (concurrent, cycles), = re.findall(
        r"(?m)^DUAL_EDGE_INGRESS_BURST_PASS rising_chunks=64 falling_chunks=64 beats_per_lane=56 "
        r"overlap=(\d+) delivery_cycles=(\d+)$", log)
    assert int(concurrent) >= 48 and int(cycles) <= 65
    assert log.count("Simulation complete via $finish(1)") == 1 and not re.search(r"\*[EF],", log)
    mapping = directory / "joint_genus"
    assert "TRI_ORACLE_DUAL_EDGE_INGRESS_GENUS_FINISHED" in pin(mapping / "console.log").read_text()
    assert "No unresolved references" in pin(mapping / "mapped_check.rpt").read_text()
    constraints = pin(mapping / "constraints.sdc").read_text()
    assert re.search(r"(?m)^create_clock .* -period 1\.72414 -waveform \{0\.0 0\.86207\} ", constraints)
    assert "-clock_fall" in constraints
    timing = {}
    for group in ("timing", "falling_ready_timing"):
        report = pin(mapping / f"{group}.rpt").read_text()
        slacks = [int(value) for value in re.findall(r"Slack:=\s+(-?\d+)", report)]
        assert slacks and min(slacks) >= 0, group
        timing[group] = min(slacks)
    direct = read(pin(directory / "direct_ingress.json"))
    baseline = pin(directory / "direct_genus/timing.rpt", direct["evidence_sha256"][str(mapping / "timing.rpt")])
    pin(directory / "direct_ingress.sv", direct["evidence_sha256"][str(DESIGN)])
    direct_slack = min(map(int, re.findall(r"Slack:=\s+(-?\d+)", baseline.read_text())))
    assert direct_slack == direct["standalone_setup_slack_ps"]["timing"] == 29
    assert timing["timing"] > direct_slack
    assert int(cycles) == direct["burst_delivery_cycles"] + 1
    area = pin(mapping / "area.rpt").read_text()
    (cells, square_micrometers), = re.findall(rf"(?m)^\s*{TOP}\s+NA\s+(\d+)\s+([\d.]+)", area)
    pads = read(pin(directory / "pad_arcs_recheck.json"))
    assert pads == read(pin(Path("records/tri_oracle_installed_pad_timing.json")))
    fastest_pad_output = {name: float(data["transmit"]["minimum_delay_ns"])
                          for name, data in pads["corners"].items()}
    assert all(delay > pads["paper_clock_period_ns"] / 2 for delay in fastest_pad_output.values())
    pin(Path(__file__).resolve().relative_to(Path.cwd()))
    return {"state": "joint_mapped_dual_edge_ingress_replayed_with_existing_memory_endpoint",
            "standalone_setup_slack_ps": timing, "overlapping_ack_and_read_cycles": int(overlap),
            "direct_capture_minimum_setup_slack_ps": direct_slack,
            "mapped_cells": int(cells), "mapped_cell_area_um2": float(square_micrometers),
            "characterized_minimum_pad_output_delays_ns": fastest_pad_output,
            "uninterrupted_chunks_per_edge": 64, "complete_beats_per_lane": 56,
            "burst_delivery_cycles": int(cycles), "simultaneous_response_cycles": int(concurrent),
            "scope": "Joint capture and response decoder synthesis and functional simulation against "
                     "the existing endpoint. Pad loading, board timing, hold timing across corners, "
                     "and full-chip routed clock skew remain open."}


if __name__ == "__main__":
    assert __debug__
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "verify"))
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    evidence = {}

    def pin(path, expected=None):
        if str(path) not in evidence:
            evidence[str(path)] = digest(path)
        assert expected is None or evidence[str(path)] == expected, path
        return path

    bench = prepare(args.directory, args.phase, pin)
    if args.phase == "verify":
        print(json.dumps(verify(args.directory, bench, pin) | {"evidence_sha256": evidence},
                         indent=2, sort_keys=True))
