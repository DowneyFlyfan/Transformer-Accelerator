"""Verify the timed SRAM boundary and the matching mapped arithmetic replay."""

import argparse
import hashlib
import json
import re
from pathlib import Path

from prepare_tri_oracle_cluster_weight_phase import distribute_weight_macro_inputs
from prepare_tri_oracle_phase_macro_boundary import MAPPING, ROOT, boundary, delay_phase_logic
from verify_tri_oracle_cluster_weight_phase import RUNS, require


SETUP_GROUPS = ("setup", "address", "chip_enable", "write_enable", "write_mask", "data")
PATH = re.compile(r"^Path 1: (VIOLATED|MET) \(([+\-]?[\d.]+) ns\) (.+)$", re.M)


def critical_path(report):
    match = PATH.search(report.read_text())
    require(match, f"no critical path in {report}")
    state, slack, endpoint = match.groups()
    slack_ps = round(float(slack)*1000)
    require(state == ("VIOLATED" if slack_ps < 0 else "MET"), f"invalid slack status in {report}")
    return {"slack_ps": slack_ps, "check": endpoint}


def electrical(report, corner):
    output = report.read_text()
    chunks = re.split(r"^Check type : (max_capacitance|max_transition)$", output, flags=re.M)
    require(len(chunks) == 5, f"expected both electrical check types in {report}")
    result = {}
    for kind, table in zip(chunks[1::2], chunks[2::2], strict=True):
        rows = re.findall(rf"^\s*\S+\s+[\d.]+\s+[\d.]+\s+-[\d.]+\s+{corner}\s*$", table, re.M)
        require(bool(rows) != ("No Violations found" in table), f"unexpected electrical report {report}")
        result[kind] = len(rows)
    return result


def verify():
    paths = {
        MAPPING, ROOT / "syn/prepare_tri_oracle_phase_macro_boundary.py",
        ROOT / "syn/tri_oracle_time_phase_macro_boundary.tcl",
        ROOT / "syn/tri_oracle_phase_macro_boundary.sdc",
    }
    physical = {}
    original = MAPPING.read_text()
    buffered = delay_phase_logic(original)
    for name, distributed, netlist in (
        ("macro_boundary", False, original), ("macro_boundary_distributed", True, buffered),
    ):
        directory = RUNS / name
        console = (directory / "console.log").read_text()
        require(len(re.findall(r"^PHASE_MACRO_INVENTORY banks=320$", console, re.M)) == 1
                and len(re.findall(r"^PHASE_MACRO_TIMING_COMPLETE$", console, re.M)) == 1
                and not re.search(r"^\*\*ERROR:", console, re.M),
                f"incomplete native analysis: {name}")
        require((directory / "macro_boundary.v").read_text() == netlist + "\n" + boundary(distributed),
                f"wrong candidate topology: {name}")
        require(all(text in console for text in ("Parasitics Mode: No SPEF/RCDB", "Design Stage: PreRoute")),
                f"unexpected parasitic analysis mode: {name}")
        paths.update(directory / file for file in ("macro_boundary.v", "console.log", "views.tcl"))
        setup = {}
        rules = {}
        for corner in ("slow", "typical"):
            setup[corner] = {}
            for group in SETUP_GROUPS:
                report = directory / f"{corner}_{group}.rpt"
                setup[corner][group] = critical_path(report)
                paths.add(report)
            report = directory / f"{corner}_electrical.rpt"
            rules[corner] = electrical(report, corner)
            paths.add(report)
        hold_report = directory / "fast_hold.rpt"
        paths.add(hold_report)
        physical[name] = {"setup": setup, "hold_fast": critical_path(hold_report), "electrical": rules}
    base, repaired = physical.values()
    for corner in ("slow", "typical"):
        require(base["setup"][corner]["setup"]["slack_ps"] < 0 < repaired["setup"][corner]["setup"]["slack_ps"],
                f"{corner}: setup repair did not pass")
        require(sum(base["electrical"][corner].values()) > 0
                and sum(repaired["electrical"][corner].values()) == 0,
                f"{corner}: electrical repair did not clear the violations")
    require(base["hold_fast"]["slack_ps"] < 0 < repaired["hold_fast"]["slack_ps"],
            "fast-corner hold repair did not pass")

    controller = RUNS / "macro_boundary_distributed/controller.v"
    require(controller.read_text() == buffered, "simulation used a different buffer repair")
    paths.add(controller)
    replays = {}
    for corner in ("slow", "typical", "fast"):
        work, control = (RUNS / f"{mode}_{corner}" for mode in ("buffered", "mapped"))
        log, old_log, status = work / "xrun.log", control / "xrun.log", work / "exit_status"
        text = log.read_text()
        require(int(status.read_text()) == 0 and "Simulation complete via $finish(1)" in text
                and not re.search(r"\*[EF],|timing violation|-notimingchecks|-nospecify", text, re.I),
                f"{corner}: repaired replay failed")
        require(f"\t{controller}\n" in text and "fabric_mapping/mapped.v\n" not in text,
                f"{corner}: repaired controller was not bound")
        require((work / "core.sv").read_text() == distribute_weight_macro_inputs((control / "core.sv").read_text()),
                f"{corner}: repaired macro drivers did not bind")
        for file in ("bench.sv", "cluster.sv", "weight_timed.v"):
            require((work / file).read_bytes() == (control / file).read_bytes(), f"{corner}: changed {file}")
        for file in ("accumulators.hex", "activations.hex", "initial_weights.hex", "masks.hex",
                     "down_index.bin", "down_payload.bin"):
            require((work / file).resolve(strict=True) == (control / file).resolve(strict=True),
                    f"{corner}: changed {file} fixture")
        marker = r"^COMPILED_CLUSTER_WEIGHT_.*$"
        matched = re.findall(marker, text, re.M)
        require(len(matched) == 6 and matched == re.findall(marker, old_log.read_text(), re.M)
                and any("exact=163840 published=2560" in result for result in matched),
                f"{corner}: changed trained replay output")
        timing = re.search(r"^\s*Timing checks:\s+([\d,]+)", text, re.M)
        require(timing and int(timing[1].replace(",", "")) >= 337600,
                f"{corner}: weight-bank timing checks were missing")
        paths.update((log, old_log, status, work / "core.sv", work / "weight_timed.v"))
        replays[corner] = {"exact_accumulator_values": 163840, "published_values": 2560, "cycles": 1972}

    hashes = {}
    for path in sorted(paths):
        with path.open("rb") as handle:
            hashes[str(path.relative_to(ROOT))] = hashlib.file_digest(handle, "sha256").hexdigest()
    return {
        "state": "loaded_weight_memory_timing_repair_verified_before_placement",
        "scope": ("Unplaced wiring with 320 vendor SRAM timing views and ideal core and memory clocks. "
                  "The mapped logic and local drivers are also replayed in Xcelium with timed memory models "
                  "and unannotated standard-cell models. Routed interconnect and the chip clock tree remain open."),
        "memory_banks": 320,
        "clock_periods_ps": {"weight": 862, "core": 1724},
        "physical": physical,
        "replay": replays,
        "evidence_sha256": hashes,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", type=Path)
    args = parser.parse_args()
    result = verify()
    if args.record:
        args.record.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print("Verified loaded macro timing and all three mapped Xcelium replays.")
