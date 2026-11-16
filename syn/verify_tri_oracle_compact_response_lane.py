"""Verify the two compact response lanes at the exact mapped memory endpoint."""

import argparse
import json
from pathlib import Path
import re

from link_tri_oracle_chip_packet_io import ROOT, instance, ports
from link_tri_oracle_indexed_whole_chip import module_at, spans
from link_tri_oracle_narrow_host import declarations
from measure_tri_oracle_serial_memory_requests import digest, read, replace
from verify_tri_oracle_host_projection import include
from verify_tri_oracle_host_rotary import MODEL
from verify_tri_oracle_host_status import arguments


OLD = Path("verilog/tri_oracle_compact_index_ingress.sv")
GEAR = Path("verilog/tri_oracle_memory_response_gearbox.sv")
MASTER = "tri_oracle_compact_response_lane"
TEST = Path(f"verilog/{MASTER}_tb.sv")
MAPPED_IO = ROOT / "memory_io_link/genus/netlist.v"
PRIOR = ROOT / "memory_io_link/fixture"
REPLAY_PASS = (
    "COMPACT_INDEX_MATRIX_PASS ",
    "NATIVE_FORWARD_MIXED_PASS ",
    "NATIVE_MEMORY_IO_PASS ",
    "STAGED_INDEXED_DOWN_MATRIX_PASS ",
    "STAGED_WRITES_PASS ",
    "EARLY_PAIR_SPARSE_ROWS_PASS ",
    "INDEXED_WEIGHT_MODE_PASS ",
)


def source(old):
    before = replace(old, "module tri_oracle_compact_index_ingress (", f"module {MASTER} (")
    text = replace(before, "// A compact response is one terminal chunk with two low 64-bit words.",
                   """// Compact mode with zero in_words carries a scalar read or write acknowledgment.
// Scalar data occupies the low 64 bits and preserves its own last and error.
// A compact index is one terminal chunk with two low 64-bit words.""")
    text = replace(text, "  logic compact_valid, compact_error;",
                   "  logic compact_valid, compact_error, compact_last;\n  wire scalar = in_words == 3'd0;")
    text = replace(text, "assign out_last = compact_valid || wide_last;",
                   "assign out_last = compact_valid ? compact_last : wide_last;")
    text = replace(text, "compact_data <= in_data[127:0];",
                   "compact_data <= {scalar ? 64'b0 : in_data[127:64], in_data[63:0]};")
    text = replace(text, "      compact_error <= 0;", "      compact_error <= 0;\n      compact_last <= 0;")
    text = replace(text, "          compact_error <= in_error || in_words != 2 || !in_last;",
                   "          compact_error <= in_error || (!scalar && (in_words != 2 || !in_last));\n"
                   "          compact_last <= !scalar || in_last;")
    return before, text


def prepare(path, phase, pin):
    index = read(pin(Path("records/tri_oracle_compact_index_ingress.json")))["evidence_sha256"]
    gearbox = read(pin(Path("records/tri_oracle_memory_response_gearbox.json")))["evidence_sha256"]
    io = read(pin(Path("records/tri_oracle_memory_io_link.json")))["evidence_sha256"]
    before, text = source(pin(OLD, index[str(OLD)]).read_text())
    pin(GEAR, gearbox[str(GEAR)])
    pin(TEST)
    pin(MODEL, io[str(MODEL)])
    pin(MAPPED_IO, io[str(MAPPED_IO)])
    parent = Path(".cache/compact_index_io/genus/netlist.v")
    pin(parent, index[str(parent)])
    new = path / f"{MASTER}.sv"
    if phase == "prepare":
        with new.open("x") as stream:
            stream.write(text)
    else:
        if phase == "verify":
            assert pin(new).read_text() == text
            assert pin(path / "red/baseline.sv").read_text() == before
        old_data = parent.read_bytes()
        ref = module_at(old_data, spans(old_data), "tri_oracle_compact_index_ingress")
        mapped = pin(path / "genus/netlist.v")
        data = mapped.read_bytes()
        assert ports(module_at(data, spans(data), MASTER)) == ports(ref)
        replay(path, phase, mapped, parent, ports(ref), io, index, pin)
    return new


def replay(path, phase, mapped, original, interface, io, index, pin):
    history = PRIOR / "xrun.history"
    prior_args = arguments(pin(history, io[str(history)]))
    original_sources = [Path(arg).relative_to(Path.cwd()) for arg in prior_args if arg.endswith((".v", ".sv"))]
    assert len(original_sources) == 6 and original in original_sources
    for src in original_sources:
        pin(src, io[str(src)])
    out = path / "trained"
    out.mkdir(exist_ok=True)
    for name in ("down_index.bin", "down_payload.bin", "projected.hex"):
        prior_link = PRIOR / name
        assert prior_link.is_symlink()
        target = prior_link.resolve().relative_to(Path.cwd())
        pin(target, io[str(target)])
        link = out / name
        if phase == "replay" and not link.is_symlink():
            link.symlink_to(target.resolve())
        assert link.is_symlink() and link.resolve() == target.resolve()
    raw = Path(".cache/model_reference/packed_down_export/v1/weights.bin")
    pin(raw, index[str(raw)])
    signature = ",\n".join(declarations(interface))
    alias = f"module tri_oracle_compact_index_ingress (\n{signature}\n);\n" + instance(
        MASTER, "lane", {name: name for name in interface}
    ) + "endmodule\n"
    replacement = path / "index_alias.v"
    bundle = path / "trained_bundle.sv"
    sources = [src for src in original_sources if src != original]
    text = "".join(include(src) for src in (*sources[:-1], mapped, replacement, sources[-1]))
    for file, content in ((replacement, alias), (bundle, text)):
        if phase == "replay" and not file.exists():
            with file.open("x") as stream:
                stream.write(content)
        else:
            assert pin(file).read_text() == content, file
    if phase == "verify":
        argv = arguments(pin(out / "xrun.history"))
        assert argv[argv.index("-top") + 1] == "compact_index_replay_tb"
        assert str(bundle.resolve()) in argv and "+FULL_MATRIX" in argv
        baseline = PRIOR / "console.log"
        old_log = pin(baseline, io[str(baseline)]).read_text()
        log = pin(out / "console.log").read_text()
        for marker in REPLAY_PASS:
            expected = [line for line in old_log.splitlines() if line.startswith(marker)]
            assert len(expected) == 1 and [line for line in log.splitlines() if line.startswith(marker)] == expected
        assert log.count("Simulation complete via $finish(1)") == 1 and not re.search(r"\*[EF],", log)


def verify(path, new, pin):
    for lane, sources in {
        "red": (path / "red/baseline.sv", GEAR),
        "rtl": (new, GEAR),
        "mapped": (path / "genus/netlist.v",),
    }.items():
        folder = path / lane
        argv = arguments(pin(folder / "xrun.history"))
        assert argv[argv.index("-top") + 1] == f"{MASTER}_tb"
        assert all(str(pin(src).resolve()) in argv for src in (*sources, TEST, MODEL, MAPPED_IO))
        log = pin(folder / "console.log").read_text()
        if lane == "red":
            assert "COMPACT_RESPONSE_MISMATCH client=2 last=0 got_last=1 error=0 got_error=1" in log
            assert "Simulation terminated via $fatal(1)" in log
        else:
            (overlap,) = re.findall(r"(?m)^COMPACT_RESPONSE_LANE_PASS wide=2 indexes=2 scalar=3 write_acks=1 overlap=(\d+)$",
                                    log)
            assert int(overlap) > 0 and log.count("Simulation complete via $finish(1)") == 1
            assert not re.search(r"\*[EF],", log)
    genus = path / "genus"
    assert "TRI_ORACLE_COMPACT_RESPONSE_GENUS_FINISHED" in pin(genus / "console.log").read_text()
    assert "No unresolved references" in pin(genus / "mapped_check.rpt").read_text()
    assert re.search(r"(?m)^create_clock .* -period 1\.72414 ", pin(genus / "constraints.sdc").read_text())
    slack = min(map(int, re.findall(r"Slack:=\s+(-?\d+)", pin(genus / "timing.rpt").read_text())))
    assert slack >= 0
    pin(Path("syn/tri_oracle_synthesize_compact_response_lane.tcl"))
    pin(Path(__file__).resolve().relative_to(Path.cwd()))
    return {
        "state": "compact_response_lanes_replayed_at_exact_mapped_memory_endpoint",
        "native_lane_count": 2, "input_data_bits_per_lane": 448, "output_data_bits_per_lane": 512,
        "new_metadata_signal_bits_for_two_lanes": 8,
        "native_cases": {"wide_beats": 2, "index_beats": 2, "scalar_beats": 3, "write_acks": 1},
        "trained_weight_replay": {"exact_bytes": 11534336, "tiles": 78,
                                  "mapped_write_ack_regression": 16},
        "standalone_clock_period_ns": 1.72414,
        "standalone_worst_setup_slack_ps": slack,
        "scope": "Digital lane behavior and exact mapped memory endpoint. The archived trained "
                 "weight and concurrent write test uses the updated response lanes. Physical "
                 "double-data-rate capture and the full-workload "
                 "schedule remain to be qualified.",
    }


if __name__ == "__main__":
    assert __debug__
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "replay", "verify"))
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    evidence = {}

    def pin(path, expected=None):
        if str(path) not in evidence:
            evidence[str(path)] = digest(path)
        assert expected is None or evidence[str(path)] == expected, path
        return path

    new = prepare(args.directory, args.phase, pin)
    if args.phase == "verify":
        print(json.dumps(verify(args.directory, new, pin) | {"evidence_sha256": evidence},
                         indent=2, sort_keys=True))
