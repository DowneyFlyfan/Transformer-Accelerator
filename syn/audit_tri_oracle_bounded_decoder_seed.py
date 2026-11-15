"""Place the smaller decoder revision on exact sites of the retained floorplan."""

import argparse
from bisect import bisect_left, insort
from collections import Counter, defaultdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from audit_tri_oracle_dual_group_placement_seed import candidates, read_rows, verify_geometry
from audit_tri_oracle_pad_ring_clearance import dimensions
from audit_tri_oracle_placed_chip_boundary import digest
from audit_tri_oracle_weight_loader_placement_region import (
    DISTANCE_UNITS, HEIGHT, ORIGIN_X, PITCH, WORD_DECODER, free_intervals, loader_inventory, sites,
)
from prepare_tri_oracle_dual_group_placement_seed import RAW_PARENT, def_name, sorted_rows
from scan_tri_oracle_dual_group_halos import read, seed_geometry
from verify_tri_oracle_pad_cold_reload import COMPONENTS, boundary_sections, components
from verify_tri_oracle_seed_components import INSTANCE, expanded_instances


DECODER_RECORD = Path("records/tri_oracle_bounded_weight_decoder.json")
REGION_RECORD = Path("records/tri_oracle_weight_loader_placement_region.json")


def pack_cells(gaps, cells, *, avoid_one_site):
    """Use the smallest sufficient interval and optionally preserve usable tails."""
    by_width = defaultdict(list)
    for y, start, end in reversed(gaps):
        by_width[end - start].append((y, start))
    available = sorted(by_width)
    placements = {}
    for width, name in sorted(cells, key=lambda item: (-item[0], item[1])):
        index = bisect_left(available, width)
        if index == len(available):
            return None
        if avoid_one_site and available[index] == width + 1 and index + 1 < len(available):
            index += 1
        size = available[index]
        y, start = by_width[size].pop()
        if not by_width[size]:
            available.pop(index)
        placements[name] = y, start
        remaining = size - width
        if remaining:
            if not by_width[remaining]:
                insort(available, remaining)
            by_width[remaining].append((y, start + width))
    assert len(placements) == len(cells)
    return placements


def divide_gaps(intervals, box, margin_um):
    margin = margin_um * DISTANCE_UNITS
    left, bottom, right, top = box
    first = -(-(left - margin - ORIGIN_X) // PITCH)
    last = (right + margin - ORIGIN_X) // PITCH
    inner, outer = [], []
    for y, row in intervals:
        for start, end in row:
            lo, hi = max(start, first), min(end, last)
            if lo >= hi or y < bottom - margin or y + HEIGHT > top + margin:
                outer.append((y, start, end))
                continue
            inner.append((y, lo, hi))
            if start < lo:
                outer.append((y, start, lo))
            if hi < end:
                outer.append((y, hi, end))
    return inner, outer


def new_inventory(seed, old_map, new_map):
    def leaves(path):
        instances = [(name.decode().removeprefix("\\"), master.decode())
                     for master, name in INSTANCE.findall(path.read_bytes())]
        assert len(dict(instances)) == len(instances)
        return dict(instances)

    prior, current = leaves(old_map), leaves(new_map)
    windows = defaultdict(dict)
    untouched = {}
    removed = set()
    with seed.open() as stream:
        read_rows(stream)
        for raw_name, master, status, _ in candidates(stream):
            if status != "UNPLACED":
                continue
            name = raw_name.replace("\\", "")
            decoder = WORD_DECODER.match(name[len(RAW_PARENT):]) if name.startswith(RAW_PARENT) else None
            if decoder:
                root = len(RAW_PARENT) + decoder.end()
                windows[name[:root]][name[root:]] = master
                removed.add(name)
            else:
                untouched[name] = master
    assert len(windows) == 4 and all(inventory == prior for inventory in windows.values())
    assert len(removed) == 4 * len(prior)
    added = {group + leaf: master for group in windows for leaf, master in current.items()}
    assert len(added) == 4 * len(current) and not added.keys() & untouched.keys()
    return removed, untouched, added


def write_coordinates(source, destination, removed, added, new_poses, count):
    def placed(name, master):
        x, y, orientation = new_poses[name]
        escaped = def_name(name.encode()).decode()
        return f"- {escaped} {master} + PLACED ( {x} {y} ) {orientation} ;\n"

    with source.open() as prior, destination.open("x") as updated:
        in_components = False
        for line in prior:
            if COMPONENTS.fullmatch(line):
                in_components = True
                updated.write(f"COMPONENTS {count} ;\n")
            elif in_components and line == "END COMPONENTS\n":
                in_components = False
                updated.writelines(placed(name, master) for name, master in sorted(added.items()))
                updated.write(line)
            elif in_components and line.endswith("+ UNPLACED ;\n"):
                _, spelling, master, *_ = line.split()
                name = spelling.replace("\\", "")
                if name not in removed:
                    updated.write(placed(name, master))
            else:
                updated.write(line)


def verify_inventory(candidate, source, layout, expected, removed, placed, fixed):
    """Independently compare every materialized instance with the mapped hierarchy."""
    with TemporaryDirectory(dir=layout.parent, prefix="verified_layout_inventory_") as temporary:
        folder = Path(temporary)
        netlist, count = sorted_rows(folder, "mapped", (name + b"\t" + master
                                                        for name, master in expanded_instances(candidate)), 4)

        def physical():
            retained = Counter()
            with source.open() as original:
                read_rows(original)
                prior = (row for row in candidates(original) if row[2] != "UNPLACED")
                for spelling, (master, status, x, y, orientation, clearance) in components(layout):
                    name = spelling.replace(b"\\", b"")
                    text = name.decode()
                    if text in expected:
                        assert status == "PLACED" and (x, y, orientation) == expected[text]
                    else:
                        assert text not in removed
                        assert next(prior) == (spelling.decode(), master, status, (x, y, orientation, clearance))
                        retained[status] += 1
                    yield name + b"\t" + master.encode()
                assert next(prior, None) is None
            assert retained == {"PLACED": placed, "FIXED": fixed}

        planned, actual = sorted_rows(folder, "planned", physical(), 4)
        assert count == actual == placed + fixed + len(expected)
        with netlist.open("rb") as old, planned.open("rb") as new:
            last = b""
            for mapped, written in zip(old, new, strict=True):
                assert mapped == written and written > last
                assert written.partition(b"\t")[0] != last.partition(b"\t")[0]
                last = written
        return count, digest(planned)


def run(candidate, seed, library, old_map, new_map, output):
    decoder = read(DECODER_RECORD)
    region = read(REGION_RECORD)
    libraries = sorted(library.glob("*.lef"))
    assert len(libraries) == 7
    evidence = {str(path): digest(path) for path in (candidate, seed, old_map, new_map, *libraries)}
    assert evidence[str(candidate)] == decoder["whole_chip_link"]["candidate_sha256"]
    assert all(evidence[str(path)] == region["evidence_sha256"][str(path)] for path in (seed, *libraries))
    assert all(evidence[str(path)] == decoder["evidence_sha256"][str(path)] for path in (old_map, new_map))
    sizes = dimensions(libraries, DISTANCE_UNITS)
    _, _, bounds, _ = loader_inventory(seed, sizes)
    rows, macros, _, reserves, old_demand, retained = seed_geometry(seed, sizes)
    removed, untouched, added = new_inventory(seed, old_map, new_map)
    final_cells = untouched | added
    assert old_demand.total() == len(removed) + len(untouched)
    inner_cells, outer_cells = [], []
    for name, master in final_cells.items():
        width, height = sizes[master]
        assert width % PITCH == 0 and height == HEIGHT
        (inner_cells if name.startswith(RAW_PARENT) else outer_cells).append((width // PITCH, name))
    assert sum(width for width, _ in inner_cells) == decoder["projected_regional_geometry"]["new_loader_sites"]
    intervals = list(free_intervals(rows, macros, reserves))
    too_small, _ = divide_gaps(intervals, bounds, 1000)
    large_need = sum(width for width, _ in inner_cells if width >= 3)
    large_supply = sum(end - start for _, start, end in too_small if end - start >= 3)
    assert large_need > large_supply
    inner, outer = divide_gaps(intervals, bounds, 1025)
    assert pack_cells(inner, inner_cells, avoid_one_site=False) is None
    inside = pack_cells(inner, inner_cells, avoid_one_site=True)
    outside = pack_cells(outer, outer_cells, avoid_one_site=True)
    assert inside is not None and outside is not None and not inside.keys() & outside.keys()
    new_poses = {name: (ORIGIN_X + first*PITCH, y, rows[y][0]) for name, (y, first) in (inside | outside).items()}
    assert new_poses.keys() == final_cells.keys()
    left, bottom, right, top = bounds
    margin = 1025 * DISTANCE_UNITS
    for width, name in inner_cells:
        x, y, _ = new_poses[name]
        assert left - margin <= x and x + width * PITCH <= right + margin
        assert bottom - margin <= y and y + HEIGHT <= top + margin
    output.mkdir()
    layout = output / "localized_seed.def"
    write_coordinates(seed, layout, removed, added, new_poses, retained + len(macros) + len(final_cells))
    print("BOUNDED_SEED_COORDINATES_WRITTEN", len(inside), len(outside), flush=True)
    # The geometry checker expects a fully placed reference. Match the retained
    # geometry separately against the original placement below.
    assert boundary_sections(layout) == boundary_sections(seed)
    geometry = verify_geometry(layout, layout, sizes)
    assert geometry["component_counts"]["UNPLACED"] == 0
    count, inventory = verify_inventory(candidate, seed, layout, new_poses, removed, retained, len(macros))
    boundary = boundary_sections(layout)
    assert all(digest(Path(name)) == value for name, value in evidence.items())
    return {
        "state": "bounded_decoder_coordinate_seed_and_complete_inventory_verified",
        "candidate_sha256": evidence[str(candidate)], "coordinate_seed_sha256": digest(layout),
        "sorted_instance_master_inventory_sha256": inventory, "physical_component_count": count,
        "retained_standard_cell_coordinates": retained, "unchanged_fixed_macros": len(macros),
        "placement_margin_um": 1025, "assigned_new_loader_cells": len(inside),
        "assigned_other_new_cells": len(outside), "untouched_boundary_pins": boundary["PINS"][0],
        "unchanged_boundary_blockages": boundary["BLOCKAGES"][0],
        "lower_bound_at_1000_um": {"required_sites_in_cells_at_least_three_sites_wide": large_need,
                                    "available_sites_in_intervals_at_least_three_sites_long": large_supply},
        "geometry": geometry,
        "evidence_sha256": evidence | {str(path): digest(path) for path in (DECODER_RECORD, REGION_RECORD, Path(__file__))},
        "scope": "Exact grid-aligned, overlap-free coordinate seed for the linked netlist. The initial locations "
                 "are based on intervals and cell width. Innovus placement, wire delay and routing are pending.",
    }


def main():
    assert __debug__ and Path("/.dockerenv").is_file()
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("candidate", "source_seed", "library", "original_map", "bounded_map", "output"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    summary = run(args.candidate, args.source_seed, args.library, args.original_map, args.bounded_map, args.output)
    with (args.output / "verified.json").open("x") as stream:
        json.dump(summary, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(summary["state"], summary["physical_component_count"], flush=True)


if __name__ == "__main__":
    main()
