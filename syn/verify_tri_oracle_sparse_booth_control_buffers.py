"""Transfer the verified readout control trees to the smaller Booth array."""

from argparse import ArgumentParser
import json
from pathlib import Path
import re

import verify_tri_oracle_array_control_buffers as tree
from verify_tri_oracle_array_placement_trials import pin_and_blockage_identity
from verify_tri_oracle_booth8 import simulation
from verify_tri_oracle_booth_placement import (
    LEF,
    components,
    dimensions,
    gates_script,
    occupancy,
    row_grid,
)
from verify_tri_oracle_gated_compute_array import PASS, ROOT, digest, read, renamed
from verify_tri_oracle_host_status import arguments
from verify_tri_oracle_sparse_booth_array import ARRAY, PLACED, checked_region

PROOF = Path("records/tri_oracle_sparse_booth_array_placement.json")
BASELINE = Path("records/tri_oracle_booth_control_buffers.json")
WORK = ARRAY / "control_buffers"
REPLAY = WORK / "replay"
BRANCHES = {
    "g619382": ("Z", 608),
    "g619932": ("Z", 608),
    "g619933": ("Z", 608),
    "hi_fo_buf620033": ("ZN", 353),
    "occupancy_onehot_reg[0]": ("Q", 257),
}


def prepared():
    proof = read(PROOF)
    region = checked_region()
    base_sdc = ARRAY / "emitted.sdc"
    layout = PLACED / "placed.def"
    netlist = ARRAY / "netlist.v"
    for path in (layout, netlist, base_sdc, region, LEF):
        assert digest(path) == proof["evidence_sha256"][str(path)], path
    cells = dict(components(layout))
    poses = {name.decode().replace("\\", ""): pose for name, pose in cells.items()}
    assert len(poses) == len(cells) == proof["mapped_cells"]
    rows, occupancy_grid, height = row_grid(region.read_text())
    left, bottom, _, cols, pitch = rows[0]
    sizes = dimensions([LEF], 2000)
    for master, status, x, y, _, _ in poses.values():
        sites, unused = divmod(sizes[master][0], pitch)
        j, dx = divmod(x - left, pitch)
        i, dy = divmod(y - bottom, height)
        assert status == "PLACED" and not (dx or dy or unused)
        assert 0 <= i < len(rows) and 0 <= j < j + sites <= cols
        assert not any(occupancy_grid[i][j : j + sites])
        occupancy_grid[i][j : j + sites] = b"\x01" * sites
    width, cell_height = sizes[tree.BUFFER]
    assert cell_height == height and width % pitch == 0
    sites_per_buffer = width // pitch
    gaps = [
        (i, m.start(), m.end())
        for i, row in enumerate(occupancy_grid)
        for m in re.finditer(rb"\x00+", row)
        if m.end() - m.start() >= sites_per_buffer
    ]

    def allocate(target_x, target_y):
        ideal = round((target_x - left) / pitch)
        candidates = []
        for index, (i, lo, hi) in enumerate(gaps):
            col = min(max(ideal, lo), hi - sites_per_buffer)
            distance = abs(left + col * pitch - target_x) + abs(rows[i][1] - target_y)
            candidates.append((distance, hi - lo, index, col))
        _, _, index, col = min(candidates)
        i, lo, hi = gaps.pop(index)
        gaps.extend(
            (i, a, b)
            for a, b in ((lo, col), (col + sites_per_buffer, hi))
            if b - a >= sites_per_buffer
        )
        return left + col * pitch, rows[i][1], rows[i][2]

    result, buffers = tree.edit(netlist.read_text(), poses, allocate, branches=BRANCHES)
    observed = len(poses) + len(buffers)
    seed = layout.read_text()
    seed = seed.replace(f"COMPONENTS {len(poses)} ;\n", f"COMPONENTS {observed} ;\n", 1)
    appended = "".join(
        f"- {name} {tree.BUFFER} + PLACED ( {x} {y} ) {side} ;\n"
        for name, _, _, x, y, side in buffers
    )
    assert seed.count("END COMPONENTS\n") == 1
    seed = seed.replace("END COMPONENTS\n", appended + "END COMPONENTS\n", 1)
    script = gates_script().replace("$count != 53622", f"$count != {observed}")
    assert f"$count != {observed}" in script
    return result, seed, script, observed, len(buffers), sites_per_buffer


def prepare():
    mapped, seeded, script, *_ = prepared()
    REPLAY.mkdir(parents=True, exist_ok=True)
    for path, data in (
        ("netlist.v", mapped),
        ("seed.def", seeded),
        ("place.tcl", script),
    ):
        (WORK / path).write_text(data)
    sdc = WORK / "emitted.sdc"
    if not sdc.is_symlink():
        sdc.symlink_to((ARRAY / sdc.name).resolve(strict=True))
    assert sdc.resolve(strict=True) == (ARRAY / sdc.name).resolve()
    dut = REPLAY / "decoupled_mapped.v"
    dut.write_text(renamed(mapped))
    argv = arguments(ARRAY / "replay/xrun.history")
    argv[argv.index(str((ARRAY / "replay/decoupled_mapped.v").resolve()))] = str(
        dut.resolve()
    )
    (REPLAY / "args.json").write_text(json.dumps(argv))


def verify():
    mapped, seeded, tcl, count, buffers, width = prepared()
    for key, wanted in (
        ("netlist.v", mapped),
        ("seed.def", seeded),
        ("place.tcl", tcl),
    ):
        assert (WORK / key).read_text() == wanted
    assert (WORK / "emitted.sdc").resolve(strict=True) == (
        ARRAY / "emitted.sdc"
    ).resolve()
    proof = read(PROOF)
    prior = read(BASELINE)
    placed = WORK / "placed.def"
    console = (WORK / "console.log").read_text()
    assert re.search(r"(?m)^TRI_ORACLE_MAPPED_ARRAY_TIMING_FINISHED$", console)
    assert re.search(r"Message Summary:\s+\d+ warning\(s\), 0 error\(s\)", console)
    native = dict(components(placed))
    assert native == dict(components(WORK / "seed.def"))
    assert all(native[name] == pose for name, pose in components(PLACED / "placed.def"))
    region = checked_region()
    assert pin_and_blockage_identity(placed.read_text()) == pin_and_blockage_identity(
        region.read_text()
    )
    cells, sites, capacity = occupancy(region.read_text(), placed)
    assert cells == count == proof["mapped_cells"] + buffers
    assert sites == proof["row_sites"] + buffers * width
    assert capacity == proof["same_region_row_site_capacity"]
    dut = REPLAY / "decoupled_mapped.v"
    assert dut.read_text() == renamed(mapped)
    assert arguments(REPLAY / "xrun.history") == read(REPLAY / "args.json")
    evidence = simulation(REPLAY, PASS, [dut], "decoupled_lockstep_tb")
    slack = {}
    for mode in ("setup", "hold", "gate_setup", "gate_hold"):
        report = WORK / f"native_{mode}.rpt"
        measurements = re.findall(r"Slack:=\s+(-?\d+\.\d+)", report.read_text())
        assert measurements, report
        slack[mode] = min(map(float, measurements))
        evidence.append(report)
    evidence.extend(
        (
            PROOF,
            BASELINE,
            region,
            dut,
            PLACED / "placed.def",
            Path(__file__).resolve().relative_to(ROOT),
            Path(tree.__file__).resolve().relative_to(ROOT),
        )
    )
    evidence.extend(
        WORK / name
        for name in (
            "netlist.v",
            "seed.def",
            "placed.def",
            "place.tcl",
            "console.log",
            "placement.rpt",
            "emitted.sdc",
        )
    )
    return {
        "state": "sparse_booth_control_buffers_placed_and_lockstep_verified",
        "clock_megahertz": proof["clock_megahertz"],
        "added_buffers": buffers,
        "added_row_sites": buffers * width,
        "remaining_sites": capacity - sites,
        "delivered_lockstep_transactions": 786,
        "same_array_unbuffered_slack_ns": proof["pre_route_slack_ns"],
        "prior_booth_with_same_buffer_recipe_slack_ns": prior[
            "pre_route_slack_after_ns"
        ],
        "buffered_sparse_array_slack_ns": slack,
        "scope": "One 32-by-8 array with the verified queue-control buffer recipe. Original placements and boundary ports are preserved. Early wire estimates and ideal clocks are used.",
        "evidence_sha256": {str(path): digest(path) for path in evidence},
    }


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "verify"))
    if parser.parse_args().action == "prepare":
        prepare()
    else:
        print(json.dumps(verify(), indent=2, sort_keys=True))
