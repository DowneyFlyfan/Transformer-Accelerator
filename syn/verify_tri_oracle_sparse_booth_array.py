"""Qualify the sparse Booth array and compare placement in the original region."""

from argparse import ArgumentParser
from collections import Counter
from contextlib import ExitStack
from functools import cache
import json
from pathlib import Path
import re

from link_tri_oracle_indexed_whole_chip import module_at, spans
from verify_tri_oracle_array_placement_trials import pin_and_blockage_identity
from verify_tri_oracle_booth8 import MULTIPLIER, WORK, array_source, simulation
from verify_tri_oracle_booth_placement import (
    LEF,
    components,
    dimensions,
    occupancy,
    placement_script,
    row_grid,
)
from verify_tri_oracle_gated_compute_array import (
    PASS,
    ROOT,
    SLOW_LIB,
    TOP,
    area,
    compile_script,
    digest,
    mapped_ports,
    read,
    renamed,
)
from verify_tri_oracle_host_status import arguments
from verify_tri_oracle_serialized_placement_transfer import INSTANCE, catalog
from verify_tri_oracle_sparse_booth8 import OUT

BASELINE = Path("records/tri_oracle_booth_array.json")
BASE_PLACEMENT = Path("records/tri_oracle_booth_array_placement.json")
UNIT = Path("records/tri_oracle_sparse_booth_multiplier.json")
REFERENCES = Path("records/paper_result_targets.json")
ARRAY = OUT / "array"
PLACED = ARRAY / "native_placement"
SLACK = re.compile(r"Slack:=\s+(-?\d+\.\d+)")
MULTIPLIERS = re.compile(rb"(?m)^\s+tri_oracle_booth8(?:_\d+)?\s+(\\\S+|\w+)\s*\(")


def checked_region():
    receipt = read(BASE_PLACEMENT)
    (path,) = (
        Path(name)
        for name in receipt["evidence_sha256"]
        if name.endswith("/region.def")
    )
    assert digest(path) == receipt["evidence_sha256"][str(path)]
    assert digest(LEF) == receipt["evidence_sha256"][str(LEF)]
    return path


def leaf_inventory(netlist, pitch, height):
    masters = dimensions([LEF], 2000)
    with ExitStack() as stack:
        modules = catalog(stack, [netlist])
        visiting = set()

        @cache
        def walk(name):
            if name not in modules:
                assert name in masters, name
                return Counter({name: 1})
            assert name not in visiting, name
            visiting.add(name)
            source, start, end = modules[name]
            counts = Counter()
            instances = Counter(
                i[1].decode() for i in INSTANCE.finditer(source, start, end)
            )
            assert instances, name
            for child, copies in instances.items():
                counts.update({leaf: n * copies for leaf, n in walk(child).items()})
            visiting.remove(name)
            return counts

        assert TOP in modules
        population = walk(TOP)
    sites = 0
    for master, copies in population.items():
        width, measured_height = masters[master]
        assert measured_height == height and width > 0 and width % pitch == 0
        sites += copies * (width // pitch)
    return population.total(), sites


def mapping(predecessor=False):
    receipt = read(BASELINE)
    region = checked_region()
    board = region.read_text()
    rows, reservations, height = row_grid(board)
    row_site_capacity = sum(row.count(0) for row in reservations)
    pitch = rows[0][-1]
    first = WORK / "array"
    stage = first if predecessor else ARRAY
    replay = first / "mapped_replay" if predecessor else ARRAY / "replay"
    old_file = first / "netlist.v"
    new_file = stage / "netlist.v"
    assert digest(old_file) == receipt["evidence_sha256"][str(old_file)]
    rtl = array_source()
    if not predecessor:
        multiplier = OUT / "mapped_add/booth8.sv"
        proof = read(UNIT)
        assert digest(multiplier) == proof["evidence_sha256"][str(multiplier)]
        rtl = rtl.removesuffix(MULTIPLIER.read_text()) + multiplier.read_text()
    assert (stage / "array.sv").read_text() == rtl
    assert (stage / "synthesize.tcl").read_text() == compile_script()
    log = (stage / "console.log").read_text()
    assert "Normal exit." in log and "TRI_ORACLE_COMPUTE_CLOCK_GATING=true" in log
    assert re.search(r"(?m)^REDUCTION_SYNTH_COMPARE_PASS \d+$", log)
    assert SLOW_LIB.stem in (stage / "area.rpt").read_text()

    original, mapped = old_file.read_bytes(), new_file.read_bytes()
    old = module_at(original, spans(original), TOP)
    new = module_at(mapped, spans(mapped), TOP)
    assert mapped_ports(new) == mapped_ports(old)
    data = read(REFERENCES)
    lines, lanes = data["silicon"]["processing_element_array_per_core"]
    multipliers = MULTIPLIERS.findall(new)
    assert len(set(multipliers)) == len(multipliers) == lines * lanes == 256
    frequency = data["system_latency"]["clock_megahertz"]
    sdc = stage / "emitted.sdc"
    period = re.search(r'create_clock -name "?core"? -period ([\d.]+)', sdc.read_text())
    assert period and abs(float(period[1]) - 1000 / frequency) <= 0.00001

    simulation_model = replay / "decoupled_mapped.v"
    assert simulation_model.read_text() == renamed(mapped.decode())
    assert arguments(replay / "xrun.history") == [
        str(simulation_model.resolve())
        if arg == str((first / "mapped_replay/decoupled_mapped.v").resolve())
        else arg
        for arg in arguments(first / "mapped_replay/xrun.history")
    ]
    logs = simulation(replay, PASS, [simulation_model], "decoupled_lockstep_tb")

    cells, sites = leaf_inventory(new_file, pitch, height)
    assert (cells, sites) == area(stage / "area.rpt")
    old_count, old_sites = receipt["booth_mapped_cells"], receipt["booth_row_sites"]
    return {
        "state": "sparse_booth_array_mapping_and_lockstep_verified"
        if not predecessor
        else "predecessor_array_mapping_control_verified",
        "clock_megahertz": frequency,
        "processing_elements": len(multipliers),
        "delivered_lockstep_transactions": 786,
        "baseline_mapped_cells": old_count,
        "baseline_row_sites": old_sites,
        "mapped_cells": cells,
        "row_sites": sites,
        "row_sites_saved": old_sites - sites,
        "same_region_row_site_capacity": row_site_capacity,
        "evidence_sha256": {
            str(path): digest(path)
            for path in (
                BASELINE,
                BASE_PLACEMENT,
                UNIT,
                REFERENCES,
                region,
                old_file,
                new_file,
                sdc,
                simulation_model,
                *logs,
                stage / "array.sv",
                stage / "area.rpt",
                stage / "console.log",
                stage / "synthesize.tcl",
                SLOW_LIB,
                LEF,
                Path(__file__).resolve().relative_to(ROOT),
            )
        },
    }


def prepare_placement():
    facts = mapping()
    assert facts["row_sites"] <= facts["same_region_row_site_capacity"]
    PLACED.mkdir(exist_ok=True)
    for file in (checked_region(), ARRAY / "netlist.v", ARRAY / "emitted.sdc"):
        target = PLACED / file.name
        if not target.is_symlink():
            target.symlink_to(file.resolve(strict=True))
        assert target.resolve(strict=True) == file.resolve(strict=True)
    (PLACED / "place.tcl").write_text(placement_script(facts["mapped_cells"]))
    return facts


def placed(predecessor=False):
    facts = mapping(predecessor=predecessor)
    array = WORK / "array" if predecessor else ARRAY
    physical = array / "native_placement"
    region = checked_region()
    placement = physical / "placed.def"
    assert (physical / "place.tcl").read_text() == placement_script(
        facts["mapped_cells"]
    )
    for source in (region, array / "netlist.v", array / "emitted.sdc"):
        assert (physical / source.name).resolve(strict=True) == source.resolve(
            strict=True
        )
    console = (physical / "console.log").read_text()
    assert re.search(r"(?m)^TRI_ORACLE_MAPPED_ARRAY_TIMING_FINISHED$", console)
    assert re.search(r"Message Summary:\s+\d+ warning\(s\), 0 error\(s\)", console)
    assert dict(components(placement)) == dict(components(physical / "attempt.def"))
    region_text = region.read_text()
    assert pin_and_blockage_identity(
        placement.read_text()
    ) == pin_and_blockage_identity(region_text)
    count, sites, capacity = occupancy(region_text, placement)
    assert (count, sites, capacity) == (
        facts["mapped_cells"],
        facts["row_sites"],
        facts["same_region_row_site_capacity"],
    )
    reports = {
        mode: physical / f"native_{mode}.rpt"
        for mode in ("setup", "hold", "gate_setup", "gate_hold")
    }
    slack = {
        name: min(map(float, SLACK.findall(path.read_text())))
        for name, path in reports.items()
    }
    baseline = read(BASE_PLACEMENT)["pre_route_slack_ns"]
    if predecessor:
        assert slack == baseline
    evidence = {
        str(path): digest(path)
        for path in (
            placement,
            physical / "console.log",
            physical / "attempt.def",
            physical / "place.tcl",
            physical / "placement.rpt",
            *reports.values(),
        )
    }
    facts.update(
        state=(
            "predecessor_native_array_control_verified"
            if predecessor
            else "sparse_booth_array_placement_and_timing_measured"
        ),
        baseline_same_region_slack_ns=baseline,
        pre_route_slack_ns=slack,
        scope="One complete 32-by-8 array. Both variants use the original region, pins, and blockages before targeted buffering. The timing estimates precede clock distribution and routing.",
        evidence_sha256=facts["evidence_sha256"] | evidence,
    )
    return facts


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    parser = ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=(
            "control",
            "placement-control",
            "mapping",
            "prepare-placement",
            "placed",
        ),
    )
    action = parser.parse_args().action
    checks = {
        "control": lambda: mapping(predecessor=True),
        "placement-control": lambda: placed(predecessor=True),
        "mapping": mapping,
        "prepare-placement": prepare_placement,
        "placed": placed,
    }
    print(json.dumps(checks[action](), indent=2, sort_keys=True))
