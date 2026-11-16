"""Verify the seven shared response pins and the unchanged trained replay."""
import argparse
from decimal import Decimal
import json
from pathlib import Path
import re

from audit_tri_oracle_packed_weight_path import pins
from link_tri_oracle_chip_packet_io import ports as mapped_ports
from link_tri_oracle_indexed_whole_chip import module_at, spans
from link_tri_oracle_narrow_host import width
from measure_tri_oracle_serial_memory_requests import digest, read
from prepare_tri_oracle_shared_edge_metadata import CONTROLS, PREFIX, PRIOR, ROOT, SERIAL, SIDEBAND, SPLIT, TOP, WRAPPER
from verify_tri_oracle_host_control import outer_ports
from verify_tri_oracle_host_status import arguments


GEOMETRY = Path("records/tri_oracle_bonded_pad_recovery.json")
CELL_MODEL = ROOT / ".cache/physical/library/tcbn28hpcplusbwp12t40p140.v"
SYNTHESIS = Path("syn/tri_oracle_synthesize_shared_edge_metadata.tcl")
TIMING_CHECK = Path("syn/tri_oracle_check_shared_edge_metadata_timing.tcl")
TERMINAL = "Simulation complete via $finish(1)"
CASES = {
    "rtl4": ("rtl4", ("CREDIT_FULL_RATE_PASS", "CREDIT_STALL_PASS")),
    "rtl8": ("rtl8", ("CREDIT_DELAY_WINDOW_PASS", "CREDIT_STALL_PASS")),
    "mapped4": ("mapped4", ("CREDIT_FULL_RATE_PASS", "CREDIT_STALL_PASS")),
    "mapped8": ("mapped8", ("CREDIT_DELAY_WINDOW_PASS", "CREDIT_STALL_PASS")),
    "mixed_rtl": ("mixed", ("COMPACT_RESPONSE_LANE_PASS",)),
    "mixed": ("mixed", ("COMPACT_RESPONSE_LANE_PASS",)),
    "trained_rtl": ("trained_rtl", ("NATIVE_MEMORY_IO_PASS", "COMPACT_INDEX_MATRIX_PASS",
                                   "STAGED_INDEXED_DOWN_MATRIX_PASS", "STAGED_WRITES_PASS")),
    "trained_mapped": ("trained_mapped", ("NATIVE_MEMORY_IO_PASS", "COMPACT_INDEX_MATRIX_PASS",
                                         "STAGED_INDEXED_DOWN_MATRIX_PASS", "STAGED_WRITES_PASS")),
}


def check_logs(out, baseline, evidence):
    def results(text, prefixes):
        return [line for line in text.splitlines() if line.startswith((*prefixes, TERMINAL))]

    for folder, (previous, prefixes) in CASES.items():
        candidate = out / folder / "console.log"
        original = SPLIT / previous / "console.log"
        assert digest(original) == baseline["evidence_sha256"][str(original)], original
        text = candidate.read_text()
        assert not re.search(r"\*[EF],", text), candidate
        actual = results(text, prefixes)
        assert len(actual) == len(prefixes) + 1 and actual[-1].startswith(TERMINAL), candidate
        assert actual == results(original.read_text(), prefixes), folder
        history = out / folder / "xrun.history"
        argv = arguments(history)
        test = out / (f"{folder}.sv" if folder.startswith("trained") else
                      "mixed_tb.sv" if folder.startswith("mixed") else "credit_tb.sv")
        assert str(test.resolve()) in argv
        if folder.endswith("8"):
            assert "TRI_ORACLE_CREDIT_TEST_DELAY=8" in argv
        if folder.startswith("trained"):
            assert "+FULL_MATRIX" in argv
            summary = r"(?m)^[A-Z0-9_]+_PASS .*$"
            assert re.findall(summary, text) == re.findall(summary, original.read_text())
            for name in ("down_index.bin", "down_payload.bin", "projected.hex"):
                assert (out / folder / name).resolve(strict=True) == (SPLIT / previous / name).resolve(strict=True)
        if folder.startswith("mapped") or folder in ("mixed", "trained_mapped"):
            manifest = test.read_text() if folder == "trained_mapped" else " ".join(argv)
            assert str((out / "genus/netlist.v").resolve()) in manifest
            assert str(CELL_MODEL) in manifest
        evidence.update((candidate, original, history))
    wrong_edge = out / "wrong_edge/console.log"
    text = wrong_edge.read_text()
    assert "*F,FATSEV" in text and "COMPACT_RESPONSE_TIMEOUT checks=0" in text and TERMINAL not in text
    evidence.add(wrong_edge)


def boundary(out):
    expected = outer_ports(CONTROLS.read_text())
    for field in SIDEBAND:
        del expected[PREFIX + field]
    expected[PREFIX + "metadata"] = ("INPUT", 7)
    assert expected[PREFIX + "data"] == ("INPUT", 448) and width(expected) == 483
    top = (out / "top_wrapper.v").read_text()
    assert outer_ports(top) == expected
    previous_chip = pins(CONTROLS.read_bytes(), "tri_oracle_chip_credited_memory", "chip")
    for field in SIDEBAND:
        del previous_chip[PREFIX + field]
    previous_chip[PREFIX + "metadata"] = (PREFIX + "metadata").encode()
    assert pins(top.encode(), "tri_oracle_chip_credited_metadata", "chip") == previous_chip
    original = (SPLIT / "chip_binding/credit_wrapper.v").read_bytes()
    expected_receiver = pins(original, "tri_oracle_credit_memory_ingress", "credit_receiver")
    for field in SIDEBAND:
        del expected_receiver["pad_" + field]
    expected_receiver["pad_metadata"] = (PREFIX + "metadata").encode()
    assert pins((out / "credit_wrapper.v").read_bytes(), TOP, "credit_receiver") == expected_receiver
    return width(expected)


def bundle_modules(out):
    manifest = (out / "chip_bundle.sv").read_text()
    sources = [Path(name) for name in re.findall(r'(?m)^`include "([^"]+)"$', manifest)]
    assert len(sources) == len(set(sources))
    introduced = {out / "genus/netlist.v", out / "credit_wrapper.v", out / "top_wrapper.v"}
    assert introduced <= {path.resolve() for path in sources}
    modules = set()
    declaration = re.compile(rb"^[ \t]*module\s+([^\s#(]+)")
    for path in sources:
        with path.open("rb") as stream:
            for line in stream:
                if match := declaration.match(line):
                    name = match[1]
                    assert name not in modules, (path, name)
                    modules.add(name)
    assert {TOP.encode(), b"tri_oracle_chip_credited_metadata", b"tri_oracle_chip_shared_metadata",
            b"tri_oracle_serial_control_pads"} <= modules
    return len(sources), len(modules)


def verify(out):
    assert Path.cwd() == ROOT and not Path("/.dockerenv").exists() and __debug__
    baseline = read(PRIOR)
    evidence = {PRIOR, SERIAL, GEOMETRY, WRAPPER, SYNTHESIS, TIMING_CHECK, CONTROLS, Path(__file__).resolve(),
                Path("syn/prepare_tri_oracle_shared_edge_metadata.py"), CELL_MODEL}
    paths = ("top_wrapper.v", "credit_wrapper.v", "chip_bundle.sv", "credit_tb.sv", "mixed_tb.sv", "trained_tb.sv",
             "trained_rtl.sv", "trained_mapped.sv", "genus/netlist.v", "genus/setup.rpt", "genus/metadata_setup.rpt",
             "genus/constraints.sdc", "genus/area.rpt", "genus/console.log", "genus/launched_synthesis.tcl",
             "genus/mapped_check.rpt", "genus/metadata_mmmc.tcl", "sta/console.log")
    evidence.update(out / path for path in paths)
    bits = boundary(out)
    check_logs(out, baseline, evidence)
    source_count, module_count = bundle_modules(out)
    netlist = (out / "genus/netlist.v").read_bytes()
    actual = mapped_ports(module_at(netlist, spans(netlist), TOP))
    assert actual["pad_metadata"] == ("INPUT", 7) and actual["pad_data"] == ("INPUT", 448)
    assert actual["pad_credit"] == actual["protocol_error"] == ("OUTPUT", 2)
    assert "No unresolved references" in (out / "genus/mapped_check.rpt").read_text()
    assert "TRI_ORACLE_SHARED_EDGE_METADATA_FINISHED early=0\n" in (out / "genus/console.log").read_text()
    assert "TRI_ORACLE_SHARED_EDGE_CORNERS_FINISHED" in (out / "sta/console.log").read_text()
    sdc = (out / "genus/constraints.sdc").read_text()
    assert re.search(r"(?m)^create_clock .* -period 1\.72414 -waveform \{0\.0 0\.86207\} ", sdc)
    for bit in range(7):
        matching = [line for line in sdc.splitlines() if line.startswith("set_input_delay ")
                    and line.endswith(f"[get_ports {{pad_metadata[{bit}]}}]")]
        assert len(matching) == 2 and sum("-clock_fall" in line for line in matching) == 1

    def timing(name, corner):
        report = (out / "genus" / name).read_text()
        assert corner in report
        slacks = tuple(map(int, re.findall(r"Slack:=\s+(-?\d+)", report)))
        assert slacks, name
        return min(slacks)

    setup = timing("setup.rpt", "ssg0p9v125c")
    shared_genus = timing("metadata_setup.rpt", "ssg0p9v125c")
    shared = {}
    for test, view in (("setup", "setup_slow"), ("hold", "hold_fast")):
        paths = []
        for bit in range(7):
            for edge, clock in (("rise", "R"), ("fall", "F")):
                report_path = out / "genus" / f"{test}_metadata_{bit}_{edge}.rpt"
                evidence.add(report_path)
                report = report_path.read_text()
                assert re.search(rf"View:\s+{view}\b", report)
                assert re.search(rf"Startpoint:\s+\([RF]\) pad_metadata\[{bit}\]", report)
                assert re.search(rf"Endpoint:.*\n\s*Clock: \({clock}\) core_clock", report)
                assert f"{test.title()} Check" in report
                slack, = re.findall(r"Slack:=\s+(-?\d+(?:\.\d+)?)", report)
                paths.append(Decimal(slack) * 1000)
        shared[test] = min(paths)
    assert min(setup, shared_genus, *shared.values()) >= 0
    area, = re.findall(rf"(?m)^{TOP}\s+NA\s+\d+\s+([0-9.]+)", (out / "genus/area.rpt").read_text())
    delta = Decimal(area) - Decimal(str(baseline["mapped_area_um2"]["split_head"]))
    spare = read(GEOMETRY)["site_margin_after_control_logic_by_additional_pads_released"]["6"]
    site_area = Decimal("0.168")
    adapter_delta = int((delta / site_area).to_integral_value(rounding="ROUND_CEILING"))
    remaining = spare - adapter_delta
    reserve = read(SERIAL)["illustrative_supply_and_ground_reserve"]
    assert remaining > 0 and bits + reserve + 1 == read(GEOMETRY)["required_sites"] - 6
    return {
        "state": "shared_edge_ingress_mapped_and_exact_trained_replay_verified",
        "chip_signal_bits": bits,
        "recovered_metadata_pins": 7,
        "receive_data_width_bits": 448,
        "receive_metadata_width_bits": 7,
        "structural_bundle_source_files": source_count,
        "structural_bundle_unique_modules": module_count,
        "supply_ground_placeholder_pads": reserve,
        "independent_filler_geometric_site_margin_after_remapped_receiver": remaining,
        "area_delta_square_micrometers": float(delta),
        "mapped_slow_setup_margin_ps": setup,
        "mapped_shared_metadata_setup_margin_ps": float(min(shared_genus, shared["setup"])),
        "mapped_shared_metadata_hold_margin_ps": float(shared["hold"]),
        "shared_metadata_capture_endpoints_checked": 14,
        "trained_fixture_bytes": baseline["trained_bytes"],
        "trained_fixture_tiles": baseline["trained_weight_tiles"],
        "trained_fixture_cycles": baseline["trained_fixture_cycles"],
        "scope": "The independently credited memory lanes share the seven response control bits on opposite "
                 "clock edges. The existing trained fixture finishes in the same cycles as the parallel control. "
                 "The pad and row counts use six released reservations and leave one extra site for a pad. "
                 "The timing model uses ideal clocks, 0.2 ns port delay and no extracted pad or package parasitics. "
                 "The latest full chip wrapper is structurally connected. Native legalization, routing and "
                 "paper-level accuracy, system latency and energy remain open.",
        "evidence_sha256": {str(path): digest(path) for path in sorted(evidence)},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", type=lambda value: Path(value).resolve())
    print(json.dumps(verify(parser.parse_args().out), indent=2, sort_keys=True))
