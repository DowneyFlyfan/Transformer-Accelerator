"""Prepare and verify the Booth array placement in the fixed array region."""

import argparse
import json
from pathlib import Path
import re

from verify_tri_oracle_array_placement_trials import (
    early_congestion,
    pin_and_blockage_identity,
)
from verify_tri_oracle_booth_array import ARRAY
from verify_tri_oracle_gated_array_placement import (
    CHECKER,
    LEF,
    ROOT,
    WORK as BASE,
    components,
    digest,
    dimensions,
    gates_script,
    read,
    row_grid,
)

WORK = ARRAY / "native_placement"
PROOF = Path("records/tri_oracle_booth_array.json")
REGIONAL_FIXTURE = Path("records/tri_oracle_gated_array_placement.json")


def inputs(proof):
    region = BASE / "region.def"
    base = read(REGIONAL_FIXTURE)
    paths = (region, ARRAY / "netlist.v", ARRAY / "emitted.sdc")
    for path, record in zip(paths, (base, proof, proof), strict=True):
        assert digest(path) == record["evidence_sha256"][str(path)], path
    assert digest(LEF) == base["evidence_sha256"][str(LEF)], LEF
    return paths


def placement_script(count):
    text = gates_script()
    assert text.count("read_def $out/seed.def") == text.count("$count != 53622") == 1
    return text.replace(
        "read_def $out/seed.def",
        "read_def $out/region.def\nplace_design -no_pre_place_opt\nwrite_def $out/attempt.def",
    ).replace("$count != 53622", f"$count != {count}")


def prepare():
    proof = read(PROOF)
    WORK.mkdir(exist_ok=True)
    for path in inputs(proof):
        link = WORK / path.name
        if not link.is_symlink():
            link.symlink_to(path.resolve(strict=True))
        assert link.resolve(strict=True) == path.resolve(strict=True)
    (WORK / "place.tcl").write_text(placement_script(proof["booth_mapped_cells"]))


def occupancy(region, placed):
    rows, occupied, height = row_grid(region)
    placed_rows, _, _ = row_grid(placed.read_text())
    assert placed_rows == rows
    left, bottom, _, columns, pitch = rows[0]
    size = dimensions([LEF], 2000)
    free = sum(bits.count(0) for bits in occupied)
    cells = dict(components(placed))
    used = 0
    for name, (master, status, x, y, _, _) in cells.items():
        width, cell_height = size[master]
        row, y_offset = divmod(y - bottom, height)
        col, x_offset = divmod(x - left, pitch)
        sites, extra_width = divmod(width, pitch)
        assert (
            status == "PLACED"
            and cell_height == height
            and not any((x_offset, y_offset, extra_width))
        ), name
        assert 0 <= row < len(rows) and 0 <= col < col + sites <= columns, name
        assert not any(occupied[row][col : col + sites]), name
        occupied[row][col : col + sites] = b"\x01" * sites
        used += sites
    assert free - used == sum(bits.count(0) for bits in occupied)
    return len(cells), used, free


def verify():
    proof = read(PROOF)
    region, netlist, sdc = inputs(proof)
    count = proof["booth_mapped_cells"]
    for path in (region, netlist, sdc):
        assert (WORK / path.name).resolve(strict=True) == path.resolve(strict=True)
    assert (WORK / "place.tcl").read_text() == placement_script(count)
    console = (WORK / "console.log").read_text()
    assert re.search(r"(?m)^TRI_ORACLE_MAPPED_ARRAY_TIMING_FINISHED$", console)
    assert re.search(
        r"(?m)^TRI_ORACLE_GATED_ARRAY_PLACED " + str(count) + r" [0-9.]+$", console
    )
    errors = re.findall(
        r"Message Summary:\s+\d+ warning\(s\), (\d+) error\(s\)", console
    )
    assert set(errors) == {"0"}
    report = (WORK / "placement.rpt").read_text()
    assert re.search(rf"(?m)^\*info: Placed = {count}\s*$", report)
    assert re.search(r"(?m)^\*info: Unplaced = 0\s*$", report)
    assert re.search(r"(?m)^Finished check_place ", report)
    placed, attempt = (WORK / name for name in ("placed.def", "attempt.def"))
    assert dict(components(placed)) == dict(components(attempt))
    assert pin_and_blockage_identity(placed.read_text()) == pin_and_blockage_identity(
        region.read_text()
    )
    geometry = re.compile(r"(?m)^DIEAREA .+;$")
    assert (
        geometry.search(placed.read_text())[0] == geometry.search(region.read_text())[0]
    )
    n, sites, total = occupancy(region.read_text(), placed)
    assert n == count and sites == proof["booth_row_sites"]
    timings = [
        WORK / f"native_{mode}.rpt"
        for mode in ("setup", "hold", "gate_setup", "gate_hold")
    ]
    slack = {
        file.stem.removeprefix("native_"): min(
            map(float, re.findall(r"Slack:=\s+(-?\d+\.\d+)", file.read_text()))
        )
        for file in timings
    }
    setup = timings[0].read_text()
    starts = re.findall(r"(?m)^\s+Startpoint: \([RF]\) (.+)$", setup)
    ends = re.findall(r"(?m)^\s+Endpoint: \([RF]\) (.+)$", setup)
    assert len(starts) == len(ends) == 12
    inputs_and_outputs = [
        PROOF,
        REGIONAL_FIXTURE,
        region,
        netlist,
        sdc,
        LEF,
        CHECKER,
        attempt,
        placed,
        *timings,
        *(WORK / name for name in ("place.tcl", "console.log", "placement.rpt")),
        Path(__file__).resolve().relative_to(ROOT),
    ]
    return dict(
        state="full_booth_array_legal_in_saved_region",
        clock_megahertz=proof["clock_megahertz"],
        placed_cells=n,
        placed_row_sites=sites,
        available_row_sites=total,
        remaining_row_sites=total - sites,
        placement_density_percent=float(
            re.search(r"Placement Density:([0-9.]+)%", report)[1]
        ),
        early_congestion=early_congestion(console),
        pre_route_slack_ns=slack,
        worst_setup_endpoints=[starts[0], ends[0]],
        scope="One compute-array region with the original pin and blockage reservations and unchanged mapped logic. "
        "Timing uses early wire estimates and an ideal clock.",
        evidence_sha256={str(path): digest(path) for path in inputs_and_outputs},
    )


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("action", choices=("prepare", "verify"))
    if cli.parse_args().action == "prepare":
        prepare()
    else:
        print(json.dumps(verify(), indent=2, sort_keys=True))
