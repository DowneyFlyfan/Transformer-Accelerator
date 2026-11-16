"""Verify the 32-by-8 Booth array mapping against the clock-gated baseline."""

import json
from pathlib import Path
import re

from link_tri_oracle_indexed_whole_chip import module_at, spans
from verify_tri_oracle_booth8 import WORK, array_source, simulation
from verify_tri_oracle_gated_compute_array import (
    PASS,
    ROOT,
    SLOW_LIB,
    TOP,
    WORK as BASE,
    area,
    compile_script,
    digest,
    mapped_ports,
    read,
    renamed,
    timing_script,
)
from verify_tri_oracle_host_status import arguments

ARRAY = WORK / "array"
BASELINE = Path("records/tri_oracle_gated_compute_array.json")
UNIT = Path("records/tri_oracle_booth_multiplier.json")
BUDGET = Path("records/tri_oracle_array_control_buffers.json")
TARGETS = Path("records/paper_result_targets.json")


def verify():
    base = read(BASELINE)
    for name in ("netlist.v", "emitted.sdc", "area.rpt"):
        file = BASE / name
        assert digest(file) == base["evidence_sha256"][str(file)]
    assert (ARRAY / "array.sv").read_text() == array_source()
    assert (ARRAY / "synthesize.tcl").read_text() == compile_script()
    transcript = (ARRAY / "console.log").read_text()
    assert "Normal exit." in transcript
    assert "TRI_ORACLE_COMPUTE_CLOCK_GATING=true" in transcript
    assert re.search(r"(?m)^REDUCTION_SYNTH_COMPARE_PASS \d+$", transcript)
    assert SLOW_LIB.stem in (ARRAY / "area.rpt").read_text()

    ref, trial = ((folder / "netlist.v").read_bytes() for folder in (BASE, ARRAY))
    ref_ports = mapped_ports(module_at(ref, spans(ref), TOP))
    trial_top = module_at(trial, spans(trial), TOP)
    assert mapped_ports(trial_top) == ref_ports
    targets = read(TARGETS)
    rows, lanes = targets["silicon"]["processing_element_array_per_core"]
    assert (
        ref_ports["operand_a"] == ref_ports["operand_b"] == ("INPUT", rows * lanes * 8)
    )
    assert ref_ports["lane_enable"] == ("INPUT", rows * lanes)
    assert ref_ports["out_sums"] == ("OUTPUT", rows * 19)
    instances = re.findall(
        rb"(?m)^\s+tri_oracle_booth8(?:_\d+)?\s+(\\\S+|\w+)\s*\(", trial_top
    )
    assert len(instances) == len(set(instances)) == rows * lanes == 256
    frequency = targets["system_latency"]["clock_megahertz"]
    period = re.search(
        r'create_clock -name "?core"? -period ([\d.]+)',
        (ARRAY / "emitted.sdc").read_text(),
    )[1]
    assert abs(float(period) - 1000 / frequency) <= 0.00001

    mapped = ARRAY / "mapped_replay/decoupled_mapped.v"
    assert mapped.read_text() == renamed(trial.decode())
    reports = simulation(mapped.parent, PASS, [mapped], "decoupled_lockstep_tb")
    old_history, new_history = (
        BASE / "replay/xrun.history",
        mapped.parent / "xrun.history",
    )
    original_arguments = arguments(old_history)
    original_arguments[
        original_arguments.index(str((BASE / "replay/decoupled_mapped.v").resolve()))
    ] = str(mapped.resolve())
    assert original_arguments == arguments(new_history)

    timing = ARRAY / "native_unplaced"
    assert (timing / "timing.tcl").read_text() == timing_script()
    for name in ("netlist.v", "emitted.sdc"):
        assert (timing / name).resolve(strict=True) == (ARRAY / name).resolve(
            strict=True
        )
    console = (timing / "console.log").read_text()
    assert "TRI_ORACLE_MAPPED_ARRAY_TIMING_FINISHED\n" in console
    assert re.search(r"Message Summary:\s+\d+ warning\(s\), 0 error\(s\)", console)
    slack = {}
    for mode in ("setup", "hold", "gate_setup", "gate_hold"):
        report = timing / f"native_{mode}.rpt"
        result = report.read_text()
        if mode.startswith("gate_"):
            assert (
                "Clock Gating " + mode.removeprefix("gate_").title() + " Check"
                in result
            )
        slack[mode] = round(
            1000 * min(map(float, re.findall(r"Slack:=\s+(-?\d+\.\d+)", result)))
        )
        reports.append(report)
    old_cells, old_sites = area(BASE / "area.rpt")
    new_cells, new_sites = area(ARRAY / "area.rpt")
    assert (
        old_sites == base["clock_gated_mapped_sites"]
        and old_cells == base["clock_gated_mapped_cells"]
    )
    saved = old_sites - new_sites
    assert saved > 0 and slack["setup"] > 0
    n = targets["silicon"]["clusters"] * targets["silicon"]["cores_per_cluster"]
    deficit = read(BUDGET)[
        "projected_chip_site_deficit_if_repeated_across_twenty_arrays"
    ]
    assert n * saved > deficit
    reports.extend(
        (
            timing / "timing.tcl",
            timing / "console.log",
            old_history,
            mapped,
            BASE / "netlist.v",
            BASE / "area.rpt",
            BASE / "emitted.sdc",
        )
    )
    reports.extend(
        ARRAY / name
        for name in (
            "array.sv",
            "synthesize.tcl",
            "netlist.v",
            "emitted.sdc",
            "area.rpt",
            "console.log",
        )
    )
    evidence = [
        BASELINE,
        UNIT,
        BUDGET,
        TARGETS,
        SLOW_LIB,
        *reports,
        Path(__file__).resolve().relative_to(ROOT),
    ]
    return dict(
        state="full_clock_gated_booth_array_mapping_and_lockstep_verified",
        clock_megahertz=frequency,
        rows=rows,
        lanes=lanes,
        booth_multipliers=len(instances),
        baseline_mapped_cells=old_cells,
        booth_mapped_cells=new_cells,
        baseline_row_sites=old_sites,
        booth_row_sites=new_sites,
        row_sites_saved_per_array=saved,
        pre_layout_slack_ps=slack,
        delivered_lockstep_transactions=786,
        projected_sites_saved_across_twenty_arrays=n * saved,
        projected_chip_margin_with_same_buffer_allowance=n * saved - deficit,
        scope="Same array interface, clock and lockstep workload. Native timing excludes physical wires. "
        "The projected site margin charges the earlier buffer allowance and requires independent placement verification.",
        evidence_sha256={str(path): digest(path) for path in evidence},
    )


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    print(json.dumps(verify(), indent=2, sort_keys=True))
