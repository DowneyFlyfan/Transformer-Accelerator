"""Check the emitted Booth chip placement against its physical grid and keepouts."""

from collections import Counter
from itertools import combinations
import json
from mmap import ACCESS_READ, mmap
from pathlib import Path
import re

from audit_tri_oracle_pad_ring_clearance import contains, dimensions, overlap
from audit_tri_oracle_physical_io_budget import macro_boxes
from plan_tri_oracle_bonded_pad_recovery import ROW, section
from verify_tri_oracle_booth_chip_link import TOP, WORK
from verify_tri_oracle_booth_fence_capacity import PAD, TRANSFER, read_table
from verify_tri_oracle_gated_compute_array import ROOT, digest, read
from verify_tri_oracle_pad_cold_reload import components

SEED = Path("records/tri_oracle_booth_chip_seed.json")
AREA = Path("records/tri_oracle_booth_fence_capacity.json")
TARGET = Path("records/paper_result_targets.json")

BOX = r"\( (\d+) (\d+) \) \( (\d+) (\d+) \)"


def rectangles(lines, prefix):
    return [
        tuple(map(int, re.fullmatch(prefix + BOX + r" ;", line).groups()))
        for line in lines.splitlines()
    ]


def geometry(path, verify_top):
    with (
        path.open("rb") as stream,
        mmap(stream.fileno(), 0, access=ACCESS_READ) as data,
    ):
        blockages = rectangles(section(data, b"BLOCKAGES"), r"\s*- PLACEMENT RECT ")
        if not verify_top:
            return blockages
        end_header = data.find(b"\nCOMPONENTS ")
        assert end_header > 0
        header = data[:end_header].decode()
        assert re.search(rf"(?m)^DESIGN {TOP} ;$", header)
        regions = {}
        for line in section(data, b"REGIONS").splitlines():
            name, *bounds = re.fullmatch(r"- (\w+) " + BOX + r" ;", line).groups()
            assert name not in regions
            regions[name] = tuple(map(int, bounds))
        groups = {}
        for name, member, region in re.findall(
            r"(?m)^- (\w+)\n +([^\s*]+/)\*\n +\+ REGION (\w+) ;$",
            section(data, b"GROUPS"),
        ):
            assert name == region and member.encode() not in groups
            groups[member.encode()] = region

    rows = {}
    for match in re.finditer(ROW.pattern, header, re.MULTILINE):
        x, y, side, length, pitch = match.groups()
        y = int(y)
        assert y not in rows
        rows[y] = int(x), side, int(length), int(pitch)
    units = int(re.search(r"(?m)^UNITS DISTANCE MICRONS (\d+) ;$", header)[1])
    die = tuple(map(int, re.search(r"(?m)^DIEAREA " + BOX + r" ;$", header).groups()))
    return die, units, rows, regions, groups, blockages


def layout(path, dims, rows, regions, groups, keepouts, memories, height):
    """Rasterize obstructions, then stream and check every cell from the file."""
    assert len(set(keepouts)) == len(keepouts)
    common_x, _, columns, pitch = next(iter(rows.values()))
    levels = sorted(rows)
    bottom = levels[0]
    assert levels == list(range(bottom, bottom + len(rows) * height, height))
    grid = [bytearray(columns) for _ in levels]
    for x1, y1, x2, y2 in keepouts:
        assert x1 < x2 and y1 < y2
        col0 = max(0, (x1 - common_x) // pitch)
        col1 = min(columns, -(-(x2 - common_x) // pitch))
        first = max(0, (y1 - bottom) // height)
        last = min(len(grid), -(-(y2 - bottom) // height))
        if col1 > col0:
            blocked = b"\x01" * (col1 - col0)
            for row in range(first, last):
                grid[row][col0:col1] = blocked
    capacity = sum(row.count(0) for row in grid)

    assert all(
        x == common_x and length == columns and step == pitch
        for x, _, length, step in rows.values()
    )
    root = next(iter(groups)).split(b"/clusters")[0]
    owner = re.compile(
        re.escape(root) + rb"/clusters.*?/cores\\\[\d+\\\]/compute/compute/"
    )
    census, region_sites, region_counts = Counter(), Counter(), Counter()
    for name, pose in components(path):
        master, status, x, y, rotation, _ = pose
        census[status] += 1
        if status == "FIXED":
            assert memories.pop(name) == pose, name
            continue
        assert status == "PLACED" and y in rows, (name, pose)
        width, standard_height = dims[master]
        assert standard_height == height and width > 0 and width % pitch == 0, master
        expected = ("N", "FN") if rows[y][1] == "N" else ("FS", "S")
        assert rotation in expected, (name, rotation, expected)
        column, dx = divmod(x - common_x, pitch)
        end = column + width // pitch
        assert dx == 0 and 0 <= column < end <= columns, (name, pose)
        row = grid[(y - bottom) // height]
        assert row.find(b"\x01", column, end) == -1, (name, pose, "occupied")
        row[column:end] = b"\x01" * (end - column)
        if match := owner.match(name):
            region = groups[match[0]]
            assert contains(regions[region], (x, y, x + width, y + height)), name
            region_counts[region] += 1
            region_sites[region] += end - column
    assert not memories
    region_free = {}
    for name, (x1, y1, x2, y2) in regions.items():
        left = max(0, -(-(x1 - common_x) // pitch))
        right = min(columns, (x2 - common_x) // pitch)
        lo = max(0, -(-(y1 - bottom) // height))
        hi = min(len(grid), (y2 - bottom) // height)
        region_free[name] = sum(grid[i].count(0, left, right) for i in range(lo, hi))
    return (
        census,
        region_counts,
        region_sites,
        region_free,
        capacity,
        sum(row.count(0) for row in grid),
    )


def verify():
    evidence = {}

    def pin(path):
        evidence[str(path)] = digest(path)
        return path

    seed, area, pad, transfer, target = (
        read(pin(path)) for path in (SEED, AREA, PAD, TRANSFER, TARGET)
    )
    placement = pin(WORK / "placement_seed.def")
    assert evidence[str(placement)] == seed["evidence_sha256"][str(placement)]
    sources = {}
    for name, expected in pad["evidence_sha256"].items():
        path = pin(Path(name))
        assert evidence[name] == expected
        sources[path.name] = path
    cold = sources["layout.def"]

    die, units, rows, regions, groups, keepouts = geometry(placement, verify_top=True)
    width_mm, height_mm = [
        (hi - lo) / (1000 * units) for lo, hi in zip(die[:2], die[2:])
    ]
    assert [width_mm, height_mm] == target["silicon"]["die_dimensions_mm"]
    assert len(rows) == 2966 and units == 2000
    row_height = 2400
    assert all(
        contains(die, (x, y, x + length * pitch, y + row_height))
        for y, (x, _, length, pitch) in rows.items()
    )
    assert len(groups) == len(regions) == 20 and set(groups.values()) == regions.keys()
    assert all(contains(die, box) for box in regions.values())
    assert not any(overlap(a, b) for a, b in combinations(regions.values(), 2))

    pads = read_table(sources["pad_slots.tsv"])
    expected_pads = [
        tuple(int(row["keepout_" + xy]) for xy in ("x1", "y1", "x2", "y2"))
        for row in pads
    ]
    expected_corners = geometry(cold, verify_top=False)
    assert len(expected_corners) == 4 and len(expected_pads) == pad["pad_reservations"]
    assert Counter(keepouts) == Counter(expected_corners + expected_pads)
    assert all(contains(die, box) for box in keepouts)

    dims = dimensions([p for p in sources.values() if p.suffix == ".lef"], units)
    moves = {
        row["instance"].encode(): row
        for row in read_table(sources["memory_macros.tsv"])
    }
    memories = {}
    count_moved = len(moves)
    for name, pose in components(cold):
        master, status, x, y, rotation, halo = pose
        if status == "FIXED":
            if move := moves.pop(name, None):
                assert move["master"] == master and move["orientation"] == rotation
                x, y = int(move["x_dbu"]), int(move["y_dbu"])
            memories[transfer["path_prefix"].encode() + name] = (
                master,
                status,
                x,
                y,
                rotation,
                halo,
            )
    assert not moves and count_moved == seed["shifted_memory_macros"]
    bodies, halos = macro_boxes(memories, dims)
    assert all(contains(die, box) for box in halos.values())
    assert not any(overlap(a, b) for a, b in combinations(halos.values(), 2))
    assert not any(overlap(box, pad) for box in halos.values() for pad in expected_pads)
    assert not any(
        overlap(box, corner) for box in bodies.values() for corner in expected_corners
    )

    counts, arrays, footprints, region_free, capacity, unused = layout(
        placement,
        dims,
        rows,
        regions,
        groups,
        keepouts + list(halos.values()),
        memories,
        row_height,
    )
    assert counts["FIXED"] == seed["fixed_memory_macros"]
    assert counts.total() == seed["exact_linked_leaf_count"]
    assert (
        capacity == area["geometric_capacity"]
        and unused == area["projected_remaining_global_sites"]
    )
    assert arrays == {key: area["leaf_cells_per_array"] for key in regions}
    assert footprints == {key: area["row_sites_per_array"] for key in regions}
    assert sum(region_free.values()) <= unused
    pin(Path(__file__).resolve().relative_to(ROOT))
    return {
        "state": "linked_booth_chip_emitted_placement_geometry_verified",
        "die_dimensions_mm": [width_mm, height_mm],
        "standard_cells_verified": counts["PLACED"],
        "fixed_memories_verified": counts["FIXED"],
        "array_regions_verified": len(arrays),
        "reservation_rectangles_verified": len(keepouts),
        "row_sites_capacity": capacity,
        "row_sites_occupied_by_standard_cells": capacity - unused,
        "row_sites_free_after_placement": unused,
        "row_sites_free_by_array_region": region_free,
        "scope": "Outlines, row alignment, overlaps, memory halos, pad keepouts and compute region membership were checked directly on the emitted file. Native import, pin geometry, timing and routing require separate verification.",
        "evidence_sha256": evidence,
    }


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    print(json.dumps(verify(), indent=2, sort_keys=True))
