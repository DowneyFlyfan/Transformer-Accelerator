"""Verify the mapped shared forward link with weight reads and captured writes."""

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
BASE = ROOT / "shared_read_link"
CUT = ROOT / "request_serialization/packed_weight_cut.v"
STIMULUS = BASE / "compact_index_replay_tb.sv"
SHARED_READ = BASE / "genus/netlist.v"
READ_TX = ROOT / "memory_request_all_reads/genus_tx/netlist.v"
CAPTURE = ROOT / "single/cache_reused.hex"
TB = Path("verilog/tri_oracle_memory_forward_link_tb.sv")
REQUEST_RTL = Path("verilog/tri_oracle_memory_request_link.sv")
WRITE_RTL = Path("verilog/tri_oracle_memory_write_link_tx.sv")
CELLS = Path(".cache/physical/library/tcbn28hpcplusbwp12t40p140.v")
INGRESS = Path(".cache/compact_index_io/genus/netlist.v")
RECORDS = Path("records")

WRITE_STIMULUS = """  logic rd_valid, rd_ready;
  logic [21:0] rd_data;
  logic source_write_valid=0, source_write_ready, source_word_valid=0, source_word_ready;
  logic [63:0] source_address, source_data;
  logic source_last;
  logic peer_write_valid, peer_word_valid, peer_last;
  logic [63:0] peer_address, peer_data;
  logic [4:0] peer_length;
  logic [7:0] peer_strobe;
  logic [511:0] projected [16];
  int write_headers, write_words, reads_during_writes;
  wire accept_header = cycle%7 != 0;
  wire accept_word = cycle%9 > 2;

  tri_oracle_memory_write_link_tx writes_link (
    .clk, .rst_n, .rd_valid, .rd_ready, .rd_data,
    .write_valid(source_write_valid), .write_ready(source_write_ready),
    .write_address(source_address), .write_length(5'd8),
    .word_valid(source_word_valid), .word_ready(source_word_ready),
    .write_data(source_data), .write_strobe(8'hff), .write_last(source_last),
    .tx_valid(wire_valid), .tx_ready(wire_ready), .tx_data(wire_data)
  );
  initial begin
    $readmemh("projected.hex", projected);
    wait (rst_n && |req_valid);
    for (int slot=0; slot<16; slot++) begin
      @(negedge clk);
      source_address=64'h2000000 + 64'(slot*64);
      source_write_valid=1;
      do @(posedge clk); while (!source_write_ready);
      @(negedge clk);
      source_write_valid=0;
      for (int word=0; word<8; word++) begin
        source_data=projected[slot][word*64+:64];
        source_last=word==7;
        source_word_valid=1;
        do @(posedge clk); while (!source_word_ready);
        @(negedge clk);
        source_word_valid=0;
      end
    end
  end
  always @(posedge clk) if (rst_n) begin
    if (|(decoded_valid & decoded_ready) && write_headers*8 > write_words)
      reads_during_writes++;
    if (peer_write_valid && accept_header) begin
      if (write_headers >= 16 || write_headers*8 != write_words ||
          peer_address !== 64'h2000000 + 64'(write_headers*64) || peer_length !== 5'd8)
        $fatal(1, "NATIVE_FORWARD_WRITE_HEADER");
      write_headers++;
    end
    if (peer_word_valid && accept_word) begin
      if (write_words >= 128 || write_words >= write_headers*8 || peer_strobe !== 8'hff ||
          peer_last !== (write_words%8 == 7) || peer_data !== projected[write_words/8][(write_words%8)*64+:64])
        $fatal(1, "NATIVE_FORWARD_WRITE_DATA");
      write_words++;
    end
  end
"""


def mixed_bench(text):
    text = replace(text, ".tx_valid(wire_valid), .tx_ready(wire_ready), .tx_data(wire_data)",
                   ".tx_valid(rd_valid), .tx_ready(rd_ready), .tx_data(rd_data)")
    text = replace(text, "  int compact_requests, full_requests, packet_flits_left;\n",
                   "  int compact_requests, full_requests, packet_flits_left;\n" + WRITE_STIMULUS)
    text = replace(text, "tri_oracle_memory_request_rx request_rx (", "tri_oracle_memory_forward_rx request_rx (")
    text = replace(text, ".req_wide(decoded_wide)\n  );", """.req_wide(decoded_wide),
    .write_valid(peer_write_valid), .write_ready(accept_header),
    .write_address(peer_address), .write_length(peer_length),
    .word_valid(peer_word_valid), .word_ready(accept_word), .write_data(peer_data),
    .write_strobe(peer_strobe), .write_last(peer_last)
  );""")
    text = replace(text, "rst_n && wire_valid && wire_ready", "rst_n && rd_valid && rd_ready")
    text = replace(text, "wire_data[0]) begin", "rd_data[0]) begin")
    return replace(text, '      $display("DUAL_GROUP_MATRIX_WRITES', '''      if (write_headers!=16 || write_words!=128 || reads_during_writes==0)
        $fatal(1, "NATIVE_FORWARD_WRITE_INVENTORY");
      $display("NATIVE_FORWARD_MIXED_PASS headers=%0d words=%0d reads_during_writes=%0d",
                write_headers,write_words,reads_during_writes);
      $display("DUAL_GROUP_MATRIX_WRITES''')


def load_inputs():
    read_path = RECORDS / "tri_oracle_shared_read_link.json"
    captured_path = RECORDS / "tri_oracle_full_chip_xcelium_multicore_prefix.json"
    request = read(read_path)
    captured = read(captured_path)
    assert request["cold_netlist_sha256"] == captured["cold_netlist_sha256"]
    for path in (STIMULUS, SHARED_READ, CUT, INGRESS, CELLS):
        assert digest(path) == request["evidence_sha256"][str(path)]
    assert digest(CAPTURE) == captured["evidence_sha256"][str(CAPTURE)]
    return request, (read_path, captured_path)


def write_ports(pin, cold_sha256):
    placed = read(pin(RECORDS / "tri_oracle_repacked_whole_chip_cold_reload.json"))
    netlist, = (Path(path) for path in placed["evidence_sha256"] if path.endswith("/cold.v"))
    assert digest(netlist) == placed["cold_netlist_sha256"] == cold_sha256
    with netlist.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
        ports = signature(module_at(data, spans(data), TOP))
    for name, bits in (("wr_address", 64), ("wr_length", 5), ("wr_data", 64), ("wr_strobe", 8)):
        assert ports[name] == (b"output", f"[{bits - 1}:0]".encode())
    for name in ("wr_req_valid", "wr_data_valid", "wr_data_last", "wr_rsp_ready"):
        assert ports[name] == (b"output", b"")
    for name in ("wr_req_ready", "wr_data_ready", "wr_rsp_valid", "wr_rsp_error"):
        assert ports[name] == (b"input", b"")
    return {"address_bits": 64, "length_bits": 5, "word_bits": 64, "strobe_bits": 8}


def verify(output, request, reports):
    proof = {}

    def pin(path):
        proof[str(path)] = digest(path)
        return path

    def replay(folder, sources):
        log_path = output / folder / "console.log"
        log = pin(log_path).read_text()
        history = pin(log_path.with_name("xrun.history")).read_text()
        command = re.findall(r"(?m)^s\d+\([^\n]+\):\s+xrun (.+)$", history)[-1]
        paths = {(log_path.parent / arg).resolve() for arg in shlex.split(command) if arg.endswith((".v", ".sv"))}
        assert all(source.resolve() in paths for source in sources)
        assert log.count("Simulation complete via $finish(1)") == 1 and not re.search(r"\*[EF],", log)
        return log

    for path in (*reports, TB, REQUEST_RTL, WRITE_RTL, SHARED_READ, STIMULUS, CUT, INGRESS, CELLS, CAPTURE,
                 READ_TX, Path("syn/tri_oracle_synthesize_memory_request_link.tcl"), Path(__file__).resolve()):
        pin(path)
    read_proof = read(pin(RECORDS / "tri_oracle_mapped_memory_request_link.json"))
    assert proof[str(READ_TX)] == read_proof["evidence_sha256"][str(READ_TX)]
    liberty = pin(CELLS.with_name("tcbn28hpcplusbwp12t40p140ssg0p9v125c.lib"))
    assert proof[str(liberty)] == read_proof["evidence_sha256"][str(liberty)]

    endpoints = {}
    netlists = {}
    for name, top, direction in (("tx", "tri_oracle_memory_write_link_tx", b"output"),
                                 ("rx", "tri_oracle_memory_forward_rx", b"input")):
        directory = output / f"genus_{name}"
        netlist = pin(directory / "netlist.v")
        netlists[name] = netlist
        text = netlist.read_bytes()
        ports = signature(module_at(text, spans(text), top))
        assert ports[f"{name}_data"] == (direction, b"[21:0]")
        assert f"TRI_ORACLE_MEMORY_REQUEST_LINK_GENUS_FINISHED {top}" in pin(directory / "console.log").read_text()
        assert "No unresolved references" in pin(directory / "mapped_check.rpt").read_text()
        assert re.search(r"(?m)^create_clock .* -period 1\.72414 ", pin(directory / "constraints.sdc").read_text())
        slack = min(map(int, re.findall(r"Slack:=\s+(-?\d+)", pin(directory / "timing.rpt").read_text())))
        assert slack > 0
        area = pin(directory / "area.rpt").read_text()
        assert "Operating conditions:   ssg0p9v125c" in area
        cells, = re.findall(rf"(?m)^\s*{top}\s+NA\s+(\d+)\s+([\d.]+)", area)
        endpoints[name] = {"setup_slack_ps": slack, "cells": int(cells[0]), "cell_area_um2": float(cells[1])}

    marker = r"(?m)^MEMORY_FORWARD_LINK_PASS (.+)$"
    mapped = replay("mapped", (READ_TX, *netlists.values(), CELLS, TB))
    directed, = re.findall(marker, mapped)
    assert re.findall(marker, replay("rtl", (REQUEST_RTL, WRITE_RTL, TB))) == [directed]
    unit_counts = {k: int(v) for k, v in (item.split("=") for item in directed.split())}
    assert unit_counts["reads"] == 36 and unit_counts["headers"] == 6 and unit_counts["words"] == 21
    assert unit_counts["overlap"] > 0 and unit_counts["stalled_flits"] > 0
    original_bench = pin(Path("verilog/tri_oracle_memory_request_link_tb.sv"))
    original_receiver = pin(output / "genus_read_only/netlist.v")
    read_only = replay("read_only_mapped", (READ_TX, original_receiver, CELLS, original_bench))
    fields, = re.findall(r"(?m)^MEMORY_REQUEST_LINK_PASS (.+)$", read_only)
    read_only_counts = {k: int(v) for k, v in (item.split("=") for item in fields.split())}
    assert read_only_counts == read_proof["unit_replay"]

    bench = pin(output / STIMULUS.name)
    assert bench.read_text() == mixed_bench(STIMULUS.read_text())
    log = replay("fixture", (CUT, INGRESS, SHARED_READ, *netlists.values(), CELLS, bench))
    expected = request["trained_down_projection"]
    assert f"STAGED_INDEXED_DOWN_MATRIX_PASS cases={expected['tiles']} exact_bytes={expected['exact_weight_bytes']}" in log
    assert f"MEMORY_REQUEST_HARDWARE_FIXTURE compact={expected['requests']} full=0" in log
    assert "INDEXED_WEIGHT_MODE_PASS switched_to_raw=1" in log
    overlap, = re.findall(r"(?m)^NATIVE_FORWARD_MIXED_PASS headers=16 words=128 reads_during_writes=(\d+)$", log)
    cycles, = re.findall(r"(?m)^DUAL_GROUP_MATRIX_WRITES writes=90112 cycles=(\d+)$", log)
    assert int(overlap) > 0
    for path, link in ((CAPTURE, "projected.hex"), *((INDEXED_FIXTURE / n, n) for n in ("down_index.bin", "down_payload.bin"))):
        assert (output / "fixture" / link).resolve() == path.resolve()
        if path != CAPTURE:
            pin(path)
            assert proof[str(path)] == request["evidence_sha256"][str(path)]
    physical_write_ports = write_ports(pin, request["cold_netlist_sha256"])
    return {
        "state": "shared_forward_link_verified_with_mapped_weight_reads_and_captured_projection_writes",
        "cold_netlist_sha256": request["cold_netlist_sha256"],
        "forward_data_bits": 22,
        "new_forward_signal_pads": 0,
        "cold_chip_write_ports": physical_write_ports,
        "synthesis": {"target_period_ns": 1.72414, "corner": "0.9 V, 125 C", "endpoints": endpoints},
        "unit_replay": unit_counts,
        "read_only_regression_packets": read_only_counts["packets"],
        "mixed_replay": {"read_requests": expected["requests"], "exact_trained_weight_read_bytes": expected["exact_weight_bytes"],
                         "captured_write_commands": 16, "exact_write_bytes": 1024, "reads_during_writes": int(overlap),
                         "cycles": int(cycles), "added_cycles_vs_read_only": int(cycles) - expected["cycles"]},
        "scope": "Mapped endpoints serialized captured projection writes concurrently with the current trained "
                 "weight-read fixture. Write commands and payloads share existing forward pins. The write "
                 "acknowledgment path, physical pads, external controller and full model remain unverified.",
        "evidence_sha256": proof,
    }


if __name__ == "__main__":
    assert __debug__
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "verify"))
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    request, reports = load_inputs()
    if args.phase == "prepare":
        with (args.directory / STIMULUS.name).open("x") as stream:
            stream.write(mixed_bench(STIMULUS.read_text()))
    else:
        print(json.dumps(verify(args.directory, request, reports), indent=2, sort_keys=True))
