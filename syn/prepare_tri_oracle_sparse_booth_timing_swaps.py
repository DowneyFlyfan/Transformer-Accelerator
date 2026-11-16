"""Refine the smaller buffered array with the existing timing-weighted swap code."""

from argparse import ArgumentParser
from collections import Counter
import json
from pathlib import Path
import re

import numpy as np
import torch

import prepare_tri_oracle_booth_timing_swaps as prior
from prepare_tri_oracle_gpu_array_placement import assignment
from verify_tri_oracle_array_placement_trials import pin_and_blockage_identity
from verify_tri_oracle_booth_placement import (
    LEF,
    components,
    dimensions,
    gates_script,
    occupancy,
)
from verify_tri_oracle_gated_compute_array import ROOT, digest, read
from verify_tri_oracle_sparse_booth_array import checked_region
from verify_tri_oracle_sparse_booth_control_buffers import WORK as BASE

WORK = BASE / "timing_swaps"
PROOF = Path("records/tri_oracle_sparse_booth_control_buffers.json")
COUNT = 57893


def inputs():
    record = read(PROOF)
    assert (
        record["added_buffers"] == 175
        and record["delivered_lockstep_transactions"] == 786
    )
    files = BASE / "placed.def", BASE / "netlist.v", BASE / "emitted.sdc"
    for path in files:
        assert digest(path) == record["evidence_sha256"][str(path)]
    return files


def export_script():
    script = prior.graph_script()
    assert script.count("64805") == 1
    return script.replace("64805", str(COUNT))


def prepare_export():
    for name, file in zip(
        ("graph_input.def", "netlist.v", "emitted.sdc"), inputs(), strict=True
    ):
        output = WORK / name
        if not output.is_symlink():
            output.symlink_to(file.resolve(strict=True))
        assert output.resolve(strict=True) == file.resolve(strict=True)
    (WORK / "export.tcl").write_text(export_script())


def place_script():
    script = gates_script()
    assert script.count("$count != 53622") == 1
    return script.replace("$count != 53622", f"$count != {COUNT}")


def plan_swaps():
    assert prior.memory_available() >= 9 * 2**30
    assert torch.cuda.mem_get_info()[0] >= 5 * 2**30
    torch.cuda.set_per_process_memory_fraction(0.12)
    torch.set_num_threads(4)
    prior.WORK = WORK
    assert (WORK / "export.tcl").read_text() == export_script()
    raw = inputs()[0]
    poses = sorted(components(raw))
    known = {name.decode().replace("\\", ""): i for i, (name, _) in enumerate(poses)}
    assert len(known) == len(poses) == COUNT
    sizes = dimensions([LEF], 2000)
    widths = np.array([sizes[pose[0]][0] for _, pose in poses])
    slots = np.array([pose[2:4] for _, pose in poses], dtype=np.int32)
    assert len(set(map(tuple, slots))) == COUNT
    edges, critical, ports, active = prior.graph(known, slots, raw.read_text())
    chosen, result = assignment(
        widths,
        slots,
        ports,
        edges,
        critical,
        active_cells=active,
        displacement_penalty=0.25,
    )
    head, body = raw.read_text().split("COMPONENTS ", 1)
    _, tail = body.split("END COMPONENTS\n", 1)
    with (WORK / "seed.def").open("w") as out:
        out.write(head + f"COMPONENTS {COUNT} ;\n")
        for i, (name, pose) in enumerate(poses):
            x, y, side = poses[chosen[i]][1][2:5]
            out.write(f"- {name.decode()} {pose[0]} + PLACED ( {x} {y} ) {side} ;\n")
        out.write("END COMPONENTS\n" + tail)
    (WORK / "place.tcl").write_text(place_script())
    result.update(
        seed_sha256=digest(WORK / "seed.def"),
        active_cells=int(active.sum()),
        displacement_penalty=0.25,
    )
    (WORK / "assignment.json").write_text(
        json.dumps(result, sort_keys=True, indent=2) + "\n"
    )


def verify():
    source, netlist, _ = inputs()
    assert (WORK / "netlist.v").resolve() == netlist.resolve()
    assert (WORK / "place.tcl").read_text() == place_script()
    assert (WORK / "export.tcl").read_text() == export_script()
    changes = read(WORK / "assignment.json")
    assert changes["seed_sha256"] == digest(WORK / "seed.def")
    console = (WORK / "console.log").read_text()
    assert re.search(r"(?m)^TRI_ORACLE_MAPPED_ARRAY_TIMING_FINISHED$", console)
    assert re.search(r"Message Summary:\s+\d+ warning\(s\), 0 error\(s\)", console)
    original = dict(components(source))
    placed = WORK / "placed.def"
    new = dict(components(placed))
    assert new == dict(components(WORK / "seed.def"))
    assert {name: pose[0] for name, pose in original.items()} == {
        name: pose[0] for name, pose in new.items()
    }
    sizes = dimensions([LEF], 2000)
    assert Counter(
        (sizes[pose[0]], *pose[2:5]) for pose in original.values()
    ) == Counter((sizes[pose[0]], *pose[2:5]) for pose in new.values())
    assert (
        sum(new[name] != pose for name, pose in original.items())
        == changes["moved_cells"]
    )
    assert pin_and_blockage_identity(placed.read_text()) == pin_and_blockage_identity(
        source.read_text()
    )
    region = checked_region()
    cells, used, capacity = occupancy(region.read_text(), placed)
    record = read(PROOF)
    assert cells == COUNT and capacity - used == record["remaining_sites"]
    modes = ("setup", "hold", "gate_setup", "gate_hold")
    reports = {name: WORK / f"native_{name}.rpt" for name in modes}
    timing = {
        name: min(map(float, re.findall(r"Slack:=\s+(-?\d+\.\d+)", path.read_text())))
        for name, path in reports.items()
    }
    docs = [
        PROOF,
        source,
        netlist,
        region,
        LEF,
        placed,
        *reports.values(),
        Path(__file__).resolve().relative_to(ROOT),
        Path(prior.__file__).resolve().relative_to(ROOT),
        Path(assignment.__code__.co_filename).resolve().relative_to(ROOT),
    ]
    docs.extend(
        WORK / name
        for name in (
            "seed.def",
            "export.tcl",
            "export.log",
            "operand_setup.rpt",
            "edges.tsv",
            "assignment.json",
            "place.tcl",
            "console.log",
            "placement.rpt",
        )
    )
    return {
        "state": "sparse_booth_array_timing_weighted_slot_swaps_measured",
        "clock_megahertz": record["clock_megahertz"],
        "same_netlist_and_row_sites": True,
        "remaining_row_sites": capacity - used,
        "assignment": changes,
        "before_slack_ns": record["buffered_sparse_array_slack_ns"],
        "after_slack_ns": timing,
        "scope": "One array. The mapped netlist, occupied site dimensions, boundary geometry and earlier lockstep result are preserved. Innovus uses early wire estimates and ideal clocks.",
        "evidence_sha256": {str(path): digest(path) for path in docs},
    }


if __name__ == "__main__":
    assert Path.cwd() == ROOT and __debug__
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare-export", "swaps", "verify"))
    action = parser.parse_args().action
    if action == "prepare-export":
        prepare_export()
    elif action == "swaps":
        plan_swaps()
    else:
        print(json.dumps(verify(), sort_keys=True, indent=2))
