"""Screen macro placement keepouts while retaining the chip outline and pad reserves."""

import argparse
from collections import Counter
from decimal import Decimal
from pathlib import Path
import json
import re

from audit_tri_oracle_dual_group_placement_seed import (
    HEIGHT, OUTLINE, PITCH, candidates, fragments, read_rows, require_free_space,
)
from audit_tri_oracle_pad_ring_clearance import dimensions
from audit_tri_oracle_placed_chip_boundary import digest
from plan_tri_oracle_pad_ring_macros import macro_box, validate_boxes
from verify_tri_oracle_pad_cold_reload import COMPONENTS, HALO, boundary_sections
from verify_tri_oracle_partial_pad_ring_geometry import mark_reserved


DISTANCE_UNITS = 2000
RECORD = Path("records/tri_oracle_dual_group_placement_seed.json")
LEF_PIN = re.compile(r"(?ms)^[ \t]+PIN (\S+)\n(.*?)^[ \t]+END \1\s*$")
LEF_RECT = re.compile(r"(?m)^[ \t]+RECT\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s*;")
SIDES = ("left", "bottom", "right", "top")


def read(path):
    return json.loads(path.read_text())


def seed_geometry(seed, sizes):
    reserved = boundary_sections(seed)["BLOCKAGES"][1]
    memory = {}
    masters = {}
    demand = Counter()
    placed = 0
    with seed.open() as stream:
        rows, count = read_rows(stream)
        for name, master, status, pose in candidates(stream):
            width, height = sizes[master]
            if status == "FIXED":
                x, y, orientation, halo = pose
                assert orientation == "N" and name not in memory
                memory[name] = x, y, width, height, halo
                masters[name] = master
                continue
            assert width > 0 and width % PITCH == 0 and height == HEIGHT
            sites = width // PITCH
            if status == "UNPLACED":
                demand[sites] += 1
                continue
            x, y, orientation, _ = pose
            side, grid = rows[y]
            assert (x - 40000) % PITCH == 0
            assert orientation in ({"N", "FN"} if side == "N" else {"FS", "S"}), name
            start = (x - 40000) // PITCH
            end = start + sites
            assert 0 <= start < end <= len(grid) and not any(grid[start:end]), name
            grid[start:end] = b"\x02" * sites
            placed += 1
    assert len(memory) == 631 and placed + demand.total() + len(memory) == count
    validate_boxes(memory, OUTLINE)
    return rows, memory, masters, reserved, demand, placed


def pin_sides(libraries, known):
    observed = {}
    for path in libraries:
        if not path.name.lower().startswith("ts"):
            continue
        text = path.read_text()
        master, = re.findall(r"(?m)^MACRO (\w+)\s*$", text)
        assert master in known and master not in observed
        width, height = map(Decimal, re.search(r"\bSIZE (\S+) BY (\S+)\s*;", text).groups())
        sides = {"signal": Counter(), "power_ground": Counter()}
        names = set()
        for pin in LEF_PIN.finditer(text):
            name, body = pin.groups()
            assert name not in names
            names.add(name)
            use, = re.findall(r"\bUSE (SIGNAL|POWER|GROUND)\s*;", body)
            kind = "signal" if use == "SIGNAL" else "power_ground"
            rectangles = LEF_RECT.findall(body)
            assert rectangles and not re.search(r"(?m)^[ \t]+(?:POLYGON|PATH|VIA)\b", body)
            edges = set()
            for rectangle in rectangles:
                x0, y0, x1, y1 = map(Decimal, rectangle)
                assert 0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height
                distances = (x0, y0, width - x1, height - y1)
                assert kind != "signal" or 0 in distances, (master, name, rectangle)
                edges.update(side for i, side in enumerate(SIDES) if distances[i] == 0)
            assert edges, (master, name)
            sides[kind].update(edges)
        assert len(names) == len(re.findall(r"(?m)^[ \t]+PIN (\S+)\s*$", text))
        assert all(sides.values())
        observed[master] = sides
    assert observed.keys() == known
    return observed


def smaller_halos(memory, cap_um, *, masters, protected):
    limit = cap_um * DISTANCE_UNITS
    return {
        name: (*pose[:4], tuple(size if side in protected.get(masters[name], ()) else min(size, limit)
                                for side, size in zip(SIDES, pose[4], strict=True)))
        for name, pose in memory.items()
    }


def measure(rows, macros, reservations, demand, occupied_sites):
    rectangles = [*map(macro_box, macros.values()), *reservations]
    free = Counter()
    for y, (_, occupied) in rows.items():
        grid = occupied.copy()
        for rectangle in rectangles:
            mark_reserved(grid, y, 40000, PITCH, HEIGHT, rectangle)
        assert grid.count(2) == occupied.count(2), y
        free.update(fragments(grid))
    available = sum(width * count for width, count in free.items())
    required = sum(width * count for width, count in demand.items())
    try:
        remainder = require_free_space(free.copy(), demand)
    except ValueError:
        fits = False
    else:
        assert remainder == available - required
        fits = True
    return {
        "available_sites_before_new_cells": available,
        "spare_sites_by_area": available - required,
        "largest_free_interval_sites": max(free, default=0),
        "exact_cell_widths_fit_without_releasing_existing_coordinates": fits,
        "projected_site_utilization_percent": round(100 * (occupied_sites + required) /
                                                     (occupied_sites + available), 6),
    }


def write_candidate(seed, output, halos):
    changed = 0
    with seed.open() as source, output.open("x") as destination:
        in_components = False
        for line in source:
            if COMPONENTS.fullmatch(line):
                in_components = True
            elif line == "END COMPONENTS\n":
                in_components = False
            name = line.split(maxsplit=2)[1] if in_components and line.startswith("- ") else ""
            destination.write(line)
            if name in halos:
                match = HALO.fullmatch(next(source))
                assert match, name
                selected = halos[name][4]
                changed += tuple(map(int, match.groups())) != selected
                destination.write("  + HALO " + " ".join(map(str, selected)) + "\n")
    return changed


def run(seed_directory, library, output):
    source = seed_directory / "seed.def"
    receipt = read(seed_directory / "receipt.json")
    geometry_path = seed_directory / "geometry_verified.json"
    geometry = read(geometry_path)
    record = read(RECORD)
    assert digest(geometry_path) == record["evidence_sha256"][str(geometry_path)]
    assert digest(source) == receipt["seed_def_sha256"] == geometry["seed_def_sha256"]
    assert receipt["candidate_sha256"] == record["candidate_sha256"]
    libraries = sorted(library.glob("*.lef"))
    evidence = {str(path): digest(path) for path in libraries}
    assert evidence == geometry["evidence_sha256"]
    sizes = dimensions(libraries, DISTANCE_UNITS)
    rows, macros, masters, reserves, demand, placed = seed_geometry(source, sizes)
    sides = pin_sides(libraries, set(masters.values()))
    occupied = sum(grid.count(2) for _, grid in rows.values())
    assert occupied == geometry["existing_occupied_sites"]
    base = measure(rows, macros, reserves, demand, occupied)
    assert base["available_sites_before_new_cells"] == geometry["available_sites"]
    assert base["spare_sites_by_area"] == geometry["unassigned_sites_after_packing"]
    assert not base["exact_cell_widths_fit_without_releasing_existing_coordinates"]

    boundary_comparison = measure(rows, macros, (), demand, occupied)
    policies = {
        "signal_edges": {master: set(pins["signal"]) for master, pins in sides.items()},
        "signal_and_power_edges": {master: set(pins["signal"]) | set(pins["power_ground"])
                                   for master, pins in sides.items()},
    }
    scenarios = {}
    selected = {}
    for policy, protected in policies.items():
        cases = {}
        for cap_um in (5, 4, 3, 2, 1):
            halos = smaller_halos(macros, cap_um, masters=masters, protected=protected)
            for name, (_, _, _, _, original) in macros.items():
                applied = halos[name][4]
                assert all(applied[SIDES.index(side)] == original[SIDES.index(side)]
                           for side in protected[masters[name]])
            case = measure(rows, halos, reserves, demand, occupied)
            case["sites_recovered_from_original_halos"] = (
                case["available_sites_before_new_cells"] - base["available_sites_before_new_cells"]
            )
            case["macros_with_smaller_halos"] = sum(halos[name] != pose for name, pose in macros.items())
            cases[cap_um] = case
            if policy not in selected and case["exact_cell_widths_fit_without_releasing_existing_coordinates"]:
                selected[policy] = cap_um
            print("WIDENED_HALO_SCREEN", policy, cap_um, case, flush=True)
        capacities = [case["available_sites_before_new_cells"] for case in cases.values()]
        assert capacities == sorted(capacities)
        scenarios[policy] = cases
    assert selected.keys() == policies.keys()
    output.mkdir()
    alternatives = {}
    for policy, cap in selected.items():
        alternative = output / f"halo_seed_{policy}.def"
        halos = smaller_halos(macros, cap, masters=masters, protected=policies[policy])
        assert write_candidate(source, alternative, halos) == scenarios[policy][cap]["macros_with_smaller_halos"]
        assert boundary_sections(alternative) == boundary_sections(source)
        assert seed_geometry(alternative, sizes) == (rows, halos, masters, reserves, demand, placed)
        alternatives[policy] = {"cap_um": cap, "sha256": digest(alternative)}
    return {
        "state": "fixed_memory_halo_capacity_screened",
        "candidate_sha256": record["candidate_sha256"],
        "candidate_seeds": alternatives,
        "pins_by_touching_side_and_master": sides,
        "same_macro_locations": len(macros),
        "retained_standard_cell_coordinates": placed,
        "unplaced_standard_cells": demand.total(),
        "original_geometry": base,
        "boundary_reservations_only_comparison": boundary_comparison,
        "halo_scenarios_by_protected_edges_and_cap_um": scenarios,
        "scope": "Verified geometric capacity and seeds retaining all prior standard-cell coordinates. "
                 "The original halo is retained on edges touched by signal pin shapes. "
                 "One seed also retains the halo on edges touched by power and ground pin shapes. "
                 "The boundary-reservation comparison is diagnostic. Both seeds keep every boundary reserve. "
                 "Signal and power pin access, timing and routing still require native checks.",
        "evidence_sha256": evidence | {str(path): digest(path) for path in (
            geometry_path, source, RECORD, Path(__file__),
        )},
    }


def main():
    assert __debug__ and Path("/.dockerenv").is_file()
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("seed", "library", "output"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    result = run(args.seed, args.library, args.output)
    with (args.output / "receipt.json").open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(result["state"], result["candidate_seeds"], flush=True)


if __name__ == "__main__":
    main()
