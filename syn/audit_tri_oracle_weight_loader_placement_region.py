"""Screen room for the widened weight loader near its retained placement."""

import argparse
from collections import Counter
import json
from pathlib import Path
import re

from audit_tri_oracle_dual_group_placement_seed import HEIGHT, PITCH, candidates, read_rows, require_free_space
from audit_tri_oracle_pad_ring_clearance import dimensions
from audit_tri_oracle_placed_chip_boundary import digest
from plan_tri_oracle_pad_ring_macros import macro_box
from prepare_tri_oracle_dual_group_placement_seed import RAW_PARENT
from scan_tri_oracle_dual_group_halos import DISTANCE_UNITS, read, seed_geometry, smaller_halos
from verify_tri_oracle_partial_pad_ring_geometry import mark_reserved


RECORD = Path("records/tri_oracle_dual_group_halo_screen.json")
ORIGIN_X = 40000
MARGINS_UM = (0, 50, 100, 200, 300, 400, 600, 800, 1000, 1200)
WORD_DECODER = re.compile(r"^indexed_lane\[([01])\]\.loader/loader/decoder/word_decoder\[([01])\]\.decoder/")


def loader_inventory(seed, sizes):
    demand = Counter()
    decoder_cells = Counter()
    left, bottom, right, top = 2**31, 2**31, 0, 0
    retained = 0
    with seed.open() as source:
        read_rows(source)
        for name, master, status, pose in candidates(source):
            if not name.startswith(RAW_PARENT):
                continue
            width, height = sizes[master]
            assert width % PITCH == 0 and height == HEIGHT
            if status == "UNPLACED":
                demand[width // PITCH] += 1
                suffix = name[len(RAW_PARENT):].replace("\\", "")
                if decoder := WORD_DECODER.match(suffix):
                    decoder_cells[f"lane_{decoder[1]}_word_{decoder[2]}"] += 1
            else:
                assert status == "PLACED"
                x, y, _, _ = pose
                left, bottom = min(left, x), min(bottom, y)
                right, top = max(right, x + width), max(top, y + height)
                retained += 1
    assert retained > 0 and demand and left < right and bottom < top
    assert len(decoder_cells) == 4 and sum(decoder_cells.values()) <= demand.total()
    return demand, retained, (left, bottom, right, top), decoder_cells


def free_intervals(rows, macros, reserves):
    obstacles = [*map(macro_box, macros.values()), *reserves]
    for y, (_, occupied) in rows.items():
        grid = occupied.copy()
        for obstacle in obstacles:
            mark_reserved(grid, y, ORIGIN_X, PITCH, HEIGHT, obstacle)
        assert grid.count(2) == occupied.count(2), y
        intervals = [(match.start(), match.end()) for match in re.finditer(rb"\x00+", grid)]
        yield y, intervals


def split_supply(intervals, bounds, margin_um):
    """Split each row's free intervals at the grid-aligned region boundary."""
    margin = margin_um * DISTANCE_UNITS
    left, bottom, right, top = bounds
    first = (left - margin - ORIGIN_X + PITCH - 1) // PITCH
    last = (right + margin - ORIGIN_X) // PITCH
    inside, outside = Counter(), Counter()
    for y, gaps in intervals:
        if y < bottom - margin or y + HEIGHT > top + margin:
            outside.update(end - start for start, end in gaps)
            continue
        for start, end in gaps:
            overlap_start, overlap_end = max(start, first), min(end, last)
            if overlap_start >= overlap_end:
                outside[end - start] += 1
                continue
            inside[overlap_end - overlap_start] += 1
            if start < overlap_start:
                outside[overlap_start - start] += 1
            if overlap_end < end:
                outside[end - overlap_end] += 1
    return inside, outside


def sites(widths):
    return sum(width * count for width, count in widths.items())


def fits(supply, demand):
    if sites(supply) < sites(demand):
        return False
    try:
        require_free_space(supply.copy(), demand)
    except ValueError:
        return False
    return True


def audit(seed, library):
    record = read(RECORD)
    source = record["candidate_seeds"]["signal_and_power_edges"]
    assert source["cap_um"] == 3 and digest(seed) == source["sha256"]
    libraries = sorted(library.glob("*.lef"))
    assert len(libraries) == 7
    input_hashes = {str(path): digest(path) for path in libraries}
    assert all(record["evidence_sha256"][name] == value for name, value in input_hashes.items())
    sizes = dimensions(libraries, DISTANCE_UNITS)
    rows, macros, masters, reserves, total_demand, retained = seed_geometry(seed, sizes)
    loader_demand, retained_loader, bounds, decoder_cells = loader_inventory(seed, sizes)
    assert loader_demand <= total_demand
    other_demand = total_demand - loader_demand
    assert retained == record["retained_standard_cell_coordinates"]
    assert total_demand.total() == record["unplaced_standard_cells"]
    loader_sites = sites(loader_demand)

    pin_sides = record["pins_by_touching_side_and_master"]
    protected = {master: set(sides["signal"]) | set(sides["power_ground"]) for master, sides in pin_sides.items()}
    scenarios = {}
    for cap in (3, 2, 1):
        adjusted = smaller_halos(macros, cap, masters=masters, protected=protected)
        intervals = list(free_intervals(rows, adjusted, reserves))
        global_supply = sum(end - start for _, gaps in intervals for start, end in gaps)
        expected = record["halo_scenarios_by_protected_edges_and_cap_um"]["signal_and_power_edges"][str(cap)]
        assert global_supply == expected["available_sites_before_new_cells"]
        region_metrics = {}
        prior_inside = 0
        for margin in MARGINS_UM:
            inside, outside = split_supply(intervals, bounds, margin)
            inside_sites, outside_sites = sites(inside), sites(outside)
            assert prior_inside <= inside_sites and inside_sites + outside_sites == global_supply
            prior_inside = inside_sites
            region_metrics[margin] = {"inside_sites": inside_sites, "outside_sites": outside_sites,
                                      "loader_site_shortfall_by_area": max(0, loader_sites - inside_sites),
                                      "loader_fits_inside": fits(inside, loader_demand),
                                      "other_cells_fit_outside": fits(outside, other_demand)}
        scenarios[cap] = region_metrics
        print("LOADER_REGION_CAP", cap, region_metrics, flush=True)

    return {
        "state": "widened_weight_loader_regional_site_supply_screened",
        "candidate_sha256": record["candidate_sha256"],
        "retained_loader_cells": retained_loader,
        "new_loader_cells": loader_demand.total(),
        "new_loader_sites_required": loader_sites,
        "new_cells_by_indexed_word_decoder": decoder_cells,
        "other_new_cells": other_demand.total(),
        "other_new_sites_required": sites(other_demand),
        "retained_loader_bounds_um": [axis / DISTANCE_UNITS for axis in bounds],
        "regions_by_halo_cap_and_margin_um": scenarios,
        "evidence_sha256": input_hashes | {str(path): digest(path) for path in (seed, RECORD, Path(__file__))},
        "scope": "The region bounds the existing loader cells by their full footprints, plus the stated margin. "
                 "The screen preserves every retained placement and protects the memory edges touched by signal, "
                 "power and ground pins. Successful greedy width packing supplies a constructive fit. A site "
                 "shortfall proves a region too small by area. If area suffices and greedy packing fails, exact "
                 "feasibility remains open. The remaining cells are screened outside the same region. Native "
                 "placement, pin access and timing are pending.",
    }


def main():
    assert __debug__ and Path("/.dockerenv").is_file()
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("seed", "library", "output"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    result = audit(args.seed, args.library)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")


if __name__ == "__main__":
    main()
