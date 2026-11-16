"""Verify write acknowledgment ownership and replay the captured mixed traffic."""

import argparse
import json
from pathlib import Path
import re
import shlex

from link_tri_oracle_indexed_whole_chip import module_at, signature, spans
from measure_tri_oracle_serial_memory_requests import INDEXED_FIXTURE, digest, read, replace
from verify_tri_oracle_memory_forward_link import CAPTURE, CELLS, CUT, INGRESS, REQUEST_RTL, WRITE_RTL


ROOT = Path(".cache/physical/whole_chip_xcelium_speed")
FORWARD = ROOT / "memory_forward_link"
PREVIOUS = Path("records/tri_oracle_memory_forward_link.json")
PRIOR_BENCH = FORWARD / "compact_index_replay_tb.sv"
PEER = FORWARD / "genus_rx/netlist.v"
TB = Path("verilog/tri_oracle_memory_io_link_tb.sv")
RTL = Path("verilog/tri_oracle_memory_io_link.sv")
READ_RTL = Path("verilog/tri_oracle_shared_read_link.sv")

ACK_MODEL = """  logic ack_pending, ack_error;
  logic source_ack_valid, source_ack_error;
  logic [1:0] physical_ready;
  bit long_frame;
  int acknowledgments, ack_faults, stalled_acks;
  wire source_ack_ready = cycle%11 == 0;
  assign mem_rsp_ready = physical_ready & {1'b1, !ack_pending};

  always @(posedge clk) begin
    if (!rst_n) begin
      ack_pending <= 0;
      ack_error <= 0;
    end else begin
      if (peer_word_valid && accept_word && peer_last) begin
        if (ack_pending) $fatal(1, "OVERLAPPING_WRITE_ACKNOWLEDGMENTS");
        ack_pending <= 1;
        ack_error <= write_headers == 3 || write_headers == 8;
      end else if (ack_pending && physical_ready[0]) begin
        ack_pending <= 0;
      end
      if (ack_pending && mem_rsp_valid[0]) $fatal(1, "ACKNOWLEDGMENT_COLLIDED_WITH_READ");
      if (source_ack_valid && !source_ack_ready) stalled_acks++;
      if (source_ack_valid && source_ack_ready) begin
        if (!ack_pending || source_ack_error !== ack_error || routed_valid[2] || routed_valid[0])
          $fatal(1, "WRONG_RESPONSE_ON_WRITE_CHANNEL");
        acknowledgments++;
        if (source_ack_error) ack_faults++;
      end
    end
  end
"""

IO_INSTANCE = """  tri_oracle_memory_io_link io_link (
    .clk, .rst_n, .req_valid({1'b0, req_valid}), .req_ready(serialized_ready),
    .req_address({64'd0, req_address}), .req_length({6'd0, req_length}), .primary_wide(1'b1),
    .rsp_valid(routed_valid), .rsp_ready({1'b0, rsp_ready}), .rsp_last(routed_last),
    .rsp_error(routed_error), .rsp_data(routed_data),
    .wr_req_valid(source_write_valid), .wr_req_ready(source_write_ready),
    .wr_address(source_address), .wr_length(5'd8),
    .wr_data_valid(source_word_valid), .wr_data_ready(source_word_ready),
    .wr_data(source_data), .wr_strobe(8'hff), .wr_data_last(source_last),
    .wr_rsp_valid(source_ack_valid), .wr_rsp_ready(source_ack_ready), .wr_rsp_error(source_ack_error),
    .mem_rsp_valid(mem_rsp_valid | {1'b0, ack_pending}), .mem_rsp_ready(physical_ready),
    .mem_rsp_last(mem_rsp_last | {1'b0, ack_pending}),
    .mem_rsp_error({mem_rsp_error[1], ack_pending ? ack_error : mem_rsp_error[0]}), .mem_rsp_data,
    .tx_valid(wire_valid), .tx_ready(wire_ready), .tx_data(wire_data)
  );"""


def fixture(text):
    text = replace(text, "  logic rd_valid, rd_ready;\n  logic [21:0] rd_data;\n", "")
    text = replace(text, "  wire accept_word = cycle%9 > 2;", "  wire accept_word = cycle%9 > 2;\n" + ACK_MODEL)
    for module, name, replacement in (("tri_oracle_memory_write_link_tx", "writes_link", ""),
                                      ("tri_oracle_shared_read_link", "request_tx", IO_INSTANCE)):
        match, = re.findall(rf"(?ms)^  {module} {name} \(.*?^  \);", text)
        text = replace(text, match, replacement)
    text = replace(text, """        source_word_valid=0;
      end
    end
  end""", """        source_word_valid=0;
      end
      do @(posedge clk); while (!(source_ack_valid && source_ack_ready));
      if (source_ack_error !== (slot == 2 || slot == 7)) $fatal(1, "NATIVE_WRITE_ACK_ERROR");
      @(negedge clk);
    end
  end""")
    text = replace(text, """  always @(posedge clk) if (rst_n && rd_valid && rd_ready) begin
    if (packet_flits_left != 0)
      packet_flits_left--;
    else if (rd_data[0]) begin
      compact_requests++;
      packet_flits_left = 1;
    end else begin
      full_requests++;
      packet_flits_left = 3;
    end
  end""", """  always @(posedge clk) if (rst_n && wire_valid && wire_ready) begin
    if (packet_flits_left == 0) begin
      if (wire_data[0]) compact_requests++;
      long_frame = !wire_data[0];
      packet_flits_left = wire_data[0] ? 1 : 3;
    end else begin
      if (packet_flits_left == 1 && long_frame && wire_data[8:7] == 0) full_requests++;
      packet_flits_left--;
    end
  end""")
    return replace(text, '      $display("DUAL_GROUP_MATRIX_WRITES', '''      if (acknowledgments!=16 || ack_faults!=2 || stalled_acks==0 || ack_pending)
        $fatal(1, "NATIVE_WRITE_ACK_INVENTORY");
      $display("NATIVE_MEMORY_IO_PASS acks=%0d faults=%0d stalled=%0d", acknowledgments,ack_faults,stalled_acks);
      $display("DUAL_GROUP_MATRIX_WRITES''')


def verify(output, previous):
    proof = {}

    def pin(path):
        proof[str(path)] = digest(path)
        return path

    def replay(folder, sources):
        path = output / folder / "console.log"
        log = pin(path).read_text()
        history = pin(path.with_name("xrun.history")).read_text()
        command = re.findall(r"(?m)^s\d+\([^\n]+\):\s+xrun (.+)$", history)[-1]
        names = {(path.parent / arg).resolve() for arg in shlex.split(command) if arg.endswith((".v", ".sv"))}
        assert all(source.resolve() in names for source in sources)
        assert log.count("Simulation complete via $finish(1)") == 1 and not re.search(r"\*[EF],", log)
        return log

    for path in (PREVIOUS, TB, RTL, READ_RTL, REQUEST_RTL, WRITE_RTL, Path(__file__).resolve(),
                 Path("syn/tri_oracle_synthesize_memory_request_link.tcl")):
        pin(path)
    for path in (PRIOR_BENCH, PEER, CELLS, CUT, INGRESS, CAPTURE,
                 CELLS.with_name("tcbn28hpcplusbwp12t40p140ssg0p9v125c.lib"),
                 INDEXED_FIXTURE / "down_index.bin", INDEXED_FIXTURE / "down_payload.bin"):
        pin(path)
        assert proof[str(path)] == previous["evidence_sha256"][str(path)]
    mapping = output / "genus"
    mapped = pin(mapping / "netlist.v")
    data = mapped.read_bytes()
    ports = signature(module_at(data, spans(data), "tri_oracle_memory_io_link"))
    assert ports["tx_data"] == (b"output", b"[21:0]")
    assert ports["tx_valid"] == (b"output", b"") and ports["tx_ready"] == (b"input", b"")
    assert ports["mem_rsp_data"] == (b"input", b"[1023:0]")
    assert all(ports[name] == (b"input", b"[1:0]") for name in ("mem_rsp_valid", "mem_rsp_last", "mem_rsp_error"))
    assert ports["mem_rsp_ready"] == (b"output", b"[1:0]")
    assert "TRI_ORACLE_MEMORY_REQUEST_LINK_GENUS_FINISHED tri_oracle_memory_io_link" in pin(
        mapping / "console.log").read_text()
    assert "No unresolved references" in pin(mapping / "mapped_check.rpt").read_text()
    assert re.search(r"(?m)^create_clock .* -period 1\.72414 ", pin(mapping / "constraints.sdc").read_text())
    slack = min(map(int, re.findall(r"Slack:=\s+(-?\d+)", pin(mapping / "timing.rpt").read_text())))
    assert slack > 0
    area = pin(mapping / "area.rpt").read_text()
    assert "Operating conditions:   ssg0p9v125c" in area
    cells, = re.findall(r"(?m)^\s*tri_oracle_memory_io_link\s+NA\s+(\d+)\s+([\d.]+)", area)

    marker = r"(?m)^MEMORY_IO_LINK_PASS (.+)$"
    observed, = re.findall(marker, replay("mapped", (mapped, PEER, CELLS, TB)))
    assert re.findall(marker, replay("rtl", (RTL, READ_RTL, REQUEST_RTL, WRITE_RTL, TB))) == [observed]
    directed = {key: int(value) for key, value in (field.split("=") for field in observed.split())}
    assert directed["acks"] == 2 and directed["failed"] == 1 and directed["auxiliary_on_ack"] == 1
    old_bench = pin(Path("verilog/tri_oracle_shared_read_link_tb.sv"))
    old_proof = read(pin(Path("records/tri_oracle_shared_read_link.json")))
    assert old_proof["cold_netlist_sha256"] == previous["cold_netlist_sha256"]
    preserved, = re.findall(r"(?m)^SHARED_READ_LINK_PASS (.+)$",
                            replay("read_only", (READ_RTL, REQUEST_RTL, old_bench)))
    assert {key: int(value) for key, value in (field.split("=") for field in preserved.split())} == old_proof["directed_replay"]
    bench = pin(output / PRIOR_BENCH.name)
    assert bench.read_text() == fixture(PRIOR_BENCH.read_text())
    log = replay("fixture", (CUT, INGRESS, mapped, PEER, CELLS, bench))
    assert "STAGED_INDEXED_DOWN_MATRIX_PASS cases=78 exact_bytes=11534336" in log
    assert "MEMORY_REQUEST_HARDWARE_FIXTURE compact=4352 full=0" in log
    assert "NATIVE_FORWARD_MIXED_PASS headers=16 words=128" in log
    assert "INDEXED_WEIGHT_MODE_PASS switched_to_raw=1" in log
    stalled, = re.findall(r"(?m)^NATIVE_MEMORY_IO_PASS acks=16 faults=2 stalled=(\d+)$", log)
    cycles, = re.findall(r"(?m)^DUAL_GROUP_MATRIX_WRITES writes=90112 cycles=(\d+)$", log)
    for local, original in (("projected.hex", CAPTURE),
                            ("down_index.bin", INDEXED_FIXTURE / "down_index.bin"),
                            ("down_payload.bin", INDEXED_FIXTURE / "down_payload.bin")):
        assert (output / "fixture" / local).resolve() == original.resolve()
    return {
        "state": "mapped_memory_io_link_verified_for_reads_writes_and_acknowledgments",
        "cold_netlist_sha256": previous["cold_netlist_sha256"],
        "forward_data_bits": 22,
        "new_write_acknowledgment_signal_pads": 0,
        "timing": {"target_period_ns": 1.72414, "worst_setup_slack_ps": slack,
                   "mapped_cells": int(cells[0]), "cell_area_um2": float(cells[1])},
        "directed_replay": directed,
        "mixed_replay": {"read_requests": 4352, "exact_read_weight_bytes": 11534336, "exact_write_bytes": 1024,
                         "write_acknowledgments": 16, "injected_write_faults": 2, "stalled_ack_cycles": int(stalled),
                         "cycles": int(cycles), "cycle_change_vs_forward_only": int(cycles) - previous["mixed_replay"]["cycles"]},
        "scope": "The combined on-chip interface and peer decoder passed mapped replay against a testbench "
                 "memory responder. Write acknowledgments share lane zero. Physical capture, pads, the "
                 "external memory controller and complete model timing remain unverified.",
        "evidence_sha256": proof,
    }


if __name__ == "__main__":
    assert __debug__
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "verify"))
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    previous = read(PREVIOUS)
    if args.phase == "prepare":
        assert digest(PRIOR_BENCH) == previous["evidence_sha256"][str(PRIOR_BENCH)]
        with (args.directory / PRIOR_BENCH.name).open("x") as stream:
            stream.write(fixture(PRIOR_BENCH.read_text()))
    else:
        print(json.dumps(verify(args.directory, previous), indent=2, sort_keys=True))
