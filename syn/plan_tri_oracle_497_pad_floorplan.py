"""Search pad-compatible memory moves at the current 497-reservation budget."""
from collections import Counter
from decimal import Decimal
import json
from pathlib import Path
import re

import torch

from plan_tri_oracle_bonded_pad_recovery import (
    ROOT, align_to_sites, contains, digest, gpu_sites, inventory, layout, overlap, read, reserves, row_sites,
    search, vendor_rules,
)


BASE = Path("records/tri_oracle_bonded_pad_recovery.json")
TRANSFER = Path("records/tri_oracle_serialized_placement_transfer.json")
RECEIVER = Path("records/tri_oracle_gated_receive_storage.json")
WORK = Path(".cache/physical/whole_chip_xcelium_speed/497_pad_floorplan")


def search_floorplans(rows, height, halos, existing, strips, units, rule, grid, side, depth, target, demand, regions):
    attempts, options = search(halos, strips, depth, grid, side, units, rule, target)
    column_step = 0, rows[0][0], rows[0][3], side - depth
    row_step = 1, rows[0][1], height, side - depth
    checked = 0
    scored = 0
    best = None
    seen = set()
    for _, boxes, motion, _ in options:
        key = tuple(motion.items())
        if key in seen:
            continue
        seen.add(key)
        checked += 1
        row_aligned = align_to_sites(boxes, *row_step)
        column_aligned = align_to_sites(boxes, *column_step)
        for alignment, candidate in (
            ("original grid", boxes), ("row grid", row_aligned),
            ("rows then columns", align_to_sites(row_aligned, *column_step) if row_aligned else None),
            ("columns then rows", align_to_sites(column_aligned, *row_step) if column_aligned else None),
        ):
            if candidate is None:
                continue
            intervals, counts = inventory(candidate, strips, units, rule)
            if sum(counts.values()) < target:
                continue
            pads, distribution = reserves(intervals, counts, strips, units, rule, target)
            obstacles = [*candidate.values(), *existing, *(keepout for _, keepout, _ in pads)]
            total, region_sites = gpu_sites(rows, height, obstacles, regions)
            margin = {name: region_sites[name] - demand[name] for name in regions}
            shifts = {name: (box[0] - halos[name][0], box[1] - halos[name][1])
                      for name, box in candidate.items() if box != halos[name]}
            distances = [abs(x) + abs(y) for x, y in shifts.values()]
            rank = sum(max(0, -value) for value in margin.values()), -total, max(distances, default=0), sum(distances)
            scored += 1
            if best is None or rank < best[0]:
                best = rank, alignment, candidate, shifts, pads, distribution, obstacles, total, region_sites
    assert best is not None
    return best, attempts, checked, scored


def run():
    evidence = {}

    def pin(path, expected=None):
        actual = digest(path)
        assert expected is None or actual == expected, path
        assert evidence.setdefault(str(path), actual) == actual, path
        return path

    plan = read(pin(BASE))
    current = read(pin(TRANSFER))
    gated = read(pin(RECEIVER))
    prior = plan["evidence_sha256"]
    (source,) = (pin(Path(name), checksum) for name, checksum in prior.items() if checksum == plan["cold_layout_sha256"])
    assert digest(source) == current["input_layout_sha256"]
    files = [pin(Path(name), checksum) for name, checksum in prior.items() if name.endswith(".lef")]
    lef, release, tech = (next(pin(Path(name), checksum) for name, checksum in prior.items() if name.endswith(suffix))
                          for suffix in ("sefu10lm.tar.gz", "rln.tar.gz", ".tlef"))
    depth_um, corner_um, _, rules, _ = vendor_rules(lef, release)
    rule = rules["pad50_independent_fillers"]
    units, rows, fixed, halos, regions, existing, placed_area, regional_area = layout(source, files)
    side, depth, corner = 3600 * units, int(depth_um * units), int(corner_um * units)
    grid = int(Decimal(re.search(r"MANUFACTURINGGRID ([\d.]+)", tech.read_text())[1]) * units)
    strips = {"bottom": (corner, 0, side - corner, depth), "top": (corner, side - depth, side - corner, side),
              "left": (0, corner, depth, side - corner), "right": (side - depth, corner, side, side - corner)}
    height = rows[1][1] - rows[0][1]
    site_area = rows[0][3] * height
    assert placed_area == site_area * current["old_standard_cell_sites"]
    demand = {name: area // site_area for name, area in regional_area.items()}
    assert all(area % site_area == 0 for area in regional_area.values())
    target = plan["required_sites"] - 6
    assert target == 497

    best, attempts, checked, scored = search_floorplans(
        rows, height, halos, existing, strips, units, rule, grid, side, depth, target, demand, regions,
    )
    _, alignment, candidate, shifts, pads, distribution, obstacles, total, region_sites = best
    die = 0, 0, side, side
    memories = list(candidate.values())
    assert all(contains(die, box) for box in memories)
    assert all(not overlap(a, b) for index, a in enumerate(memories) for b in memories[:index])
    for x in (0, side - corner):
        for y in (0, side - corner):
            assert not any(overlap((x, y, x + corner, y + corner), box) for box in memories)
    for index, (edge, keepout, body) in enumerate(pads):
        assert contains(strips[edge], keepout) and contains(keepout, body) and all(value % grid == 0 for value in body)
        assert not any(overlap(keepout, box) for box in memories)
        assert not any(overlap(keepout, other) for _, other, _ in pads[:index])
    assert Counter(edge for edge, _, _ in pads) == distribution and len(pads) == target
    blockers = {key: (x1, y1, x2 - x1, y2 - y1, (0, 0, 0, 0))
                for key, (x1, y1, x2, y2) in enumerate(obstacles)}
    assert row_sites(rows, height, die, blockers) == total
    assert all(row_sites(rows, height, region, blockers) == region_sites[name] for name, region in regions.items())
    assert all(region_sites[name] >= demand[name] for name in regions)

    pad_table = WORK / "pad_slots.tsv"
    memory_table = WORK / "memory_macros.tsv"
    with pad_table.open("w") as stream:
        stream.write("edge\tkeepout_x1\tkeepout_y1\tkeepout_x2\tkeepout_y2\tbody_x1\tbody_y1\tbody_x2\tbody_y2\n")
        for edge, reserve, body in pads:
            stream.write("\t".join(map(str, (edge, *reserve, *body))) + "\n")
    with memory_table.open("w") as stream:
        stream.write("instance\tmaster\tx_dbu\ty_dbu\torientation\n")
        for name, (dx, dy) in sorted(shifts.items()):
            master, _, x, y, orientation, _ = fixed[name]
            assert (x + dx) % grid == (y + dy) % grid == 0
            stream.write(f"{name.decode()}\t{master}\t{x + dx}\t{y + dy}\t{orientation}\n")
    for path in (pad_table, memory_table, Path(__file__).resolve().relative_to(ROOT),
                 Path("syn/plan_tri_oracle_bonded_pad_recovery.py")):
        pin(path)
    return {
        "state": "current_pad_target_reoptimized_and_site_counts_independently_verified",
        "device": torch.cuda.get_device_name(), "pad_reservations": target, "reserved_by_edge": distribution,
        "macro_windows_attempted": attempts, "feasible_macro_layouts_screened": checked,
        "placement_grid_variants_screened": scored, "selected_alignment": alignment,
        "moved_memory_macros": len(shifts),
        "previous_geometric_site_capacity": current["geometric_sites_after_497_pad_reservations"],
        "new_geometric_site_capacity": total,
        "site_capacity_change": total - current["geometric_sites_after_497_pad_reservations"],
        "geometric_site_margin_with_verified_gated_receiver": total - current["wrapped_standard_cell_sites"] + gated["sites_saved"],
        "scope": "Exact geometric row capacity after reserving 497 slots and adjusting the same 631 memory macros. "
                 "Counts were independently recomputed with integer row intervals. Native placement, bonded IO "
                 "extension, power and ground closure, timing, and routing are unverified.",
        "evidence_sha256": evidence,
    }


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    with Path("/proc/meminfo").open() as info:
        assert next(int(line.split()[1]) for line in info if line.startswith("MemAvailable:")) >= 8 * 1024**2
    assert torch.cuda.mem_get_info()[0] >= 2 * 1024**3
    torch.cuda.set_per_process_memory_fraction(0.15)
    WORK.mkdir(parents=True, exist_ok=True)
    print(json.dumps(run(), indent=2, sort_keys=True))
