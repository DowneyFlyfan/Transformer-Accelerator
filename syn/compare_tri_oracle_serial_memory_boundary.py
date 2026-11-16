"""Replay trained weights through the mapped request serializer and response receiver."""
import argparse
import json
from pathlib import Path
import re

from measure_tri_oracle_serial_memory_requests import digest, read, replace
from verify_tri_oracle_host_status import arguments


ROOT = Path(__file__).resolve().parents[1]
BASE = Path(".cache/physical/whole_chip_xcelium_speed/shared_edge_metadata")
SHARED = Path("records/tri_oracle_shared_edge_metadata.json")
SERIAL = Path("records/tri_oracle_serial_control_pads.json")
PAD_CONTROL = Path(".cache/physical/serialized_memory_controls/genus/netlist.v")
PEER = Path("verilog/tri_oracle_serial_flit_bridge.sv")
TOP = "compact_index_replay_tb"
FIXTURES = ("down_index.bin", "down_payload.bin", "projected.hex")


ADAPTER = """  // Insert the exact mapped chip boundary. The memory peer reconstructs
  // each original 22-bit word from three successive 8-bit pad transfers.
  logic pad_request_valid, pad_request_ready, flit_valid, flit_ready;
  logic [7:0] pad_request_data;
  logic [21:0] flit_data;
  tri_oracle_serial_control_pads boundary_control (
    .clk, .rst_n,
    .host_rx_valid(1'b0), .host_rx_data(4'b0), .wide_host_rx_ready(1'b0),
    .host_tx_ready(1'b0), .wide_host_tx_valid(1'b0), .wide_host_tx_data(16'b0), .wide_host_tx_last(1'b0),
    .memory_tx_valid(pad_request_valid), .memory_tx_ready(pad_request_ready), .memory_tx_data(pad_request_data),
    .wide_memory_tx_valid(wire_valid), .wide_memory_tx_ready(wire_ready), .wide_memory_tx_data(wire_data)
  );
  tri_oracle_flit_from_pads #(.WORD_BITS(22), .PAD_BITS(8)) memory_peer (
    .clk, .rst_n, .pad_valid(pad_request_valid), .pad_ready(pad_request_ready), .pad_data(pad_request_data),
    .out_valid(flit_valid), .out_ready(flit_ready), .out_word(flit_data)
  );
  int physical_flits = 0, serialized_words = 0, pad_stalls = 0;
  bit previously_stalled = 0;
  logic [7:0] previous_pad_data;
  always @(posedge clk) if (rst_n) begin
    logic [23:0] padded;
    padded = {2'b0, wire_data};
    if (previously_stalled && (!pad_request_valid || previous_pad_data !== pad_request_data))
      $fatal(1, "SERIAL_MEMORY_PAD_WORD_CHANGED_WHILE_STALLED");
    previously_stalled = pad_request_valid && !pad_request_ready;
    previous_pad_data = pad_request_data;
    if (previously_stalled) pad_stalls++;
    if (pad_request_valid && pad_request_ready) begin
      if (pad_request_data !== padded[8*(physical_flits%3)+:8])
        $fatal(1, "SERIAL_MEMORY_PAD_WORD_ORDER");
      physical_flits++;
    end
    if ((wire_valid && wire_ready) !== (flit_valid && flit_ready))
      $fatal(1, "SERIAL_MEMORY_WIDE_HANDSHAKE");
    if (flit_valid && flit_ready) begin
      if (flit_data !== wire_data || physical_flits != (serialized_words + 1) * 3)
        $fatal(1, "SERIAL_MEMORY_WIDE_WORD_MISMATCH");
      serialized_words++;
    end
  end
"""


def prepare(out):
    records = read(SHARED)["evidence_sha256"]
    test, bundle = (BASE / name for name in ("trained_tb.sv", "trained_mapped.sv"))
    for path in (test, bundle):
        assert digest(path) == records[str(path.resolve())]
    assert digest(PAD_CONTROL) == read(SERIAL)["evidence_sha256"][str(PAD_CONTROL)]
    anchor = "  tri_oracle_memory_forward_rx request_rx ("
    source = replace(test.read_text(), anchor, ADAPTER + anchor)
    source = replace(source, ".rx_valid(wire_valid), .rx_ready(wire_ready), .rx_data(wire_data)",
                     ".rx_valid(flit_valid), .rx_ready(flit_ready), .rx_data(flit_data)")
    source = replace(source, '      $display("DUAL_GROUP_MATRIX_WRITES',
                     '      $display("SERIAL_MEMORY_PAD_TRAFFIC narrow=%0d wide=%0d stalled=%0d",\n'
                     '               physical_flits,serialized_words,pad_stalls);\n'
                     '      $display("DUAL_GROUP_MATRIX_WRITES')
    text = replace(bundle.read_text(), str(test.resolve()), str(out / "trained_tb.sv"))
    text = f'`include "{PAD_CONTROL.resolve()}"\n`include "{PEER.resolve()}"\n' + text
    out.mkdir(parents=True, exist_ok=True)
    (out / "trained_tb.sv").write_text(source)
    (out / "bundle.sv").write_text(text)
    for name in FIXTURES:
        fixture = (BASE / "trained_mapped" / name).resolve(strict=True)
        for subdir in ("directed", "full"):
            folder = out / subdir
            folder.mkdir(exist_ok=True)
            target = folder / name
            if target.is_symlink():
                assert target.resolve(strict=True) == fixture
            else:
                target.symlink_to(fixture)


def verify(out):
    history = out / "full/xrun.history"
    argv = arguments(history)
    assert argv[argv.index("-top") + 1] == TOP
    assert str(out / "bundle.sv") in argv and "+FULL_MATRIX" in argv
    original = (BASE / "trained_mapped/console.log").resolve()
    assert digest(original) == read(SHARED)["evidence_sha256"][str(original)]
    fresh = out / "full/console.log"
    baseline, trial = original.read_text(), fresh.read_text()
    for text in (baseline, trial):
        assert not re.search(r"\*[EF],", text)
        assert text.count("Simulation complete via $finish(1)") == 1
    for pattern in (
        r"^INDEXED_DOWN_TILE .*$",
        r"^COMPACT_INDEX_MATRIX_PASS .*$",
        r"^MEMORY_REQUEST_HARDWARE_FIXTURE .*$",
        r"^STAGED_INDEXED_DOWN_MATRIX_PASS .*$",
        r"^EARLY_PAIR_SPARSE_ROWS_PASS .*$",
        r"^INDEXED_WEIGHT_MODE_PASS .*$",
    ):
        a, b = (re.findall(pattern, text, re.M) for text in (baseline, trial))
        assert a and a == b, pattern
        if pattern.startswith("^INDEXED_DOWN_TILE"):
            assert len(a) == 80
    # Contention counters can legitimately change. The functional events
    # and explicit testbench checks must still cover all concurrent writes.
    assert re.search(r"(?m)^NATIVE_FORWARD_MIXED_PASS headers=16 words=128 reads_during_writes=[1-9]\d*$", trial)
    assert re.search(r"(?m)^NATIVE_MEMORY_IO_PASS acks=16 faults=2 stalled=[1-9]\d*$", trial)
    assert re.search(r"(?m)^STAGED_WRITES_PASS segments=180224 concurrent=[1-9]\d* directed_conflicts=[1-9]\d*$", trial)
    old, new = (int(re.search(r"(?m)^DUAL_GROUP_MATRIX_WRITES writes=90112 cycles=(\d+)$", text)[1])
                for text in (baseline, trial))
    narrow, wide, blocked = map(int, re.search(r"(?m)^SERIAL_MEMORY_PAD_TRAFFIC narrow=(\d+) wide=(\d+) stalled=(\d+)$", trial).groups())
    assert narrow == 3 * wide and new >= old
    aligned, full = map(int, re.search(r"(?m)^MEMORY_REQUEST_HARDWARE_FIXTURE compact=(\d+) full=(\d+)$", trial).groups())
    assert wide == 2 * aligned + 4 * full + 4 * (16 + 128)
    for name in FIXTURES:
        assert (out / "full" / name).resolve(strict=True) == (BASE / "trained_mapped" / name).resolve(strict=True)
    bundle = (out / "bundle.sv").read_text()
    for path in (PAD_CONTROL, BASE / "genus/netlist.v", PEER):
        assert f'`include "{path.resolve()}"' in bundle
    paths = (SHARED, SERIAL, PAD_CONTROL, PEER, BASE / "genus/netlist.v", original,
             fresh, history, out / "bundle.sv", out / "trained_tb.sv", Path(__file__).resolve())
    return {
        "state": "combined_mapped_memory_links_replayed_exactly",
        "training_tiles": 78, "verified_weight_bytes": 11534336,
        "aligned_read_requests": aligned, "full_address_read_requests": full,
        "twenty_two_bit_forward_matrix_cycles": old, "eight_bit_forward_matrix_cycles": new,
        "additional_matrix_cycles": new - old, "matrix_cycle_increase_percent": 100 * (new - old) / old,
        "forward_link_active_flits": narrow, "forward_link_stalled_cycles": blocked,
        "scope": "The mapped memory-control cut uses the same archived trained weights and simulated peer as "
                 "the original run. The outgoing memory requests use eight pins and incoming metadata is "
                 "shared across clock edges. The measured cycle difference applies to the fixture. The whole "
                 "chip latency, physical package and report workload remain unverified.",
        "evidence_sha256": {str(path.relative_to(ROOT) if path.is_absolute() else path): digest(path) for path in paths},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "verify"))
    parser.add_argument("out", type=lambda name: Path(name).resolve())
    options = parser.parse_args()
    assert Path.cwd() == ROOT and options.out.is_relative_to(ROOT / ".cache") and not Path("/.dockerenv").exists()
    if options.mode == "prepare":
        prepare(options.out)
    else:
        print(json.dumps(verify(options.out), indent=2, sort_keys=True))
