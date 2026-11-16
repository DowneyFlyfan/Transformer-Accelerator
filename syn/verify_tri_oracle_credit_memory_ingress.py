"""Replay delayed credits and the mixed response endpoint with the mapped ingress."""

import argparse
import json
from pathlib import Path
import re

from link_tri_oracle_chip_packet_io import ROOT
from measure_tri_oracle_serial_memory_requests import digest, read, replace
from verify_tri_oracle_compact_response_lane import GEAR, MAPPED_IO
from verify_tri_oracle_dual_edge_memory_capture import RTL as CAPTURE
from verify_tri_oracle_dual_edge_memory_ingress import BASE as DIRECT, REPLAY as DIRECT_TB
from verify_tri_oracle_host_rotary import MODEL
from verify_tri_oracle_host_status import arguments
from verify_tri_oracle_host_projection import include


TOP = "tri_oracle_credit_memory_ingress"
TEST = Path(f"verilog/{TOP}_tb.sv")
RTL = Path(f"verilog/{TOP}.sv")
FIFO = Path("verilog/async_fifo.sv")
SYNTH = Path(f"syn/tri_oracle_synthesize_credit_memory_ingress.tcl")
GPU_CHECK = Path("syn/check_tri_oracle_credit_conservation.py")
COMPACT = ROOT / "compact_responses/tri_oracle_compact_response_lane.sv"
MIXED = "tri_oracle_credit_memory_ingress_mixed_tb"
PACKED = ROOT / "compact_responses"
WEIGHT_TEST = ROOT / "memory_io_link/compact_index_replay_tb.sv"


def trained_bench(source):
    assert "ddr_peer_staged_error" not in source
    opening = re.search(r"(?ms)^    tri_oracle_compact_index_ingress ingress \(.*?^    \);\n", source)
    assert opening is not None
    source = replace(source, opening[0], "")
    anchor = "  for (genvar lane=0;lane<2;lane++) begin : lanes\n    assign decoded_ready"
    bridge = """  logic [1:0] credit_valid,pad_credit,protocol_error;
  logic [1:0] stage_valid='0,stage_pop;
  logic [1:0][447:0] stage_data;
  logic [1:0][2:0] stage_words;
  logic [1:0] stage_compact,stage_last,ddr_peer_staged_error;
  logic passing_falling=0;
  wire [447:0] shared_data;
  assign #2 shared_data=clk?stage_data[1]:stage_data[0];
  assign stage_pop={passing_falling,credit_valid[0]};
  assign link_ready=~stage_valid | stage_pop;
  always @(negedge clk or negedge rst_n)
    if (!rst_n) passing_falling<=0;
    else passing_falling<=credit_valid[1];
  for (genvar phase=0;phase<2;phase++) begin : transport_peer
    int available=8;
    logic [3:0] delayed=0;
    wire phase_clk=phase==0?clk:!clk;
    assign credit_valid[phase]=rst_n && stage_valid[phase] && available!=0;
    always @(posedge phase_clk or negedge rst_n)
      if (!rst_n) begin
        available<=8;
        delayed<=0;
      end else begin
        int updated;
        updated=available+int'(delayed[3])-int'(credit_valid[phase]);
        if (updated<0 || updated>8) $fatal(1,"TRAINED_CREDIT_CONSERVATION");
        available<=updated;
        delayed<={delayed[2:0],pad_credit[phase]};
      end
    always @(posedge clk or negedge rst_n)
      if (!rst_n) stage_valid[phase]<=0;
      else if (link_ready[phase]) stage_valid[phase]<=link_valid[phase];
    always @(posedge clk) if (link_valid[phase] && link_ready[phase]) begin
      stage_data[phase]<=link_data[phase];
      stage_words[phase]<=link_words[phase];
      stage_compact[phase]<=link_compact[phase];
      stage_last[phase]<=link_last[phase];
      ddr_peer_staged_error[phase]<=link_error[phase];
    end
  end
  tri_oracle_credit_memory_ingress credit_ingress (
    .clk,.rst_n,.pad_data(shared_data),.pad_valid(credit_valid),.pad_credit,.protocol_error,
    .pad_words(stage_words),.pad_compact(stage_compact),.pad_last(stage_last),.pad_error(ddr_peer_staged_error),
    .out_valid(mem_rsp_valid),.out_ready(mem_rsp_ready),.out_data(mem_rsp_data),
    .out_last(mem_rsp_last),.out_error(mem_rsp_error)
  );
  always @(posedge clk)
    if (rst_n && protocol_error!==0) $fatal(1,"TRAINED_CREDIT_OVERFLOW");

"""
    return replace(source, anchor, bridge + anchor)


def trained_sources(directory, phase, compact, pin):
    archived = pin(PACKED / "trained_bundle.sv", compact[str(PACKED / "trained_bundle.sv")])
    weights = Path(".cache/model_reference/packed_down_export/v1/weights.bin")
    pin(weights, compact[str(weights)])
    for label in re.findall(r'(?m)^`include "([^"]+)"$', archived.read_text()):
        path = Path(label).relative_to(Path.cwd())
        pin(path, compact[str(path)])
    test = directory / "trained_tb.sv"
    old = pin(WEIGHT_TEST, compact[str(WEIGHT_TEST)])
    data = trained_bench(old.read_text())
    bundle = replace(archived.read_text(), include(PACKED / "genus/netlist.v") + include(PACKED / "index_alias.v"), "")
    generated = {test: data}
    for name, paths in {"rtl": (FIFO, CAPTURE, GEAR, COMPACT, RTL),
                        "mapped": (directory / "genus/netlist.v",)}.items():
        generated[directory / f"trained_{name}.sv"] = replace(
            bundle, include(WEIGHT_TEST), "".join(include(item) for item in (*paths, test)))
        out = directory / f"trained_{name}"
        out.mkdir(exist_ok=True)
        for file in ("down_index.bin", "down_payload.bin", "projected.hex"):
            target = (PACKED / "trained" / file).resolve()
            path = target.relative_to(Path.cwd())
            pin(path, compact[str(path)])
            local = out / file
            if phase == "prepare" and not local.exists():
                local.symlink_to(target)
            assert local.is_symlink() and local.resolve() == target
    for file, content in generated.items():
        if phase == "prepare" and not file.exists():
            with file.open("x") as handle:
                handle.write(content)
        else:
            assert pin(file).read_text() == content


def mixed_bench(source):
    source = replace(source, f"module {DIRECT_TB};", f"module {MIXED};")
    marker = "  logic [1:0][2:0] pad_words=0;"
    added = """
  logic [1:0] pad_credit,protocol_error;
  int available[2]='{default:8};
  logic [3:0] delayed[2]='{default:0};
  for (genvar lane=0;lane<2;lane++) begin: credit_peer
    wire phase_clk=lane==0?clk:!clk;
    assign pad_ready[lane]=rst_n && available[lane]!=0;
    always @(posedge phase_clk or negedge rst_n)
      if (!rst_n) begin
        available[lane]<=8;
        delayed[lane]<=0;
      end else begin
        int updated;
        updated=available[lane]+int'(delayed[lane][3])-int'(pad_valid[lane] && pad_ready[lane]);
        if (updated<0 || updated>8) $fatal(1,"CREDIT_MIXED_COUNTER");
        available[lane]<=updated;
        delayed[lane]<={delayed[lane][2:0],pad_credit[lane]};
      end
  end
  always @(posedge clk) if (rst_n && protocol_error!==0) $fatal(1,"CREDIT_MIXED_OVERFLOW");
"""
    source = replace(source, marker, marker + "\n" + added)
    return replace(source, """  tri_oracle_dual_edge_memory_ingress ingress (
    .clk,.rst_n,.pad_valid,.pad_ready,.pad_last,.pad_error,.pad_compact,.pad_words,.pad_data,""",
                   """  tri_oracle_credit_memory_ingress ingress (
    .clk,.rst_n,.pad_valid(pad_valid & pad_ready),.pad_credit,.protocol_error,
    .pad_last,.pad_error,.pad_compact,.pad_words,.pad_data,""")


def prepare(directory, phase, pin):
    capture = read(pin(Path("records/tri_oracle_dual_edge_memory_capture.json")))["evidence_sha256"]
    compact = read(pin(Path("records/tri_oracle_compact_response_lane.json")))["evidence_sha256"]
    direct = read(pin(Path("records/tri_oracle_dual_edge_memory_ingress.json")))["evidence_sha256"]
    for path in (COMPACT, GEAR):
        pin(path, compact[str(path)])
    pin(CAPTURE, capture[str(CAPTURE)])
    for path in (MODEL, MAPPED_IO, DIRECT / "joint_genus/netlist.v", DIRECT / "joint_tb.sv"):
        pin(path, direct[str(path)])
    for path in (TEST, RTL, FIFO, SYNTH, GPU_CHECK):
        pin(path)
    test = directory / "mixed_tb.sv"
    source = mixed_bench((DIRECT / "joint_tb.sv").read_text())
    if phase == "prepare" and not test.exists():
        with test.open("x") as handle:
            handle.write(source)
    else:
        assert pin(test).read_text() == source
    trained_sources(directory, phase, compact, pin)
    return test


def verify(directory, test, pin):
    def simulation(folder, top, sources):
        run = directory / folder
        argv = arguments(pin(run / "xrun.history"))
        assert argv[argv.index("-top") + 1] == top
        assert all(str(pin(src).resolve()) in argv for src in sources)
        return pin(run / "console.log").read_text()

    red = simulation("red", f"{TOP}_tb", (directory / "red/baseline.sv", TEST, MODEL,
                                        DIRECT / "joint_genus/netlist.v"))
    assert "CREDIT_CONSERVATION" in red and "Simulation terminated via $fatal(1)" in red
    mapped = directory / "genus/netlist.v"
    results = {}
    for lane, sources in {"rtl": (RTL, CAPTURE, COMPACT, GEAR, FIFO, TEST),
                          "mapped": (mapped, MODEL, TEST)}.items():
        log = simulation(lane, f"{TOP}_tb", sources)
        assert log.count("CREDIT_FULL_RATE_PASS chunks=64,64 responses=56,56 delay=4") == 1
        (first, second), = re.findall(r"(?m)^CREDIT_STALL_PASS chunks=64,64 responses=56,56 credit_stalls=(\d+),(\d+)$", log)
        assert min(int(first), int(second)) >= 36
        assert log.count("Simulation complete via $finish(1)") == 1 and not re.search(r"\*[EF],", log)
        results[lane] = [int(first), int(second)]
    extra_delay = {}
    for lane, sources in {"rtl_delayed": (RTL, CAPTURE, COMPACT, GEAR, FIFO, TEST),
                          "mapped_delayed": (mapped, MODEL, TEST)}.items():
        history = pin(directory / lane / "xrun.history")
        assert "TRI_ORACLE_CREDIT_TEST_DELAY=8" in arguments(history)
        log = simulation(lane, f"{TOP}_tb", sources)
        (first, second), = re.findall(r"(?m)^CREDIT_DELAY_WINDOW_PASS chunks=64,64 responses=56,56 "
                                      r"delay=8 credit_stalls=(\d+),(\d+)$", log)
        assert min(int(first), int(second)) > 0
        assert log.count("Simulation complete via $finish(1)") == 1 and not re.search(r"\*[EF],", log)
        extra_delay[lane] = [int(first), int(second)]
    mixed = simulation("mixed", MIXED, (mapped, MODEL, MAPPED_IO, test))
    (overlap,) = re.findall(r"(?m)^COMPACT_RESPONSE_LANE_PASS wide=2 indexes=2 scalar=3 write_acks=1 overlap=(\d+)$", mixed)
    assert int(overlap) > 0 and mixed.count("Simulation complete via $finish(1)") == 1
    assert not re.search(r"\*[EF],", mixed)
    fixture_cycles = {}
    def cycles(log):
        (elapsed_ns,) = re.findall(r"Simulation complete via \$finish\(1\) at time (\d+) NS", log)
        assert int(elapsed_ns) % 10 == 0
        return int(elapsed_ns) // 10

    for name in ("rtl", "mapped"):
        folder = f"trained_{name}"
        log = simulation(folder, "compact_index_replay_tb", (directory / f"{folder}.sv",))
        assert "+FULL_MATRIX" in arguments(pin(directory / folder / "xrun.history"))
        assert log.count("COMPACT_INDEX_MATRIX_PASS compact0=780 compact1=756") == 1
        assert log.count("STAGED_INDEXED_DOWN_MATRIX_PASS cases=78 exact_bytes=11534336") == 1
        assert log.count("NATIVE_MEMORY_IO_PASS acks=16 faults=2") == 1
        assert log.count("Simulation complete via $finish(1)") == 1 and not re.search(r"\*[EF],", log)
        fixture_cycles[name] = cycles(log)
    assert fixture_cycles["rtl"] == fixture_cycles["mapped"]
    before = PACKED / "trained/console.log"
    compact = read(Path("records/tri_oracle_compact_response_lane.json"))["evidence_sha256"]
    baseline_cycles = cycles(pin(before, compact[str(before)]).read_text())
    genus = directory / "genus"
    assert "TRI_ORACLE_CREDIT_MEMORY_INGRESS_GENUS_FINISHED" in pin(genus / "console.log").read_text()
    assert "No unresolved references" in pin(genus / "mapped_check.rpt").read_text()
    assert re.search(r"(?m)^create_clock .* -period 1\.72414 -waveform \{0\.0 0\.86207\} ",
                     pin(genus / "constraints.sdc").read_text())
    slack = min(map(int, re.findall(r"Slack:=\s+(-?\d+)", pin(genus / "timing.rpt").read_text())))
    assert slack >= 0
    cells, area = next(re.finditer(rf"(?m)^\s*{TOP}\s+NA\s+(\d+)\s+([\d.]+)",
                                  pin(genus / "area.rpt").read_text())).groups()
    gpu = read(pin(directory / "credit_invariant_gpu.rechecked.json"))
    assert set(gpu["state_transitions_by_return_stages"]) == {str(x) for x in range(1, 9)}
    assert sum(gpu["state_transitions_by_return_stages"].values()) == gpu["verified_transitions"] == 40672
    pin(Path(__file__).resolve().relative_to(Path.cwd()))
    return {
        "state": "mapped_credit_ingress_verified_with_delayed_peer",
        "credit_depth_per_lane": 8, "modeled_credit_return_delay_cycles": 4,
        "uninterrupted_chunks_per_lane": 64, "complete_beats_per_lane": 56,
        "credit_stall_cycles_by_lane": results, "mapped_setup_slack_ps": slack,
        "eight_cycle_feedback_unstalled_sink_wait_by_lane": extra_delay,
        "mapped_cell_count": int(cells), "mapped_cell_area_um2": float(area),
        "mixed_endpoint_overlapping_read_ack_cycles": int(overlap),
        "trained_weight_bytes": 11534336, "trained_weight_tiles": 78,
        "trained_fixture_cycles": fixture_cycles, "direct_fixture_cycles": baseline_cycles,
        "abstract_storage_transitions_verified_on_host_gpu": gpu["verified_transitions"],
        "scope": "Digital capture, FIFO, decoder and delayed credit protocol. The shared reset is part of the "
                 "interface contract. Pad delay and numerical results on the whole workload require separate checks.",
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

    test = prepare(args.directory, args.phase, pin)
    if args.phase == "verify":
        print(json.dumps(verify(args.directory, test, pin) | {"evidence_sha256": evidence},
                         indent=2, sort_keys=True))
