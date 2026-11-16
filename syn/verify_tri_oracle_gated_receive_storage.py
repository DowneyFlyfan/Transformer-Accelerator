"""Compare clock-gated synthesis of the exact eight-credit receiver."""
import argparse
from decimal import Decimal
import json
from pathlib import Path
import re
import subprocess

from link_tri_oracle_indexed_whole_chip import module_at, spans
from verify_tri_oracle_host_status import arguments
from verify_tri_oracle_shared_edge_metadata import CASES, ROOT, TOP, digest, mapped_ports, read


BASE = Path(".cache/physical/whole_chip_xcelium_speed/shared_edge_metadata")
WORK = BASE.with_name("gated_receive_storage")
PROOF = Path("records/tri_oracle_shared_edge_metadata.json")
PLACEMENT = Path("records/tri_oracle_serialized_placement_transfer.json")
SYNTHESIS = Path("syn/tri_oracle_synthesize_shared_edge_metadata.tcl")
TIMING = Path("syn/tri_oracle_check_shared_edge_metadata_timing.tcl")
RUNS = ("mapped4", "mapped8", "mixed", "trained_mapped")
CELL_SITE_AREA = Decimal("0.168")


def synthesis_source():
    source = SYNTHESIS.read_text()
    source = source.replace("set root [file dirname [file dirname [file normalize [info script]]]]",
                            f"set root {{{ROOT}}}", 1)
    anchor = "set_db auto_ungroup none"
    assert source.count(anchor) == 1
    return source.replace(anchor, "set_db lp_insert_clock_gating true\n"
                          "puts GATING_SETTING=[get_db lp_insert_clock_gating]\n" + anchor)


def timing_source(gated=True):
    source, _, _ = TIMING.read_text().partition("set cases [list")
    source = source.replace("set root [file dirname [file dirname [file normalize [info script]]]]",
                            f"set root {{{ROOT}}}", 1)
    source += """report_timing -view setup_slow -max_paths 12 -path_type full_clock > $out/native_setup.rpt
report_timing -early -view hold_fast -max_paths 12 -path_type full_clock > $out/native_hold.rpt
"""
    if gated:
        source += """report_timing -check_type clock_gating_setup -view setup_slow -max_paths 12 > $out/native_gate_setup.rpt
set_db timing_analysis_check_type hold
report_timing -check_type clock_gating_hold -view hold_fast -max_paths 12 > $out/native_gate_hold.rpt
"""
    return source + "puts TRI_ORACLE_MAPPED_RECEIVER_TIMING_FINISHED\nexit\n"


def prepare_reference():
    reference = WORK / "reference_timing"
    reference.mkdir(exist_ok=True)
    for name in ("netlist.v", "constraints.sdc"):
        verified = pin_baseline(BASE / "genus" / name).resolve()
        link = reference / name
        if link.is_symlink():
            assert link.resolve(strict=True) == verified
        else:
            link.symlink_to(verified)
    (reference / "timing.tcl").write_text(timing_source(gated=False))


def pin_baseline(path):
    pins = read(PROOF)["evidence_sha256"]
    absolute = str(path.resolve())
    assert digest(path) == pins.get(absolute, pins.get(str(path))), path
    return path


def run(folder):
    original = pin_baseline(BASE / folder / "xrun.history")
    argv = arguments(original)
    reference_map = BASE / "genus/netlist.v"
    candidate_map = WORK / "netlist.v"
    out = WORK / folder
    out.mkdir(exist_ok=True)
    if folder == "trained_mapped":
        old_bundle = pin_baseline(BASE / "trained_mapped.sv")
        bundle = WORK / "trained_mapped.sv"
        text = old_bundle.read_text()
        assert text.count(str(reference_map.resolve())) == 1
        bundle.write_text(text.replace(str(reference_map.resolve()), str(candidate_map.resolve())))
        argv[argv.index(str(old_bundle.resolve()))] = str(bundle.resolve())
        for name in ("down_index.bin", "down_payload.bin", "projected.hex"):
            fixture = (BASE / folder / name).resolve(strict=True)
            link = out / name
            if link.is_symlink():
                assert link.resolve(strict=True) == fixture
            else:
                link.symlink_to(fixture)
    else:
        argv[argv.index(str(reference_map.resolve()))] = str(candidate_map.resolve())
    env = {"USER": "downeyflyfan", "LOGNAME": "downeyflyfan", "CDS_LIC_FILE": "5280@localhost",
           "LM_LICENSE_FILE": "5280@localhost"}
    command = ["docker", "exec"]
    for name, value in env.items():
        command.extend(("-e", f"{name}={value}"))
    command.extend(("-w", str(out.resolve()), "tri-oracle-eda", "/opt/cadence/bin/xrun", *argv))
    with (out / "console.log").open("w") as console:
        subprocess.run(command, stdout=console, stderr=subprocess.STDOUT, check=True)


def area(path):
    cells, square_micrometers = re.search(rf"(?m)^{TOP}\s+NA\s+(\d+)\s+([\d.]+)", path.read_text()).groups()
    sites = Decimal(square_micrometers) / CELL_SITE_AREA
    assert sites == int(sites), path
    return int(cells), int(sites)


def verify():
    console = WORK / "console.log"
    transcript = console.read_text()
    assert "GATING_SETTING=true" in transcript and "TRI_ORACLE_SHARED_EDGE_METADATA_FINISHED early=0\n" in transcript
    assert (WORK / "synthesize.tcl").read_text() == synthesis_source()
    assert "No unresolved references" in (WORK / "mapped_check.rpt").read_text()
    assert (WORK / "timing.tcl").read_text() == timing_source()
    assert re.search(r"(?m)^TRI_ORACLE_MAPPED_RECEIVER_TIMING_FINISHED$", (WORK / "timing.log").read_text())
    original = pin_baseline(BASE / "genus/netlist.v")
    mapped = WORK / "netlist.v"
    original_text, candidate_text = original.read_bytes(), mapped.read_bytes()
    assert mapped_ports(module_at(original_text, spans(original_text), TOP)) == mapped_ports(
        module_at(candidate_text, spans(candidate_text), TOP))
    gates = re.findall(rb"(?m)^\s+(CKL\w+)\s+\S+\s*\(\s*\.", candidate_text)
    assert gates and not re.search(rb"(?m)^\s+CKL\w+\s+\S+\s*\(\s*\.", original_text)
    evidence = [PROOF, PLACEMENT, SYNTHESIS, TIMING, original, mapped, console,
                WORK / "synthesize.tcl", WORK / "timing.tcl", WORK / "timing.log",
                WORK / "constraints.sdc", WORK / "mapped_check.rpt", WORK / "area.rpt", WORK / "setup.rpt",
                WORK / "metadata_setup.rpt", WORK / "trained_mapped.sv"]
    matrix_cycles = None
    for folder in RUNS:
        prefixes = CASES[folder][1]
        before = pin_baseline(BASE / folder / "console.log")
        after = WORK / folder / "console.log"
        baseline, candidate = before.read_text(), after.read_text()
        assert not re.search(r"\*[EF],", candidate)
        assert candidate.count("Simulation complete via $finish(1)") == 1
        selected = tuple(prefixes) + ("DUAL_GROUP_MATRIX_WRITES", "INDEXED_DOWN_TILE")
        events = lambda text: [line for line in text.splitlines() if line.startswith(selected)]
        assert len(events(candidate)) >= len(prefixes) and events(candidate) == events(baseline), folder
        history = WORK / folder / "xrun.history"
        test_input = (WORK / "trained_mapped.sv").resolve() if folder == "trained_mapped" else mapped.resolve()
        assert str(test_input) in arguments(history)
        if folder == "trained_mapped":
            assert str(mapped.resolve()) in test_input.read_text()
            cycles, = re.findall(r"(?m)^DUAL_GROUP_MATRIX_WRITES writes=90112 cycles=(\d+)$", candidate)
            matrix_cycles = int(cycles)
            for name in ("down_index.bin", "down_payload.bin", "projected.hex"):
                assert (WORK / folder / name).resolve() == (BASE / folder / name).resolve(strict=True)
        evidence.extend((before, after, history))
    assert matrix_cycles is not None
    old_cells, old_sites = area(pin_baseline(BASE / "genus/area.rpt"))
    new_cells, new_sites = area(WORK / "area.rpt")
    placement = read(PLACEMENT)
    receiver = next(row for row in placement["added_blocks"] if row["master"] == TOP)
    assert old_sites == receiver["standard_cell_sites"] and old_cells == receiver["leaf_instances"]
    setup, metadata = (min(map(int, re.findall(r"Slack:=\s+(-?\d+)", (WORK / name).read_text())))
                       for name in ("setup.rpt", "metadata_setup.rpt"))
    reference = WORK / "reference_timing"
    assert (reference / "timing.tcl").read_text() == timing_source(gated=False)
    assert re.search(r"(?m)^TRI_ORACLE_MAPPED_RECEIVER_TIMING_FINISHED$", (reference / "timing.log").read_text())
    assert (reference / "netlist.v").resolve() == original.resolve()
    assert (reference / "constraints.sdc").resolve() == pin_baseline(BASE / "genus/constraints.sdc").resolve()
    native = {}
    for variant, folder, modes in (("gated", WORK, ("setup", "hold", "gate_setup", "gate_hold")),
                                  ("baseline", reference, ("setup", "hold"))):
        native[variant] = {}
        for mode in modes:
            report = folder / f"native_{mode}.rpt"
            text = report.read_text()
            if mode.startswith("gate_"):
                assert "Clock Gating " + mode.removeprefix("gate_").title() + " Check" in text, report
            margins = re.findall(r"Slack:=\s+(-?\d+\.\d+)", text)
            assert margins, report
            native[variant][mode] = float(min(map(Decimal, margins)) * 1000)
            evidence.append(report)
    evidence.extend((reference / "timing.tcl", reference / "timing.log", BASE / "genus/constraints.sdc"))
    evidence.extend((BASE / "genus/area.rpt", Path(__file__).resolve().relative_to(ROOT)))
    return {
        "state": "clock_gated_receiver_mapped_and_trained_fixture_verified",
        "baseline_cells": old_cells, "gated_cells": new_cells, "inserted_gate_instances_in_module_definitions": len(gates),
        "baseline_sites": old_sites, "gated_sites": new_sites, "sites_saved": old_sites - new_sites,
        "remaining_geometric_site_margin_if_substituted": placement["remaining_sites_after_all_reachable_wrapper_logic"] + old_sites - new_sites,
        "genus_slow_setup_slack_ps": setup, "genus_slow_metadata_setup_slack_ps": metadata,
        "innovus_prelayout_endpoint_slack_ps": native,
        "verified_xcelium_fixtures": list(RUNS),
        "trained_tiles": read(PROOF)["trained_fixture_tiles"],
        "trained_matrix_cycles_unchanged": matrix_cycles,
        "scope": "Mapped functional tests and pre-layout Genus and Innovus timing. The area difference is applied "
                 "to the existing full-wrapper geometric budget without charging future timing repairs. Native "
                 "placement, gated clock distribution and routed timing remain separate checks.",
        "evidence_sha256": {str(path): digest(path) for path in evidence},
    }


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "verify", *RUNS))
    action = parser.parse_args().action
    if action == "prepare":
        WORK.mkdir(parents=True, exist_ok=True)
        (WORK / "synthesize.tcl").write_text(synthesis_source())
        (WORK / "timing.tcl").write_text(timing_source())
        prepare_reference()
    elif action == "verify":
        print(json.dumps(verify(), indent=2, sort_keys=True))
    else:
        run(action)
