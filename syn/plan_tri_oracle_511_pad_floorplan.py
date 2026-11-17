"""Search the current Booth floorplan for 511 independent-filler pad sites."""

from collections import Counter
from decimal import Decimal
import json
from pathlib import Path
import re

import torch

from audit_tri_oracle_bonded_pad_capacity import vendor_rules
from audit_tri_oracle_pad_ring_clearance import contains, dimensions, overlap
from audit_tri_oracle_physical_io_budget import macro_boxes
from plan_tri_oracle_bonded_pad_recovery import align_to_sites, gpu_sites, inventory, reserves, search
from plan_tri_oracle_pad_ring_macros import row_sites
from verify_tri_oracle_booth_chip_geometry import geometry, layout
from verify_tri_oracle_corrected_booth_roundtrip import ROOT, digest
from verify_tri_oracle_pad_cold_reload import components
from verify_tri_oracle_wide_request_timing import MODELS, PAD_CAPACITY, PLACEMENT, TRIAL
from verify_tri_oracle_wide_request_trial import MODULE


TIMING = Path("records/tri_oracle_wide_request_timing.json")
BASE_CAPACITY = Path("records/tri_oracle_corrected_booth_buffered_row_capacity.json")


def site_counts(rows, height, die, boxes, regions):
    blockers = {index: (x1, y1, x2 - x1, y2 - y1, (0, 0, 0, 0))
                for index, (x1, y1, x2, y2) in enumerate(boxes)}
    return row_sites(rows, height, die, blockers), {
        name: row_sites(rows, height, region, blockers) for name, region in regions.items()}


def evaluate(die, rows, height, regions, demand, parent_demand, halos, fixed_blockages, strips, rule, units, grid, target):
    depth = strips["bottom"][3]
    side = die[2]
    attempted, candidates = search(halos, strips, depth, grid, side, units, rule, target)
    row_alignment = (1, rows[0][1], height, side - depth)
    column_alignment = (0, rows[0][0], rows[0][3], side - depth)
    best = None
    screened = 0
    seen = set()
    max_global = max_parent = None
    failures = Counter()
    for _, candidate, moves, _ in candidates:
        move_key = tuple(moves.items())
        if move_key in seen:
            continue
        seen.add(move_key)
        row_aligned = align_to_sites(candidate, *row_alignment)
        col_aligned = align_to_sites(candidate, *column_alignment)
        for alignment, boxes in (
            ("manufacturing grid", candidate), ("row grid", row_aligned),
            ("rows then columns", align_to_sites(row_aligned, *column_alignment) if row_aligned else None),
            ("columns then rows", align_to_sites(col_aligned, *row_alignment) if col_aligned else None),
        ):
            if boxes is None:
                continue
            intervals, counts = inventory(boxes, strips, units, rule)
            if sum(counts.values()) < target:
                continue
            pads, distribution = reserves(intervals, counts, strips, units, rule, target)
            if any(value % grid for _, reserve, body in pads for value in (*reserve, *body)):
                failures["off_manufacturing_grid"] += 1
                continue
            obstacles = [*boxes.values(), *fixed_blockages, *(keepout for _, keepout, _ in pads)]
            available, fenced = gpu_sites(rows, height, obstacles, regions)
            margins = {name: fenced[name] - demand[name] for name in regions}
            parent_margin = available - sum(fenced.values()) - parent_demand
            global_margin = parent_margin + sum(margins.values())
            distances = [abs(box[0] - halos[name][0]) + abs(box[1] - halos[name][1])
                         for name, box in boxes.items() if box != halos[name]]
            # Global cells can use spare sites inside compute regions. The
            # current verified placement already uses those sites.
            deficits = sum(max(0, -margin) for margin in margins.values())
            rank = deficits, max(0, -global_margin), -global_margin, max(distances), sum(distances)
            evidence = (boxes, pads, distribution, obstacles, alignment, distances,
                        available, fenced, margins, parent_margin, global_margin)
            if best is None or rank < best[0]:
                best = rank, evidence
            max_global = global_margin if max_global is None else max(max_global, global_margin)
            max_parent = parent_margin if max_parent is None else max(max_parent, parent_margin)
            failures["fenced_site_deficit"] += min(margins.values()) < 0
            failures["global_site_deficit"] += global_margin < 0
            screened += 1
    assert best is not None and screened > 0
    return best[1], attempted, screened, failures, max_global, max_parent


def run():
    evidence = {}

    def pin(path, expected=None):
        checksum = digest(path)
        assert expected is None or checksum == expected, path
        evidence[str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path)] = checksum
        return path

    def read(path):
        return json.loads(pin(path).read_text())

    placement, models, old, trial, timing, pads = (
        read(path) for path in (PLACEMENT, MODELS, BASE_CAPACITY, TRIAL, TIMING, PAD_CAPACITY))
    assert old["database_fingerprint_sha256"] == placement["database_fingerprint_sha256"] == models["database_fingerprint_sha256"]
    assert trial["cold_receiver_netlist_sha256"] == timing["cold_receiver_netlist_sha256"] == models["cold_netlist_sha256"]
    database = Path(placement["database"])
    cold = database.parents[1] / "cold/layout.def"
    pin(cold, placement["evidence_sha256"][str(cold)])
    lefs = tuple(pin(path, models["evidence_sha256"][str(path)]) for path in sorted((database / "libs/lef").glob("*.lef")))
    tech, = (pin(path, models["evidence_sha256"][str(path)]) for path in (database / "libs/lef").glob("*.tlef"))
    assert len(lefs) == 7
    archives = pads["evidence_sha256"]
    abstract, release = (next(pin(Path(name), checksum) for name, checksum in archives.items() if name.endswith(suffix))
                         for suffix in ("sefu10lm.tar.gz", "_rln.tar.gz"))
    depth_um, corner_um, pad_view, rules, supplies = vendor_rules(abstract, release)
    assert pad_view == pads["pad_view_sha256"]
    rule = rules["pad50_independent_fillers"]
    die, units, row_map, regions, groups, keepouts = geometry(cold, verify_top=True)
    side, depth, corner = 3600 * units, int(depth_um * units), int(corner_um * units)
    assert die == (0, 0, side, side)
    grid = int(Decimal(re.search(r"MANUFACTURINGGRID ([\d.]+)", tech.read_text())[1]) * units)
    strips = {"bottom": (corner, 0, side - corner, depth), "top": (corner, side - depth, side - corner, side),
              "left": (0, corner, depth, side - corner), "right": (side - depth, corner, side, side - corner)}
    stride = int(sum(rule[:2]) * units)
    old_pads = [box for box in keepouts if any(
        contains(strip, box) and (box[2] - box[0], box[3] - box[1])
        == ((stride, depth) if edge in ("bottom", "top") else (depth, stride))
        for edge, strip in strips.items())]
    original_count = timing["repaired_fixed_macro_floorplan_pad_capacity"]["pad50_independent_fillers"]["whole_ring_sites"]
    assert len(old_pads) == original_count == 497 and len(set(old_pads)) == 497
    main_blockages = sorted(set(keepouts) - set(old_pads))
    assert len(main_blockages) == 4
    for index, region in enumerate(regions.values()):
        assert not any(overlap(region, previous) for previous in list(regions.values())[:index])

    rows = [(x, y, length, pitch) for y, (x, _, length, pitch) in sorted(row_map.items())]
    height, pitch = rows[1][1] - rows[0][1], rows[0][3]
    site_area = Decimal(height * pitch) / units**2
    assert site_area == Decimal(old["site_area_square_micrometers"])
    sizes = dimensions(lefs, units)
    fixed, old_link_sites, old_link_cells, shared_link_cells = {}, 0, 0, 0
    for name, pose in components(cold):
        master, status, x, y, *_ = pose
        if status == "FIXED":
            fixed[name] = pose
        elif name.startswith(b"request_link/"):
            width, cell_height = sizes[master]
            assert width % pitch == 0 and cell_height == height
            shared_link_cells += any(overlap((x, y, x + width, y + height), region)
                                     for region in regions.values())
            old_link_sites += width // pitch
            old_link_cells += 1
    assert len(fixed) == 631 and old_link_cells == 61 and shared_link_cells > 0
    _, halos = macro_boxes(fixed, sizes)
    census, _, demand, free, old_sites, old_free = layout(
        cold, sizes, row_map, regions, groups, keepouts + list(halos.values()), fixed.copy(), height)
    assert census == {"PLACED": old["standard_cells"], "FIXED": old["fixed_memory_macros"]}
    assert free == old["row_sites_free_by_region"] and sum(free.values()) == old_free
    assert (old_sites, old_sites - old_free) == (old["row_sites_available_after_keepouts"], old["row_sites_occupied"])
    _, original_by_edge = inventory(halos, strips, units, rule)
    assert original_by_edge == timing["repaired_fixed_macro_floorplan_pad_capacity"]["pad50_independent_fillers"]["sites_by_edge"]
    area_report, = (pin(Path(name), checksum) for name, checksum in trial["evidence_sha256"].items()
                    if name.endswith("/genus/area.rpt"))
    area, = re.findall(rf"(?m)^{MODULE}\s+NA\s+52\s+([\d.]+)\s+", area_report.read_text())
    new_link_sites = Decimal(area) / site_area
    assert new_link_sites == int(new_link_sites)
    parent_demand = old["row_sites_occupied"] - sum(demand.values()) - old_link_sites + int(new_link_sites)
    target = trial["digital_signal_pins"] + sum(supplies.values())
    assert target == trial["signal_and_illustrative_supply_pins"] == 511
    _, base_by_region = gpu_sites(rows, height, keepouts + list(halos.values()), regions)
    assert all(base_by_region[name] >= demand[name] + free[name] for name in regions)
    values, windows, tested, failures, max_global, max_parent = evaluate(
        die, rows, height, regions, demand, parent_demand, halos, main_blockages, strips, rule, units, grid, target)
    (boxes, slots, distribution, obstacles, alignment, distances, capacity, fenced,
     margins, parent_margin, global_margin) = values
    assert site_counts(rows, height, die, obstacles, regions) == (capacity, fenced)
    assert len(slots) == target and sum(distribution.values()) == target
    assert all(contains(die, box) for box in boxes.values())
    assert not any(overlap(box, other) for index, box in enumerate(boxes.values()) for other in list(boxes.values())[:index])
    for index, (edge, slot, body) in enumerate(slots):
        assert contains(strips[edge], slot) and contains(slot, body)
        assert not any(overlap(slot, macro) for macro in boxes.values())
        assert not any(overlap(slot, other) for _, other, _ in slots[:index])
    out = cold.parents[1] / "wide_request_trial/pad_floorplan"
    out.mkdir()
    selected = out / "screened_floorplan.json"
    moves = {name.decode(): [master, x + boxes[name][0] - halos[name][0],
                            y + boxes[name][1] - halos[name][1], rotation]
             for name, (master, _, x, y, rotation, _) in fixed.items() if boxes[name] != halos[name]}
    assert all(x % grid == y % grid == 0 for _, x, y, _ in moves.values())
    selected.write_text(json.dumps({"moved_macros": moves, "pad_slots": slots}, sort_keys=True) + "\n")
    pin(selected)
    pin(Path(__file__).resolve())
    return {
        "state": "wide_request_independent_filler_floorplan_screened",
        "cold_netlist_sha256": timing["cold_receiver_netlist_sha256"],
        "pad_reservations": target, "reservations_by_edge": distribution,
        "tested_bottom_blockage_windows": windows, "gpu_screened_grid_variants": tested,
        "variants_by_failed_capacity_test": dict(failures),
        "selected_alignment": alignment, "moved_memory_macros": len(moves),
        "maximum_macro_manhattan_movement_um": max(distances) / units,
        "unfenced_site_margin": parent_margin, "global_site_margin": global_margin,
        "fenced_site_margins": margins, "best_global_margin_across_tested_layouts": max_global,
        "best_unfenced_margin_across_tested_layouts": max_parent,
        "original_request_cell_sites": old_link_sites, "wide_request_cell_sites": int(new_link_sites),
        "original_request_cells_in_compute_regions": shared_link_cells,
        "regional_and_global_site_demands_met": min(global_margin, *margins.values()) >= 0,
        "graphics_device": torch.cuda.get_device_name(), "peak_device_bytes": torch.cuda.max_memory_allocated(),
        "scope": "Search over contiguous bottom macro windows and four grid alignments. Memory halos, "
                 "die dimensions and compute fences are preserved. Pad and row counts use ideal "
                 "geometry and exclude additional pad-cell logic, legalization and routed timing.",
        "evidence_sha256": evidence,
    }


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    with Path("/proc/meminfo").open() as stream:
        assert next(int(line.split()[1]) for line in stream if line.startswith("MemAvailable:")) >= 8 * 1024**2
    assert torch.cuda.is_available() and torch.cuda.mem_get_info()[0] >= 2 * 1024**3
    torch.cuda.set_per_process_memory_fraction(0.12)
    print(json.dumps(run(), indent=2, sort_keys=True))
