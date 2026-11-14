"""Measure placement capacity as macro clearances change inside a fixed pad ring."""

import argparse
from collections import Counter
from decimal import Decimal
import json
from pathlib import Path

from audit_tri_oracle_placed_chip_boundary import digest
from plan_tri_oracle_pad_ring_macros import load_floorplan, row_sites, shift_inward, validate_boxes


ROOT = Path(__file__).resolve().parents[1]


def evaluate(fixed, rows, outline, grid, row_height, site_area, movable_area, units, trim_nm):
    trim = Decimal(trim_nm) * units / 1000
    assert trim == int(trim) and trim < min(min(pose[4]) for pose in fixed.values())
    trimmed = {name: (*pose[:4], tuple(clearance - int(trim) for clearance in pose[4]))
               for name, pose in fixed.items()}
    positions = shift_inward(shift_inward(trimmed, 0, outline[0], grid), 1, outline[1], grid)
    validate_boxes(positions, outline)
    sites = row_sites(rows, row_height, outline, positions)
    used = -(-movable_area // site_area)
    shifted = {name: sum(positions[name][axis] - pose[axis] for axis in (0, 1))
               for name, pose in fixed.items() if positions[name][:2] != pose[:2]}
    return dict(trim_nanometers_per_side=trim_nm,
                minimum_remaining_halo_micrometers=min(min(pose[4]) for pose in positions.values()) / units,
                placement_sites=sites, free_sites_after_existing_standard_cells=sites - used,
                geometric_utilization_percent=100 * movable_area / (sites * site_area),
                moved_macros=len(shifted), maximum_macro_manhattan_move_micrometers=max(shifted.values(), default=0) / units,
                fits_before_pad_interface_logic=sites >= used)


def run(design, libdir):
    seed_file = ROOT / "records/tri_oracle_pad_ring_macro_seed.json"
    prior_file = ROOT / "records/tri_oracle_grouped_active_placement.json"
    clearance_file = ROOT / "records/tri_oracle_pad_ring_clearance.json"
    seed, prior, clearance = (json.loads(path.read_text()) for path in (seed_file, prior_file, clearance_file))
    assert seed["candidate_netlist_sha256"] == prior["candidate_netlist_sha256"] == clearance["candidate_netlist_sha256"]
    assert digest(design) == prior["placed_design_exchange_sha256"]
    libraries = sorted(libdir.glob("*.lef"))
    technology, = libdir.glob("*.tlef")
    assert len(libraries) == 7
    assert all(digest(path) == clearance["evidence_sha256"][str(path.relative_to(ROOT))] for path in libraries)
    assert digest(technology) == seed["evidence_sha256"][str(technology.relative_to(ROOT))]
    units, grid, rows, fixed, masters, movable_area = load_floorplan(design, libraries, technology)
    height = int(Decimal("1.2") * units)
    pitch, = {row[3] for row in rows}
    site_area = pitch * height
    assert movable_area % site_area == 0
    depth = int(Decimal(seed["reserved_pad_depth_micrometers"]) * units)
    outline = (depth, depth, 3600 * units - depth, 3600 * units - depth)
    trims = (0, 50, 100, 150, 200, 300, 500, 750, 1000, 1500, 2000)
    cases = {str(trim): evaluate(fixed, rows, outline, grid, height, site_area, movable_area, units, trim)
             for trim in trims}
    baseline = cases["0"]
    assert baseline["placement_sites"] == seed["site_capacity"]["new_geometric_sites"]
    assert baseline["free_sites_after_existing_standard_cells"] == -seed["site_capacity"]["minimum_site_deficit"]
    memories = Counter(master for master, _ in masters.values())
    assert sum(memories.values()) == seed["existing_macros"] == 631
    return dict(
        state="pad_ring_macro_clearance_sensitivity_measured",
        candidate_netlist_sha256=seed["candidate_netlist_sha256"],
        compiled_memory_masters=memories,
        pad_ring_depth_micrometers=depth / units,
        standard_cell_sites_required=movable_area // site_area,
        scenarios=cases,
        evidence_sha256={str(path.relative_to(ROOT)): digest(path) for path in
                         (seed_file, prior_file, clearance_file, design, technology, *libraries,
                          Path(__file__).resolve(), ROOT / "syn/plan_tri_oracle_pad_ring_macros.py")},
        scope="No overlaps among macro bodies or their modeled haloes. Standard-cell capacity is optimistic. "
              "The analysis excludes pad interface cells, clock tree cells, layout congestion, timing and pin access. "
              "The smaller haloes are trial inputs requiring native placement and verification.",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("design", "libdir"):
        parser.add_argument(name, type=lambda value: Path(value).absolute())
    print(json.dumps(run(**vars(parser.parse_args())), sort_keys=True, indent=2))
