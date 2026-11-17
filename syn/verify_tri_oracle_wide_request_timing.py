"""Measure wide-request core timing and screen the repaired chip's pad perimeter."""

import argparse
from decimal import Decimal
import json
import mmap
from pathlib import Path
import re

from audit_tri_oracle_bonded_pad_capacity import geometry, vendor_rules
from link_tri_oracle_indexed_whole_chip import module_at, signature, spans
from measure_tri_oracle_credited_request_link import PAD_TIMING, pad_envelope
from prepare_tri_oracle_booth_packet_replay import replace_once
from verify_tri_oracle_booth_clock_boundary import PLACEMENT
from verify_tri_oracle_corrected_booth_roundtrip import ROOT, TOP, digest
from verify_tri_oracle_wide_request_trial import MODULE, PAD_CAPACITY, TX


TRIAL = Path("records/tri_oracle_wide_request_trial.json")
MODELS = Path("records/tri_oracle_corrected_booth_buffered_models.json")
TEMPLATE = Path("syn/tri_oracle_check_memory_tx_credit_timing.tcl")
LIBRARY = Path(".cache/physical/library")
RC = Path(".cache/physical/rc")
TECH = Path(".cache/physical/routing_kit/N28_PRTF_Cad_v1d5a/PR_tech/Cadence/LefHeader/VHV/tsmcn28_10lm5X2Y2ZUTRDL.tlef")


def setup():
    trial = json.loads(TRIAL.read_text())
    assert trial["state"] == "wide_request_link_synthesized_and_replayed_with_placed_response_receiver"
    netlist, = (ROOT / path for path in trial["evidence_sha256"] if path.endswith("/wide_request_trial/genus/netlist.v"))
    assert digest(netlist) == trial["evidence_sha256"][str(netlist.relative_to(ROOT))]
    source_sdc = netlist.with_name("constraints.sdc")
    source = source_sdc.read_text()
    assert re.search(rf"(?m)^current_design {MODULE}$", source)
    assert '-period 1.72414 -waveform {0.0 0.86207}' in source
    folder = netlist.parents[1] / "innovus_timing"
    driver = TEMPLATE.read_text()
    for old, new in (
        ("set root [file dirname [file dirname [file normalize [info script]]]]", f"set root {{{ROOT}}}"),
        ("set out [file normalize $::env(TRI_ORACLE_TX_CREDIT_OUTPUT)]", f"set out {{{folder}}}"),
        ("$out/netlist.v", f"{{{netlist}}}"),
        ("$out/constraints.sdc", f"{{{source_sdc}}}"),
        (f"-top {TX}", f"-top {MODULE}"),
        ("!= 9", "!= 23"),
        ("-max_paths 12 > $out/native_pad_setup.rpt", "-nworst 1 -max_paths 23 > $out/native_pad_setup.rpt"),
        ("-max_paths 12 > $out/native_pad_hold.rpt", "-nworst 1 -max_paths 23 > $out/native_pad_hold.rpt"),
    ):
        driver = replace_once(driver, old, new)
    return folder, driver, (netlist, source_sdc), trial


def pad_geometry(trial):
    placement, capacity, models = (json.loads(path.read_text()) for path in (PLACEMENT, PAD_CAPACITY, MODELS))
    stage = ROOT / Path(placement["database"]).parents[1]
    layout = stage / "cold/layout.def"
    netlist = stage / "cold/cold.v"
    approved = placement["evidence_sha256"]
    assert digest(netlist) == approved[str(netlist.relative_to(ROOT))] == trial["cold_receiver_netlist_sha256"]
    with netlist.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as source:
        ports = signature(module_at(source, spans(source), TOP))
    assert ports["memory_tx_data"] == (b"output", b"[7:0]")
    assert ports["memory_mem_rsp_data"] == (b"input", b"[447:0]")
    signals = sum(1 if not field else int(re.fullmatch(rb"\[(\d+):0\]", field)[1]) + 1
                  for _, field in ports.values())
    assert signals + 14 == trial["digital_signal_pins"] == 498
    inputs = capacity["evidence_sha256"]
    assert models["cold_netlist_sha256"] == trial["cold_receiver_netlist_sha256"]
    lef_dir = ROOT / placement["database"] / "libs/lef"
    lefs = tuple(sorted(lef_dir.glob("*.lef")))
    model_hashes = models["evidence_sha256"]
    assert len(lefs) == 7 and all(digest(path) == model_hashes[str(path.relative_to(ROOT))] for path in lefs)
    archive, = (Path(path) for path in inputs if "sefu10lm.tar.gz" in path)
    release, = (Path(path) for path in inputs if path.endswith("_rln.tar.gz"))
    for path in (archive, release):
        assert digest(path) == inputs[str(path)]
    depth, corner, abstract, regimes, supplies = vendor_rules(archive, release)
    assert abstract == capacity["pad_view_sha256"]
    observed = geometry(layout, approved[str(layout.relative_to(ROOT))], lefs, depth, corner, regimes)
    reserved = trial["signal_and_illustrative_supply_pins"]
    assert signals + 14 + sum(supplies.values()) == reserved
    margins = {}
    for name, edges in observed["capacity_by_case_and_edge"].items():
        sites = sum(edges.values())
        margins[name] = {"sites_by_edge": edges, "whole_ring_sites": sites, "spare_sites": sites - reserved,
                         "spare_sites_if_macros_rearranged_in_same_outline":
                         observed["upper_bound_without_macros_by_case"][name] - reserved}
    return margins, (PLACEMENT, PAD_CAPACITY, MODELS, layout, netlist, archive, release, *lefs)


def verify():
    folder, driver, inputs, trial = setup()
    timing_driver = folder / "measure.tcl"
    assert timing_driver.read_text() == driver
    assert int((folder / "exit_status").read_text()) == 0
    status_path = folder / "native_status.json"
    status = json.loads(status_path.read_text())
    assert status["exit_status"] == 0 and status["stop_reason"] is None
    log = (folder / "console.log").read_text()
    assert "TRI_ORACLE_MEMORY_TX_CREDIT_TIMING_FINISHED" in log
    assert not re.search(r"(?im)^\s*\*\*ERROR:", log)
    sdc = (folder / "peer_phase.sdc").read_text()
    assert sdc.count("-clock_fall [get_ports {pad_data* pad_valid}]") == 2
    assert "pad_sample_clock" not in sdc
    assert "-period 1.72414 -waveform {0.0 0.86207}" in sdc

    def paths(name, view, check, outputs):
        text = (folder / name).read_text()
        assert f"#  Design:            {MODULE}" in text
        reports = re.split(r"(?m)^Path \d+: ", text)[1:]
        assert reports
        endpoints, slacks = set(), []
        for report in reports:
            assert re.search(rf"(?m)^\s*View:\s+{view}$", report) and check in report
            endpoint = re.search(r"(?m)^\s*Endpoint: \([RF]\) (\S+)\n\s*Clock: (.+)$", report)
            endpoints.add(endpoint[1])
            if outputs:
                assert endpoint[2] == "(F) core_clock"
            else:
                assert re.search(r"(?m)^\s*Startpoint: \([RF]\) pad_credit$", report)
            slacks.append(Decimal(re.search(r"Slack:=\s+(-?[\d.]+)", report)[1]) * 1000)
        if outputs:
            assert endpoints == {"pad_valid", *(f"pad_data[{bit}]" for bit in range(22))}
        return min(slacks), len(endpoints)

    setup_slack, covered = paths("native_pad_setup.rpt", "setup_slow", "Late Output Delay Assertion", True)
    hold_slack, _ = paths("native_pad_hold.rpt", "hold_fast", "Early Output Delay Assertion", True)
    return_slack, _ = paths("native_return_hold.rpt", "hold_fast", "Hold Check", False)
    assert min(setup_slack, hold_slack, return_slack) > 0
    margins, geometry_inputs = pad_geometry(trial)
    archive, = (Path(path) for path in json.loads(PAD_TIMING.read_text())["evidence_sha256"] if path.endswith("_nldm.tar.gz"))
    envelope = pad_envelope(min(setup_slack, Decimal(trial["slow_library_wire_free_pad_setup_ps"])), hold_slack)
    inputs = (*inputs, *geometry_inputs, TRIAL, TEMPLATE, PAD_TIMING, archive, timing_driver, status_path, TECH,
              LIBRARY / "tcbn28hpcplusbwp12t40p140.lef",
              *(LIBRARY / f"tcbn28hpcplusbwp12t40p140{corner}.lib" for corner in ("ssg0p9v125c", "ffg1p05vm40c")),
              *(RC / corner for corner in ("qrc_rcworst", "qrc_rcbest")),
              *(folder / name for name in ("peer_phase.sdc", "tx_credit_mmmc.tcl", "console.log", "exit_status",
                                          "native_pad_setup.rpt", "native_pad_hold.rpt", "native_return_hold.rpt")),
              Path(__file__).resolve())
    return {
        "state": "wide_request_link_native_timing_and_fixed_macro_pad_screen_verified",
        "cold_receiver_netlist_sha256": trial["cold_receiver_netlist_sha256"],
        "request_output_endpoints_per_timing_view": covered,
        "wire_free_setup_ps_slow": float(setup_slack),
        "wire_free_hold_ps_fast": float(hold_slack),
        "wire_free_credit_input_hold_ps_fast": float(return_slack),
        "native_resource_status": status,
        "matched_clock_and_output_pad_latency_spread": envelope,
        "required_signal_and_illustrative_supply_sites": trial["signal_and_illustrative_supply_pins"],
        "repaired_fixed_macro_floorplan_pad_capacity": margins,
        "scope": "Standalone Innovus timing uses ideal core clock and modeled peer input timing. The "
                 "package and board are excluded. Pad capacity uses the repaired chip's fixed static "
                 "random-access memory macro halos and hypothetical bond filler spacing.",
        "evidence_sha256": {str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path): digest(path)
                            for path in inputs},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "verify"))
    args = parser.parse_args()
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").is_file()
    if args.phase == "prepare":
        folder, text, _, _ = setup()
        folder.mkdir()
        (folder / "measure.tcl").write_text(text)
        print(folder)
    else:
        print(json.dumps(verify(), indent=2, sort_keys=True))
