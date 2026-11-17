"""Check the dual-port weight expansion against the exact widened placement."""

from collections import Counter, defaultdict
from decimal import Decimal
from itertools import accumulate, combinations
import json
from pathlib import Path
import re

from audit_tri_oracle_pad_ring_clearance import contains, dimensions, overlap
from audit_tri_oracle_physical_io_budget import macro_boxes
from verify_tri_oracle_booth_chip_geometry import geometry
from verify_tri_oracle_corrected_booth_roundtrip import ROOT, digest, read
from verify_tri_oracle_pad_cold_reload import components


SEED = Path("records/tri_oracle_wide_request_placement_seed.json")
IMPORT = Path("records/tri_oracle_wide_request_native_import_inputs.json")
RESOURCES = Path("records/tri_oracle_wide_seed_paper_resources.json")
OVERLAP = Path("records/tri_oracle_compiled_cluster_weight_overlap.json")
PAPER = Path("records/paper_result_targets.json")
SINGLE = "TS5N28HPCPSVTA32X128M2FW"
DUAL = "TS6N28HPCPSVTA32X128M2FW"


def area(box):
    return (box[2] - box[0]) * (box[3] - box[1])


def area_sum(boxes):
    return sum(map(area, boxes))


def free_grid_sites(rows, exclusions, height):
    """Count complete sites, with each obstructed site counted only once."""
    y_origins = sorted(rows)
    x_origin, _, columns, pitch = rows[y_origins[0]]
    bottom = y_origins[0]
    assert y_origins == list(range(bottom, bottom + height * len(rows), height))
    assert all((x, count, step) == (x_origin, columns, pitch)
               for x, _, count, step in rows.values())
    strips = [[] for _ in rows]
    for x1, y1, x2, y2 in exclusions:
        first = max(0, (y1 - bottom) // height)
        last = min(len(strips), -(-(y2 - bottom) // height))
        left = max(0, (x1 - x_origin) // pitch)
        right = min(columns, -(-(x2 - x_origin) // pitch))
        if left < right:
            for row in range(first, last):
                strips[row].append((left, right))
    blocked = 0
    for intervals in strips:
        used_until = 0
        for left, right in sorted(intervals):
            blocked += max(0, right - max(used_until, left))
            used_until = max(used_until, right)
    return columns * len(rows) - blocked


def fixed_replacements(fixed, sizes):
    replacements = {}
    checked_cores = defaultdict(set)
    for name, pose in fixed.items():
        match = re.fullmatch(rb"(.+/compute)/weights\[(\d+)\]", name.replace(b"\\", b""))
        if match:
            assert pose[0] == SINGLE
            checked_cores[match[1]].add(int(match[2]))
            replacements[name] = (DUAL, *pose[1:])
    assert len(checked_cores) == 20 and len(replacements) == 320
    assert all(indices == set(range(16)) for indices in checked_cores.values())
    return macro_boxes(fixed | replacements, sizes), set(replacements)


def uniform_halo_limit(bodies, allowance, grid):
    """Find the largest grid-aligned uniform halo within the area budget."""
    perimeter = sum(2 * ((x2 - x1) + (y2 - y1)) for x1, y1, x2, y2 in bodies)

    def extra(steps):
        halo = steps * grid
        return halo * perimeter + len(bodies) * 4 * halo * halo

    assert allowance >= 0
    lo, hi = 0, allowance // (grid * perimeter) + 1
    while hi - lo > 1:
        middle = (hi + lo) // 2
        if extra(middle) <= allowance:
            lo = middle
        else:
            hi = middle
    assert extra(lo) <= allowance < extra(lo + 1)
    return lo * grid


def verify():
    evidence = {}

    def pin(path, expected=None):
        path = path.relative_to(ROOT) if path.is_absolute() else path
        value = evidence.setdefault(str(path), digest(path))
        assert expected is None or value == expected, path
        return path

    seed, inputs, resources, cluster, paper = (read(pin(path)) for path in
                                                (SEED, IMPORT, RESOURCES, OVERLAP, PAPER))
    assert seed["candidate_sha256"] == inputs["candidate_sha256"] == resources["candidate_sha256"]
    netlist = Path(inputs["netlist"]).relative_to(ROOT)
    assert digest(netlist) == seed["candidate_sha256"]
    evidence[str(netlist)] = seed["candidate_sha256"]
    layout = Path(inputs["seed"]).relative_to(ROOT)
    pin(layout, seed["evidence_sha256"][str(layout)])
    libraries = [pin(Path(path), sha) for path, sha in inputs["evidence_sha256"].items()
                 if path.endswith(".lef")]
    replacement, = (Path(path) for path in cluster["evidence_sha256"]
                    if "/dual_port_weight_probe_01/" in path and path.endswith(".lef"))
    technology_lef, = (Path(path) for path in inputs["evidence_sha256"] if path.endswith(".tlef"))
    technology_lef = pin(technology_lef, inputs["evidence_sha256"][str(technology_lef)])
    libraries.append(pin(replacement, cluster["evidence_sha256"][str(replacement)]))
    def_plan, = (Path(path) for path in seed["evidence_sha256"] if path.endswith("/screened_floorplan.json"))
    pad_slots = read(pin(def_plan, seed["evidence_sha256"][str(def_plan)]))["pad_slots"]

    die, units, rows, _, _, obstructions = geometry(layout, verify_top=True)
    assert die == (0, 0, 3600 * units, 3600 * units)
    paper_size = tuple(Decimal(str(value)) for value in paper["silicon"]["die_dimensions_mm"])
    assert tuple(Decimal(end) / (1000 * units) for end in die[2:]) == paper_size
    grid, = re.findall(r"(?m)^MANUFACTURINGGRID ([\d.]+) ;$", technology_lef.read_text())
    grid = int(Decimal(grid) * units)
    assert grid > 0
    sizes = dimensions(libraries, units)
    fixed, standard = {}, Counter()
    for name, pose in components(layout):
        master, status, *_ = pose
        if status == "FIXED":
            assert name not in fixed
            fixed[name] = pose
        else:
            assert status == "PLACED"
            standard[master] += 1
    assert len(fixed) == 631 and sum(standard.values()) + len(fixed) == inputs["components"]
    assert Counter(pose[0] for pose in fixed.values()) == resources["memory"]["macro_counts_by_master"]
    levels = sorted(rows)
    height = levels[1] - levels[0]
    pitch = rows[levels[0]][3]
    assert all(sizes[master][1] == height and sizes[master][0] % pitch == 0 for master in standard)
    cell_area = sum(pitch * height * count * (sizes[master][0] // pitch) for master, count in standard.items())
    baseline_body, baseline_halos = macro_boxes(fixed, sizes)
    (new_body, new_halos), replaced = fixed_replacements(fixed, sizes)
    pads = [tuple(keepout) for _, keepout, _ in pad_slots]
    assert len(pads) == len(set(pads)) == seed["reserved_pad_sites"] == 511
    assert set(pads) <= set(obstructions) and len(obstructions) == 515
    assert all(contains(die, box) for box in (*pads, *baseline_halos.values()))
    assert not any(overlap(left, right) for left, right in combinations([*pads, *baseline_halos.values()], 2))
    baseline_sites = free_grid_sites(rows, [*obstructions, *baseline_halos.values()], height)
    assert baseline_sites - cell_area // (pitch * height) == seed["remaining_sites"]

    # Give all cells and memories the entire die, with no core margin, row
    # snapping, fences or routing. Retain the separately reserved pad footprints
    # and disjoint macro halos required by the widened placement flow.
    available = area(die) - area_sum(pads) - cell_area
    body_budget = available - area_sum(new_body.values())
    baseline_margin = available - area_sum(baseline_halos.values())
    growth = sorted(area(new_halos[name]) - area(baseline_halos[name]) for name in replaced)
    assert growth[0] > 0 and body_budget > 0
    shortfall = area_sum(new_halos.values()) - available
    assert shortfall == sum(growth) - baseline_margin > 0
    max_substitutions = sum(used <= baseline_margin for used in accumulate(growth))
    assert 0 < max_substitutions < len(replaced)
    largest_uniform_halo = uniform_halo_limit(tuple(new_body.values()), body_budget, grid)
    body_growth = sum(area(new_body[name]) - area(baseline_body[name]) for name in replaced)

    def mm2(value):
        return str(Decimal(value) / (units * units * 1_000_000))

    assert Decimal(mm2(body_growth)) == Decimal(cluster["physical_weight_macro_area_cost"][
        "extra_square_millimeters_for_dual_ports"])
    individually_clear = sum(
        contains(die, box) and not any(overlap(box, rect) for rect in obstructions)
        and not any(overlap(box, baseline_halos[other]) for other in fixed if other != name)
        for name, box in new_halos.items() if name in replaced
    )
    pin(Path(__file__).resolve())
    return {
        "state": "full_dual_port_weight_expansion_exceeds_widened_floorplan_with_current_keepouts",
        "candidate_sha256": seed["candidate_sha256"],
        "fixed_memories": len(fixed), "tested_replacements": len(replaced),
        "standard_cells": sum(standard.values()), "reserved_pad_count": len(pads),
        "unchanged_seed_free_sites": seed["remaining_sites"],
        "standard_cell_area_mm2": mm2(cell_area), "reserved_pad_area_mm2": mm2(area_sum(pads)),
        "extra_bare_macro_area_mm2": mm2(body_growth),
        "memory_and_halo_area_mm2": {"baseline": mm2(area_sum(baseline_halos.values())),
                                      "dual_port": mm2(area_sum(new_halos.values()))},
        "area_left_for_halos_with_new_macro_bodies_mm2": mm2(body_budget),
        "unplaced_area_lower_bound_mm2": mm2(area(die) + shortfall),
        "minimum_area_shortfall_mm2": mm2(shortfall),
        "upper_bound_substitutions_with_current_halos": max_substitutions,
        "individual_anchored_geometry_passes_with_logic_removed": individually_clear,
        "anchored_halo_collisions": sum(overlap(a, b) for a, b in combinations(new_halos.values(), 2)),
        "anchored_pad_collisions": sum(overlap(a, b) for a in new_halos.values() for b in pads),
        "optimistic_uniform_halo_area_upper_bound_um": str(Decimal(largest_uniform_halo) / units),
        "scope": "Area certificate uses exact widened placement cell inventory, compiler dimensions, "
                 "pad reservations and nonoverlapping memory halos. The movable bound grants the whole die "
                 "and leaves out all other blockages and placement restrictions. The uniform halo value is "
                 "an area ceiling for a hypothetical change, without a placement or routing result.",
        "evidence_sha256": evidence,
    }


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    print(json.dumps(verify(), indent=2, sort_keys=True))
