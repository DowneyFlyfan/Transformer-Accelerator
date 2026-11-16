"""Check edge capture and replay the mapped compact memory endpoint through it."""

import argparse
import json
from pathlib import Path
import re

from link_tri_oracle_chip_packet_io import ROOT
from measure_tri_oracle_serial_memory_requests import digest, read, replace
from verify_tri_oracle_compact_response_lane import MASTER as LANE, MAPPED_IO, TEST as LANE_TEST
from verify_tri_oracle_host_rotary import MODEL
from verify_tri_oracle_host_status import arguments


TOP = "tri_oracle_dual_edge_memory_capture"
RTL = Path(f"verilog/{TOP}.sv")
TEST = Path(f"verilog/{TOP}_tb.sv")
COMPACT = ROOT / "compact_responses/genus/netlist.v"
SYNTH = Path(f"syn/tri_oracle_synthesize_dual_edge_memory_capture.tcl")


def coupled_bench(text):
    text = replace(text, f"module {LANE}_tb;", f"module {LANE}_captured_tb;")
    old = """  logic [1:0] in_valid=0,in_ready,in_last=0,in_error=0,in_compact=0;
  logic [1:0][2:0] in_words=0;
  logic [1:0][447:0] in_data=0;"""
    text = replace(text, old, """  logic [1:0] in_valid,in_ready,in_last,in_error,in_compact;
  logic [1:0][2:0] in_words;
  logic [1:0][447:0] in_data;
  logic [1:0] pad_valid=0,pad_ready,pad_last=0,pad_error=0,pad_compact=0;
  logic [1:0][2:0] pad_words=0;
  logic [1:0][447:0] peer_data=0;
  wire [447:0] pad_data;
  assign #2 pad_data = clk ? peer_data[1] : peer_data[0];
  tri_oracle_dual_edge_memory_capture capture (
    .clk,.rst_n,.pad_valid,.pad_ready,.pad_last,.pad_error,.pad_compact,.pad_words,.pad_data,
    .out_valid(in_valid),.out_ready(in_ready),.out_last(in_last),.out_error(in_error),
    .out_compact(in_compact),.out_words(in_words),.out_data(in_data)
  );""")
    original_send = """    in_valid[lane]=1;
    in_data[lane]=data;
    in_words[lane]=words;
    in_compact[lane]=compact;
    in_last[lane]=last;
    in_error[lane]=error;
    do @(posedge clk); while (!in_ready[lane]);
    @(negedge clk); in_valid[lane]=0;"""
    return replace(text, original_send, """    if (lane==0) @(negedge clk);
    else @(posedge clk);
    #1;
    pad_valid[lane]=1;
    peer_data[lane]=data;
    pad_words[lane]=words;
    pad_compact[lane]=compact;
    pad_last[lane]=last;
    pad_error[lane]=error;
    if (lane==0) begin
      do @(posedge clk); while (!pad_ready[lane]);
    end else begin
      do @(negedge clk); while (!pad_ready[lane]);
    end
    #1 pad_valid[lane]=0;
    @(negedge clk);""")


def prepare(path, phase, pin):
    evidence = read(pin(Path("records/tri_oracle_compact_response_lane.json")))["evidence_sha256"]
    for item in (LANE_TEST, COMPACT, MODEL, MAPPED_IO):
        pin(item, evidence[str(item)])
    pin(RTL)
    pin(TEST)
    bench = path / "coupled_tb.sv"
    content = coupled_bench(LANE_TEST.read_text())
    if phase == "prepare":
        with bench.open("x") as output:
            output.write(content)
    else:
        assert pin(bench).read_text() == content
    return bench


def verify(path, bench, pin):
    def run(lane, top, required):
        folder = path / lane
        argv = arguments(pin(folder / "xrun.history"))
        assert argv[argv.index("-top") + 1] == top
        assert all(str(pin(src).resolve()) in argv for src in required)
        return pin(folder / "console.log").read_text()

    red = run("red", f"{TOP}_tb", (path / "red/baseline.sv", TEST))
    assert "DDR_CAPTURE_DATA lane=1 beat=0" in red and "Simulation terminated via $fatal(1)" in red
    mapped = path / "genus/netlist.v"
    result = {}
    for lane, required in {"rtl": (RTL, TEST), "mapped": (mapped, TEST, MODEL)}.items():
        log = run(lane, f"{TOP}_tb", required)
        (concurrent, rising_held, falling_held), = re.findall(
            r"(?m)^DUAL_EDGE_CAPTURE_PASS rise=128 fall=101 overlap=(\d+) stalls=(\d+),(\d+)$", log)
        assert int(concurrent) >= 16 and int(rising_held) > 0 and int(falling_held) > 0
        assert log.count("Simulation complete via $finish(1)") == 1 and not re.search(r"\*[EF],", log)
        result[lane] = {"simultaneous_beats": int(concurrent),
                        "stalled_cycles": [int(rising_held), int(falling_held)]}
    log = run("coupled", f"{LANE}_captured_tb", (mapped, COMPACT, bench, MODEL, MAPPED_IO))
    (overlap,) = re.findall(r"(?m)^COMPACT_RESPONSE_LANE_PASS wide=2 indexes=2 scalar=3 write_acks=1 overlap=(\d+)$", log)
    assert int(overlap) > 0 and log.count("Simulation complete via $finish(1)") == 1
    assert not re.search(r"\*[EF],", log)
    genus = path / "genus"
    assert "TRI_ORACLE_DUAL_EDGE_CAPTURE_GENUS_FINISHED" in pin(genus / "console.log").read_text()
    assert "No unresolved references" in pin(genus / "mapped_check.rpt").read_text()
    constraints = pin(genus / "constraints.sdc").read_text()
    assert re.search(r"(?m)^create_clock .* -period 1\.72414 ", constraints)
    assert "-clock_fall" in constraints
    timing = {}
    for group in ("timing", "input_timing", "falling_output_timing", "falling_ready_timing"):
        report = pin(genus / f"{group}.rpt").read_text()
        slacks = [int(value) for value in re.findall(r"Slack:=\s+(-?\d+)", report)]
        assert slacks and min(slacks) >= 0, group
        timing[group] = min(slacks)
    pin(SYNTH)
    pin(Path(__file__).resolve().relative_to(Path.cwd()))
    return {
        "state": "mapped_dual_edge_memory_capture_and_compact_endpoint_verified",
        "shared_data_signals": 448, "rising_beats": 128, "falling_beats": 101,
        "coupled_endpoint_cases": {"wide_beats": 2, "index_beats": 2, "scalar_beats": 3, "write_acks": 1},
        "simulations": result, "standalone_clock_period_ns": 1.72414,
        "standalone_setup_slack_ps": timing,
        "scope": "Mapped digital receiver with an ideal common clock. The peer launches on "
                 "alternating phases. The functional replay disables timing checks. Setup uses "
                 "0.2 ns interface budgets before pad, package, and routed clock effects.",
    }


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
