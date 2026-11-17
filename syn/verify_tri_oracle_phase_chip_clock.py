"""Verify the generated core clock, reset repair, and chip command replay."""

import argparse
import hashlib
import json
import re
from pathlib import Path

from prepare_tri_oracle_phase_macro_boundary import (
    CLOCK_MAPPING, MAPPING, REPAIRED_CLOCK_BOUNDARY, ROOT, boundary, delay_clock_hold_paths,
    delay_phase_logic, distribute_cluster_reset,
)
from verify_tri_oracle_phase_chip import summary, verify as verify_chip
from verify_tri_oracle_phase_macro_boundary import critical_path, electrical, require


WORK = CLOCK_MAPPING.parent.parent


def verify():
    evidence = {MAPPING, CLOCK_MAPPING, ROOT / "verilog/tri_oracle_phase_chip_clock.sv",
                ROOT / "verilog/tri_oracle_weight_phase_clock.sv", ROOT / "verilog/tri_oracle_phase_chip_clock_tb.sv",
                ROOT / "syn/tri_oracle_map_phase_chip_clock.tcl", ROOT / "syn/tri_oracle_phase_macro_boundary.sdc",
                ROOT / "syn/prepare_tri_oracle_phase_macro_boundary.py", ROOT / "syn/tri_oracle_time_phase_macro_boundary.tcl"}
    mapping_log = CLOCK_MAPPING.parent / "console.log"
    timing_sdc = CLOCK_MAPPING.parent / "timing.sdc"
    require(re.search(r"^PHASE_CHIP_CLOCK_MAPPED$", mapping_log.read_text(), re.M)
            and re.search(r"^create_generated_clock.*core_clock.*-edges \{2 4 6\}.*memory_clk",
                          timing_sdc.read_text(), re.M), "clock mapping or generated-clock definition missing")
    evidence.update((mapping_log, timing_sdc))

    original_controller = delay_phase_logic(MAPPING.read_text())
    original_clock = CLOCK_MAPPING.read_text()
    timings = {}
    for folder, repaired in ((WORK / "macro_boundary", False), (REPAIRED_CLOCK_BOUNDARY, True)):
        controller = distribute_cluster_reset(original_controller) if repaired else original_controller
        clock = delay_clock_hold_paths(original_clock) if repaired else original_clock
        netlist = folder / "macro_boundary.v"
        require(netlist.read_text() == controller + "\n" + clock + "\n" + boundary(True, True),
                f"clock and memory timing netlist did not match: {folder}")
        if repaired:
            require((folder / "controller.v").read_text() == controller and
                    (folder / "clock.v").read_text() == clock, "chip used a different reset repair")
            evidence.update((folder / "controller.v", folder / "clock.v"))
        log = folder / "console.log"
        output = log.read_text()
        require(re.search(r"^PHASE_MACRO_INVENTORY banks=320$", output, re.M)
                and re.search(r"^PHASE_MACRO_TIMING_COMPLETE$", output, re.M)
                and "Parasitics Mode: No SPEF/RCDB" in output and not re.search(r"^\*\*ERROR:", output, re.M),
                f"incomplete Innovus timing report: {folder}")
        samples = {"setup_slow": "slow_setup.rpt", "setup_typical": "typical_setup.rpt", "hold_fast": "fast_hold.rpt"}
        timing = {name: critical_path(folder / file) for name, file in samples.items()}
        timing["electrical"] = {}
        for corner in ("slow", "typical"):
            report = folder / f"{corner}_electrical.rpt"
            timing["electrical"][corner] = electrical(report, corner)
            if repaired:
                require(sum(timing["electrical"][corner].values()) == 0, f"reset repair violated {corner} electrical limits")
            evidence.add(report)
        timings["cluster_reset_buffered" if repaired else "shared_reset"] = timing
        evidence.update((netlist, log, folder / "views.tcl", *(folder / file for file in samples.values())))
    initial, repaired = timings.values()
    for key in ("setup_slow", "setup_typical", "hold_fast"):
        require(initial[key]["slack_ps"] < 0 < repaired[key]["slack_ps"], f"reset repair did not clear {key}")

    reset_replays = {}
    for name in ("reset_rtl", "reset_mapped", "reset_mapped_repaired"):
        simulator_log = WORK / name / "xrun.log"
        exit_status = WORK / name / "exit_status"
        text = simulator_log.read_text()
        require(int(exit_status.read_text()) == 0 and "Simulation complete via $finish(1)" in text
                and not re.search(r"\*[EF],", text), f"{name}: reset replay failed")
        require(summary(text, "PHASE_CLOCK_PASS") == {"resets": 16, "duty_checks": 64},
                f"{name}: reset offset or duty-cycle coverage missing")
        reset_replays[name] = {"asynchronous_reset_offsets": 16, "full_duty_checks": 64}
        evidence.update((simulator_log, exit_status))
    chip = verify_chip(True, False, buffered=True, derived_clock=True)
    hashes = chip["evidence_sha256"]
    for path in sorted(evidence):
        with path.open("rb") as stream:
            hashes[str(path.relative_to(ROOT))] = hashlib.file_digest(stream, "sha256").hexdigest()
    return {
        "state": "internally_divided_chip_command_layer_and_loaded_weight_boundary_verified",
        "scope": ("The command-layer candidate derives a 1,724 ps core clock from one 862 ps external input. "
                  "Clock and controller gates are mapped. Innovus estimates the unplaced clock and reset loads "
                  "of the five-cluster controller and 320 weight banks. Full-chip routing and clock distribution are pending."),
        "memory_and_core_periods_ps": [862, 1724],
        "clocks": ["external_weight_memory_clock", "internally_divided_core_clock"],
        "timings": timings,
        "reset_replays": reset_replays,
        "command_cases": chip["cases"],
        "evidence_sha256": hashes,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", type=Path)
    args = parser.parse_args()
    result = verify()
    if args.record:
        args.record.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print("Verified the mapped clock, reset timing repair, and five single-clock chip replays.")
