"""Check data-control buffer trees on the placed Booth array."""

import argparse
from pathlib import Path
import json
import re

import verify_tri_oracle_array_control_buffers as tree
from verify_tri_oracle_array_placement_trials import (
    early_congestion,
    pin_and_blockage_identity,
)
from verify_tri_oracle_booth8 import simulation
from verify_tri_oracle_gated_compute_array import PASS, ROOT, renamed
from verify_tri_oracle_host_status import arguments
from verify_tri_oracle_booth_placement import (
    LEF,
    WORK as BASE,
    components,
    digest,
    dimensions,
    gates_script,
    occupancy,
    read,
    row_grid,
)

WORK = BASE / "control_buffers"


def prepared():
    prior = read(Path("records/tri_oracle_booth_array_placement.json"))
    old = BASE / "placed.def"
    netlist = BASE.parent / "netlist.v"
    region = (BASE / "region.def").resolve()
    assert digest(old) == prior["evidence_sha256"][str(old)]
    assert digest(netlist) == prior["evidence_sha256"][str(netlist)]
    assert (
        digest(region) == prior["evidence_sha256"][str(region.relative_to(Path.cwd()))]
    )
    locations = {
        name.decode().replace("\\", ""): pose for name, pose in components(old)
    }
    assert len(locations) == prior["placed_cells"]
    rows, occupied, height = row_grid(region.read_text())
    left, bottom, _, columns, pitch = rows[0]
    sizes = dimensions([LEF], 2000)
    for master, status, x, y, _, _ in locations.values():
        width, cell_height = sizes[master]
        row, y_offset = divmod(y - bottom, height)
        col, x_offset = divmod(x - left, pitch)
        span, width_offset = divmod(width, pitch)
        assert (
            status == "PLACED"
            and cell_height == height
            and not any((x_offset, y_offset, width_offset))
        )
        assert 0 <= row < len(rows) and 0 <= col < col + span <= columns
        assert not any(occupied[row][col : col + span])
        occupied[row][col : col + span] = b"\x01" * span
    gaps = [
        (row, match.start(), match.end())
        for row, bits in enumerate(occupied)
        for match in re.finditer(rb"\x00+", bits)
    ]
    assert sum(stop - start for _, start, stop in gaps) == prior["remaining_row_sites"]
    width = sizes[tree.BUFFER][0] // pitch
    assert sizes[tree.BUFFER] == (width * pitch, height)

    def allocate(target_x, target_y):
        ideal = round((target_x - left) / pitch)
        options = []
        for index, (row, start, stop) in enumerate(gaps):
            if stop - start >= width:
                col = min(max(start, ideal), stop - width)
                distance = abs(left + col * pitch - target_x) + abs(
                    rows[row][1] - target_y
                )
                options.append((distance, stop - start, index, col))
        _, _, index, col = min(options)
        row, start, stop = gaps.pop(index)
        gaps.extend(
            (row, a, b) for a, b in ((start, col), (col + width, stop)) if a < b
        )
        return left + col * pitch, rows[row][1], rows[row][2]

    branches = {
        "g619382": ("Z", 608),
        "g619932": ("Z", 608),
        "g619933": ("Z", 608),
        "hi_fo_buf620033": ("ZN", 353),
        "occupancy_onehot_reg[0]": ("Q", 257),
    }
    mapped, buffers = tree.edit(
        netlist.read_text(), locations, allocate, branches=branches
    )
    layout = old.read_text()
    before = len(locations)
    after = before + len(buffers)
    layout = layout.replace(f"COMPONENTS {before} ;\n", f"COMPONENTS {after} ;\n", 1)
    additions = "".join(
        f"- {name} {tree.BUFFER} + PLACED ( {x} {y} ) {side} ;\n"
        for name, _, _, x, y, side in buffers
    )
    layout = layout.replace("END COMPONENTS\n", additions + "END COMPONENTS\n", 1)
    return (
        mapped,
        layout,
        gates_script().replace("$count != 53622", f"$count != {after}"),
        len(buffers),
        width,
    )


def prepare():
    WORK.mkdir(exist_ok=True)
    mapped, seed, tcl, _, _ = prepared()
    for name, text in (("netlist.v", mapped), ("seed.def", seed), ("place.tcl", tcl)):
        (WORK / name).write_text(text)
    sdc = WORK / "emitted.sdc"
    if not sdc.is_symlink():
        sdc.symlink_to((BASE / "emitted.sdc").resolve(strict=True))


def verify():
    mapped, seed, tcl, buffers, width = prepared()
    for name, expected in (
        ("netlist.v", mapped),
        ("seed.def", seed),
        ("place.tcl", tcl),
    ):
        assert (WORK / name).read_text() == expected
    assert (WORK / "emitted.sdc").resolve(strict=True) == (
        BASE / "emitted.sdc"
    ).resolve(strict=True)
    console = (WORK / "console.log").read_text()
    assert re.search(r"(?m)^TRI_ORACLE_MAPPED_ARRAY_TIMING_FINISHED$", console)
    assert re.search(r"Message Summary:\s+\d+ warning\(s\), 0 error\(s\)", console)
    baseline = Path("records/tri_oracle_booth_array_placement.json")
    area = Path("records/tri_oracle_booth_array.json")
    previous = read(baseline)
    placed = WORK / "placed.def"
    new_cells = dict(components(placed))
    old_cells = dict(components(BASE / "placed.def"))
    assert dict(components(WORK / "seed.def")) == new_cells
    assert all(new_cells[name] == pose for name, pose in old_cells.items())
    region = BASE / "region.def"
    assert pin_and_blockage_identity(placed.read_text()) == pin_and_blockage_identity(
        region.read_text()
    )
    count, used, total = occupancy(region.read_text(), placed)
    assert count == previous["placed_cells"] + buffers
    assert used == previous["placed_row_sites"] + buffers * width
    assert total == previous["available_row_sites"]

    replay = WORK / "replay"
    dut = replay / "decoupled_mapped.v"
    assert dut.read_text() == renamed(mapped)
    logs = simulation(replay, PASS, [dut], "decoupled_lockstep_tb")
    reference = BASE.parent / "mapped_replay"
    argv = arguments(reference / "xrun.history")
    argv[argv.index(str((reference / "decoupled_mapped.v").resolve()))] = str(
        dut.resolve()
    )
    assert arguments(replay / "xrun.history") == argv

    reports = [
        WORK / f"native_{name}.rpt"
        for name in ("setup", "hold", "gate_setup", "gate_hold")
    ]
    slack = {
        p.stem.removeprefix("native_"): min(
            map(float, re.findall(r"Slack:=\s+(-?\d+\.\d+)", p.read_text()))
        )
        for p in reports
    }
    assert slack["setup"] > previous["pre_route_slack_ns"]["setup"]
    evidence = [
        baseline,
        area,
        BASE / "placed.def",
        region.resolve().relative_to(ROOT),
        dut,
        *logs,
        *reports,
        Path(__file__).resolve().relative_to(ROOT),
        Path(tree.__file__).resolve().relative_to(ROOT),
    ]
    evidence.extend(
        WORK / name
        for name in (
            "netlist.v",
            "seed.def",
            "placed.def",
            "place.tcl",
            "console.log",
            "placement.rpt",
        )
    )
    return dict(
        state="booth_array_data_control_buffers_placed_and_lockstep_verified",
        clock_megahertz=previous["clock_megahertz"],
        added_buffers=buffers,
        added_row_sites=buffers * width,
        remaining_row_sites=total - used,
        delivered_lockstep_transactions=786,
        pre_route_slack_before_ns=previous["pre_route_slack_ns"],
        pre_route_slack_after_ns=slack,
        early_congestion=early_congestion(console),
        scope="The original cell locations, region and boundary pins are preserved. Timing uses early wire estimates and an ideal clock.",
        evidence_sha256={str(path): digest(path) for path in evidence},
    )


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("action", choices=("prepare", "verify"))
    if cli.parse_args().action == "prepare":
        prepare()
    else:
        print(json.dumps(verify(), indent=2, sort_keys=True))
