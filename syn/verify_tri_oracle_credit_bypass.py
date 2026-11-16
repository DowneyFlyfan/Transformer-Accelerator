"""Prepare and check the paired empty-queue bypass experiment from the project root."""

import argparse
from hashlib import file_digest
import json
from pathlib import Path
import re

from measure_tri_oracle_serial_memory_requests import replace
from verify_tri_oracle_host_status import arguments


ROOT = Path(__file__).resolve().parents[1]
BASE = Path(".cache/physical/whole_chip_xcelium_speed")
BEFORE = BASE / "credit_ingress"
TRIAL = BASE / "bypass_credit_ingress"
INGRESS = "tri_oracle_credit_memory_ingress"
FIFO = "tri_oracle_credit_bypass_fifo.sv"
CREDIT_TEST = Path(f"verilog/{INGRESS}_tb.sv")
CELL_MODEL = Path(".cache/physical/library/tcbn28hpcplusbwp12t40p140.v")
CAPTURE = Path("verilog/tri_oracle_dual_edge_memory_capture.sv")
GEARBOX = Path("verilog/tri_oracle_memory_response_gearbox.sv")
DECODER = BASE / "compact_responses/tri_oracle_compact_response_lane.sv"
BASELINE = Path("records/tri_oracle_credit_memory_ingress.json")
CLAIM = "TRI_ORACLE_CREDIT_MEMORY_INGRESS_GENUS_FINISHED"


def digest(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def generated():
    ingress = Path(f"verilog/{INGRESS}.sv").read_text()
    for previous, candidate in (
        ("reload && !empty", "reload && (!empty || valid[lane])"),
        ("    // Both ports use the same rising edge. The registered read data is\n"
         "    // the head slot and remains available when the decoder stalls.",
         "    // The head remains registered even when the empty queue is bypassed."),
        ("async_fifo #(.BW(CHUNK_BITS), .MEM_SIZE(CREDIT_DEPTH))",
         "tri_oracle_credit_bypass_fifo #(.WIDTH(CHUNK_BITS), .DEPTH(CREDIT_DEPTH))"),
        (".rd_clk(clk), .wr_clk(clk), .rst_n, .rd(dequeue), .wr(valid[lane]),",
         ".clk, .rst_n, .read_enable(dequeue), .write_enable(valid[lane]),"),
        (".in({last", ".write_data({last"),
        (".out(head)", ".read_data(head)"),
        ("head_valid <= !empty", "head_valid <= dequeue"),
    ):
        ingress = replace(ingress, previous, candidate)

    synthesis = Path("syn/tri_oracle_synthesize_credit_memory_ingress.tcl").read_text()
    synthesis = replace(synthesis, "set root [file dirname [file dirname [file normalize [info script]]]]",
                        f"set root {{{ROOT}}}\nset trial {{{ROOT / TRIAL}}}")
    synthesis = replace(synthesis, "$root verilog/async_fifo.sv", f"$trial {FIFO}")
    synthesis = replace(synthesis, f"$root verilog/{INGRESS}.sv", f"$trial {INGRESS}.sv")

    trained_rtl = (BEFORE / "trained_rtl.sv").read_text()
    for previous, candidate in (("async_fifo.sv", FIFO), (f"{INGRESS}.sv", f"{INGRESS}.sv")):
        trained_rtl = replace(trained_rtl, str(ROOT / "verilog" / previous),
                              str(ROOT / TRIAL / candidate))
    trained_mapped = replace((BEFORE / "trained_mapped.sv").read_text(),
                             str(ROOT / BEFORE / "genus/netlist.v"), str(ROOT / TRIAL / "genus/netlist.v"))

    return {
        f"{INGRESS}.sv": ingress, FIFO: Path("verilog", FIFO).read_text(),
        "first_chunk_tb.sv": Path("verilog/tri_oracle_credit_first_chunk_tb.sv").read_text(),
        "synthesize.tcl": synthesis, "trained_rtl.sv": trained_rtl, "trained_mapped.sv": trained_mapped,
    }


def check():
    evidence = {}

    def pin(path, expected=None):
        actual = digest(path)
        assert expected is None or actual == expected, path
        assert evidence.setdefault(str(path), actual) == actual, path
        return path

    previous = json.loads(pin(BASELINE).read_text())
    baseline_pins = previous["evidence_sha256"]
    for path in (BEFORE / "genus/netlist.v", BEFORE / "genus/timing.rpt",
                 BEFORE / "trained_rtl/console.log", BEFORE / "trained_mapped/console.log",
                 BEFORE / "trained_rtl.sv", BEFORE / "trained_mapped.sv", BEFORE / "mixed_tb.sv",
                 CELL_MODEL, CAPTURE, GEARBOX, DECODER, CREDIT_TEST, Path(f"verilog/{INGRESS}.sv")):
        pin(path, baseline_pins[str(path)])
    for name, contents in generated().items():
        assert pin(TRIAL / name).read_text() == contents, name
        if name in ("trained_rtl.sv", "trained_mapped.sv"):
            for filename in re.findall(r'(?m)^`include "([^"\n]+)"$', contents):
                path = Path(filename).relative_to(ROOT)
                if not path.is_relative_to(TRIAL):
                    pin(path, baseline_pins[str(path)])

    def replay(folder, top, sources, *, options=(), passed=True):
        directory = TRIAL / folder
        argv = arguments(pin(directory / "xrun.history"))
        assert argv[argv.index("-top") + 1] == top
        assert all(str(pin(source).resolve()) in argv for source in sources)
        assert all(option in argv for option in options)
        log = pin(directory / "console.log").read_text()
        if passed:
            assert log.count("Simulation complete via $finish(1)") == 1
            assert not re.search(r"\*[EF],", log)
        return log

    rtl = (TRIAL / f"{INGRESS}.sv", TRIAL / FIFO, CAPTURE, GEARBOX, DECODER)
    mapped = TRIAL / "genus/netlist.v"
    first = TRIAL / "first_chunk_tb.sv"
    red = replay("red", "first_chunk_tb", (first, BEFORE / "genus/netlist.v", CELL_MODEL), passed=False)
    assert "FIRST_CHUNK_CREDIT_LATE credits=00" in red and "Simulation terminated via $fatal(1)" in red
    for folder, sources in (("first", rtl), ("first_mapped", (mapped, CELL_MODEL))):
        assert "FIRST_CHUNK_BYPASS_PASS lanes=2" in replay(folder, "first_chunk_tb", (*sources, first))

    waits = {}
    for prefix, sources in (("rtl", rtl), ("mapped", (mapped, CELL_MODEL))):
        full = replay(prefix + "4", INGRESS + "_tb", (*sources, CREDIT_TEST))
        assert "CREDIT_FULL_RATE_PASS chunks=64,64 responses=56,56 delay=4" in full
        delayed = replay(prefix + "8", INGRESS + "_tb", (*sources, CREDIT_TEST),
                         options=("TRI_ORACLE_CREDIT_TEST_DELAY=8",))
        (a, b), = re.findall(r"(?m)^CREDIT_DELAY_WINDOW_PASS chunks=64,64 responses=56,56 "
                            r"delay=8 credit_stalls=(\d+),(\d+)$", delayed)
        waits[prefix] = [int(a), int(b)]
        assert all(new < old for new, old in zip(waits[prefix],
                   previous["eight_cycle_feedback_unstalled_sink_wait_by_lane"][prefix + "_delayed"], strict=True))
    assert waits["rtl"] == waits["mapped"]
    mixed = replay("mixed", INGRESS + "_mixed_tb",
                   (mapped, CELL_MODEL, BASE / "memory_io_link/genus/netlist.v", BEFORE / "mixed_tb.sv"))
    (overlap,) = re.findall(r"(?m)^COMPACT_RESPONSE_LANE_PASS wide=2 indexes=2 scalar=3 "
                           r"write_acks=1 overlap=(\d+)$", mixed)
    assert int(overlap) > 0

    # The testbench opens the dense weight fixture by its absolute path.
    dense = Path(".cache/model_reference/packed_down_export/v1/weights.bin")
    pin(dense, baseline_pins[str(dense)])
    fixture_cycles = {}
    for name in ("rtl", "mapped"):
        folder = "trained_" + name
        log = replay(folder, "compact_index_replay_tb", (TRIAL / f"{folder}.sv",), options=("+FULL_MATRIX",))
        for marker in (
            "COMPACT_INDEX_MATRIX_PASS compact0=780 compact1=756",
            "STAGED_INDEXED_DOWN_MATRIX_PASS cases=78 exact_bytes=11534336",
            "NATIVE_MEMORY_IO_PASS acks=16 faults=2",
        ):
            assert log.count(marker) == 1
        for fixture in ("down_index.bin", "down_payload.bin", "projected.hex"):
            path = (TRIAL / folder / fixture).resolve(strict=True)
            assert path == (BEFORE / folder / fixture).resolve(strict=True)
            relative = path.relative_to(ROOT)
            pin(relative, baseline_pins[str(relative)])
        (elapsed,) = re.findall(r"Simulation complete via \$finish\(1\) at time (\d+) NS", log)
        assert int(elapsed) % 10 == 0
        fixture_cycles[folder] = int(elapsed) // 10
    baseline_cycles = previous["trained_fixture_cycles"]["mapped"]
    cycles = fixture_cycles["trained_mapped"]
    assert cycles == fixture_cycles["trained_rtl"] < baseline_cycles

    genus = TRIAL / "genus"
    assert CLAIM in pin(genus / "console.log").read_text()
    assert "No unresolved references" in pin(genus / "mapped_check.rpt").read_text()
    assert re.search(r"(?m)^create_clock .* -period 1\.72414 -waveform \{0\.0 0\.86207\} ",
                     pin(genus / "constraints.sdc").read_text())
    timing = pin(genus / "timing.rpt").read_text()
    assert "ssg0p9v125c" in timing
    slack = min(map(int, re.findall(r"Slack:=\s+(-?\d+)", timing)))
    assert slack > 0
    area = pin(genus / "area.rpt").read_text()
    cells, cell_area = re.search(rf"(?m)^{INGRESS}\s+NA\s+(\d+)\s+(\d+\.\d+)", area).groups()
    for path in (Path(__file__).relative_to(ROOT), Path("verilog", FIFO),
                 Path("verilog/tri_oracle_credit_first_chunk_tb.sv")):
        pin(path)
    return {
        "state": "mapped_empty_queue_bypass_verified_on_trained_weight_replay",
        "trained_weight_bytes": previous["trained_weight_bytes"],
        "trained_weight_tiles": previous["trained_weight_tiles"],
        "trained_fixture_cycles_before": baseline_cycles,
        "trained_fixture_cycles_after": cycles,
        "trained_fixture_cycles_saved": baseline_cycles - cycles,
        "first_credit_cycles_saved_per_lane": 1,
        "eight_cycle_feedback_unstalled_sink_wait_by_lane_before":
            previous["eight_cycle_feedback_unstalled_sink_wait_by_lane"]["mapped_delayed"],
        "eight_cycle_feedback_unstalled_sink_wait_by_lane_after": waits["mapped"],
        "mapped_setup_slack_ps_before": previous["mapped_setup_slack_ps"],
        "mapped_setup_slack_ps_after": slack,
        "mapped_cell_area_um2_before": previous["mapped_cell_area_um2"],
        "mapped_cell_area_um2_after": float(cell_area),
        "mapped_cell_count_after": int(cells),
        "scope": "Paired digital memory ingress and trained weight replay. The slow-corner synthesis "
                 "estimate retains positive setup slack. Whole-chip timing, pad qualification and routing "
                 "are unverified. The bypass is a distinct candidate from the published credit ingress.",
        "evidence_sha256": evidence,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true", help="write alternate sources under .cache")
    args = parser.parse_args()
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    if args.prepare:
        TRIAL.mkdir(parents=True, exist_ok=True)
        for name, contents in generated().items():
            path = TRIAL / name
            if path.exists():
                assert path.read_text() == contents, path
            else:
                path.write_text(contents)
    else:
        print(json.dumps(check(), indent=2, sort_keys=True))
