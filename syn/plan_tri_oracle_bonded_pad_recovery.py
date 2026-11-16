"""Screen independent-filler pad locations against the latest cold floorplan."""
import argparse
from collections import Counter
from decimal import Decimal
import json
from mmap import mmap, ACCESS_READ
from pathlib import Path
import re

import torch

from audit_tri_oracle_bonded_pad_capacity import capacity, free_intervals, vendor_rules
from audit_tri_oracle_pad_ring_clearance import contains, dimensions, get_units, overlap
from audit_tri_oracle_physical_io_budget import macro_boxes
from audit_tri_oracle_placed_chip_boundary import digest
from plan_tri_oracle_pad_ring_macros import ROW, row_sites
from verify_tri_oracle_pad_cold_reload import components


ROOT = Path(__file__).resolve().parents[1]
BONDED = Path("records/tri_oracle_bonded_pad_capacity.json")
CONTROLS = Path("records/tri_oracle_serial_control_pads.json")
FLIP = Path("records/tri_oracle_flip_chip_geometry.json")
GIB = 2**30
EDGE_ORDER = ("bottom", "left", "right", "top")


def read(path):
    return json.loads(path.read_text())


def section(data, key):
    header = data.find(b"\n" + key + b" ")
    assert header >= 0
    first = data.find(b"\n", header + 1) + 1
    end = data.find(b"\nEND " + key + b"\n", first)
    assert end > first
    return data[first:end].decode()


def layout(path, lefs):
    with path.open() as stream:
        units = get_units(stream)
        sizes = dimensions(lefs, units)
        rows = []
        for line in stream:
            if match := ROW.match(line):
                x, y, _, length, pitch = match.groups()
                rows.append(tuple(map(int, (x, y, length, pitch))))
            if line.startswith("COMPONENTS "):
                expected_components = int(line.split()[1])
                break
    with path.open("rb") as stream, mmap(stream.fileno(), 0, access=ACCESS_READ) as data:
        regions = {}
        for line in section(data, b"REGIONS").splitlines():
            name, *coordinates = re.fullmatch(
                r"- (\w+) \( (\d+) (\d+) \) \( (\d+) (\d+) \) ;", line).groups()
            regions[name] = tuple(map(int, coordinates))
        groups = {rule.rstrip("*").encode(): name for rule, name in re.findall(
            r"(?m)^ +([^\s]+\*)\n +\+ REGION (\w+) ;$", section(data, b"GROUPS"))}
        existing = [tuple(map(int, match)) for match in re.findall(
            r"(?m)^\s*- PLACEMENT RECT \( (\d+) (\d+) \) \( (\d+) (\d+) \) ;$",
            section(data, b"BLOCKAGES"))]
    assert len(groups) == len(regions) == 20 and set(groups.values()) == set(regions)
    assert len(existing) == 4
    path_prefix = re.escape(next(iter(groups)).split(b"cores")[0].split(b"clusters")[0])
    owner_pattern = re.compile(path_prefix + rb".*?/cores\\\[\d+\\\]/compute/compute/")
    fixed, usage = {}, Counter()
    area = instances = 0
    for name, pose in components(path):
        master, status, *_ = pose
        instances += 1
        if status == "FIXED":
            fixed[name] = pose
            continue
        assert status == "PLACED"
        w, h = sizes[master]
        area += w * h
        owner = owner_pattern.match(name)
        if owner:
            region = groups.get(owner[0])
            assert region is not None, name
            usage[region] += w * h
    assert instances == expected_components and len(fixed) == 631 and len(usage) == 20
    _, halos = macro_boxes(fixed, sizes)
    return units, sorted(rows, key=lambda row: row[1]), fixed, halos, regions, existing, area, usage


def inventory(halos, strips, units, rule):
    intervals = {edge: free_intervals(strips[edge], int(edge in ("left", "right")), halos.values())
                 for edge in EDGE_ORDER}
    counts = {edge: capacity(parts, units, rule) for edge, parts in intervals.items()}
    return intervals, counts


def search(halos, strips, depth, grid, side, units, rule, minimum):
    # Scan each contiguous group of obstructing bottom macros. Preserve the
    # horizontal footprint and original vertical order of overlapping macros.
    order = sorted(halos, key=lambda name: (halos[name][1], name))
    boxes = [halos[name] for name in order]
    precedents = [[j for j, other in enumerate(boxes[:i])
                   if max(other[0], box[0]) < min(other[2], box[2])]
                  for i, box in enumerate(boxes)]
    bottom = sorted((i for i, box in enumerate(boxes) if overlap(box, strips["bottom"])),
                    key=lambda i: boxes[i][0])
    scenarios = []
    attempts = 0
    for lo in range(len(bottom)):
        for hi in range(lo + 1, len(bottom) + 1):
            attempts += 1
            selected = set(bottom[lo:hi])
            shifts = []
            for i, (x1, y1, x2, y2) in enumerate(boxes):
                clear = depth if i in selected else y1
                bound = max((boxes[j][3] + shifts[j] for j in precedents[i]), default=y1)
                shift = max(0, -(-(max(clear, bound) - y1) // grid) * grid)
                shifts.append(shift)
            if any(box[3] + shift > side - depth for box, shift in zip(boxes, shifts, strict=True)):
                continue
            candidate = {
                name: (x1, y1 + delta, x2, y2 + delta)
                for name, (x1, y1, x2, y2), delta in zip(order, boxes, shifts, strict=True)
            }
            _, counts = inventory(candidate, strips, units, rule)
            if sum(counts.values()) >= minimum:
                moved = {name: shift for name, shift in zip(order, shifts, strict=True) if shift}
                score = max(moved.values()), sum(moved.values()), len(moved)
                scenarios.append((score, candidate, moved, counts))
    assert attempts == len(bottom) * (len(bottom) + 1) // 2 and scenarios
    return attempts, sorted(scenarios, key=lambda option: option[0])


def align_to_sites(boxes, axis, origin, step, limit):
    """Move halos forward when rounding would block an extra row or column."""
    result = {}
    across = 1 - axis
    for name, box in sorted(boxes.items(), key=lambda entry: (entry[1][axis], entry[0])):
        lower = max((other[axis + 2] for other in result.values()
                     if max(other[across], box[across]) < min(other[across + 2], box[across + 2])),
                    default=box[axis])
        start = max(box[axis], lower)
        span = box[axis + 2] - box[axis]
        rounded = -(-(start + span - origin) // step) - (start - origin) // step
        if rounded > -(-span // step):
            start = origin - (-(start - origin) // step) * step
        if start + span > limit:
            return None
        moved = list(box)
        moved[axis], moved[axis + 2] = start, start + span
        result[name] = tuple(moved)
    return result


def reserves(intervals, counts, strips, units, rule, total):
    pad_width, gap, end = (int(size * units) for size in rule)
    assert gap == end and gap % 2 == 0
    result = []
    details = Counter()
    # Keep the full left, right and top edges available. The bottom edge
    # supplies the remaining pins after the three unaffected edges.
    for edge in ("left", "right", "top", "bottom"):
        horizontal = edge in ("bottom", "top")
        count = min(counts[edge], total - len(result))
        for start, stop in intervals[edge]:
            stride = pad_width + gap
            for site in range(start, stop - stride + 1, stride):
                if details[edge] == count:
                    break
                (x1, y1, x2, y2) = strips[edge]
                rectangle = (site, y1, site + stride, y2) if horizontal else (x1, site, x2, site + stride)
                body = (rectangle[0] + gap // 2, rectangle[1], rectangle[2] - gap // 2, rectangle[3]) if horizontal else (
                        rectangle[0], rectangle[1] + gap // 2, rectangle[2], rectangle[3] - gap // 2)
                result.append((edge, rectangle, body))
                details[edge] += 1
        assert details[edge] == count
    assert len(result) == total
    return result, dict(details)


def gpu_sites(rows, height, boxes, regions):
    # Occupancy [R,C] represents R physical rows and C legal horizontal sites.
    # The blockages and fixed halos are rasterized with outward rounding.
    x, y, count, pitch = rows[0]
    assert rows == [(x, y + index * height, count, pitch) for index in range(len(rows))]
    occupied = torch.zeros((len(rows), count), dtype=torch.bool, device="cuda")
    for left, bottom, right, top in boxes:
        ymin = max(0, (bottom - y) // height)
        ymax = min(len(rows), -(-(top - y) // height))
        xmin = max(0, (left - x) // pitch)
        xmax = min(count, -(-(right - x) // pitch))
        if ymin < ymax and xmin < xmax:
            occupied[ymin:ymax, xmin:xmax] = True
    output = {}
    for name, (left, bottom, right, top) in regions.items():
        ymin = max(0, -(-(bottom - y) // height))
        ymax = min(len(rows), (top - y) // height)
        xmin = max(0, -(-(left - x) // pitch))
        xmax = min(count, (right - x) // pitch)
        view = occupied[ymin:ymax, xmin:xmax]
        output[name] = view.numel() - int(torch.count_nonzero(view))
    return occupied.numel() - int(torch.count_nonzero(occupied)), output


def continuous_site_upper_bound(rows, height, side, depth, corner, pad_pitch, pads, halos):
    """Grant every pad the shallowest row overlap and ignore site rounding."""
    left, bottom, cols, pitch = rows[0]
    right = left + cols * pitch
    top = rows[-1][1] + height
    outline = left, bottom, right, top
    assert all(contains(outline, box) for box in halos.values())
    row_area = (right - left) * (top - bottom)
    halo_area = sum((x2 - x1) * (y2 - y1) for x1, y1, x2, y2 in halos.values())
    least_pad_depth = min(depth - left, depth - bottom, right - (side - depth), top - (side - depth))
    corners_area = (corner - left + right - (side - corner)) * (corner - bottom + top - (side - corner))
    assert least_pad_depth > 0 and corners_area > 0
    return (row_area - halo_area - pads * pad_pitch * least_pad_depth - corners_area) // (pitch * height)


def fewer_pads(rows, height, obstacles, existing, slots, demand, die):
    """Measure releasing a contiguous strip outside the old blockages."""
    bottoms = sorted(rect for edge, rect, _ in slots if edge == "bottom")
    starts = [index for index, rect in enumerate(bottoms)
              if index == 0 or bottoms[index - 1][2] < rect[0]]
    for index in starts:
        run = bottoms[index:index + 6]
        if len(run) != 6 or any(a[2] != b[0] for a, b in zip(run, run[1:])):
            continue
        if not any(overlap(rect, old) for rect in run for old in existing):
            break
    else:
        raise ValueError("No six adjacent bottom pads outside the original reserve")
    answer = {}
    for count in range(1, len(run) + 1):
        released = set(run[:count])
        areas = [*obstacles, *existing, *(box for _, box, _ in slots if box not in released)]
        total, _ = gpu_sites(rows, height, areas, {})
        answer[count] = total - demand
        if count in (2, 3, len(run)):
            blockers = {key: (x1, y1, x2 - x1, y2 - y1, (0, 0, 0, 0))
                        for key, (x1, y1, x2, y2) in enumerate(areas)}
            assert row_sites(rows, height, die, blockers) - demand == answer[count]
    return answer


def run(out):
    assert Path.cwd() == ROOT and not Path("/.dockerenv").exists() and __debug__
    with Path("/proc/meminfo").open() as stream:
        assert next(int(line.split()[1]) for line in stream if line.startswith("MemAvailable:")) * 1024 >= 8 * GIB
    assert torch.cuda.mem_get_info()[0] >= 2 * GIB
    torch.cuda.set_per_process_memory_fraction(0.15)
    bonded, interface, flip = read(BONDED), read(CONTROLS), read(FLIP)
    target = interface["physical_chip_boundary_signal_bits"] + interface["illustrative_supply_and_ground_reserve"]
    inputs = bonded["evidence_sha256"]
    design = Path(bonded["cold_floorplan"])
    lefs = [Path(p) for p in inputs if p.endswith(".lef")]
    lef, = [Path(p) for p in inputs if p.endswith("sefu10lm.tar.gz")]
    release, = [Path(p) for p in inputs if p.endswith("rln.tar.gz")]
    technology, = [Path(p) for p in flip["evidence_sha256"] if p.endswith(".tlef")]
    for path in (design, *lefs, lef, release):
        assert digest(path) == inputs[str(path)], path
    assert digest(technology) == flip["evidence_sha256"][str(technology)]
    depth_um, corner_um, _, rules, _ = vendor_rules(lef, release)
    rule = rules["pad50_independent_fillers"]
    units, rows, fixed, halos, regions, existing, area, usage = layout(design, lefs)
    side, depth, corner = 3600 * units, int(depth_um * units), int(corner_um * units)
    grid = int(Decimal(re.search(r"MANUFACTURINGGRID ([\d.]+)", technology.read_text())[1]) * units)
    strips = {"bottom": (corner, 0, side - corner, depth),
              "top": (corner, side - depth, side - corner, side),
              "left": (0, corner, depth, side - corner),
              "right": (side - depth, corner, side, side - corner)}
    _, old = inventory(halos, strips, units, rule)
    assert old == bonded["geometry"]["capacity_by_case_and_edge"]["pad50_independent_fillers"]
    height = 2400
    pitch = rows[0][3]
    site_area = pitch * height
    assert area % site_area == 0 and all(size % site_area == 0 for size in usage.values())
    used = area // site_area
    old_total, old_regions = gpu_sites(rows, height, [*halos.values(), *existing], regions)
    required = {name: size // site_area for name, size in usage.items()}
    assert old_total >= used and all(old_regions[name] >= count for name, count in required.items())
    attempts, candidates = search(halos, strips, depth, grid, side, units, rule, target)
    screened = []
    seen = set()
    checked = 0
    for _, boxes, moved, counts in candidates:
        outcome = (tuple(moved.items()), tuple(counts.items()))
        if outcome in seen:
            continue
        checked += 1
        seen.add(outcome)
        column_step = (0, rows[0][0], pitch, side - depth)
        row_step = (1, rows[0][1], height, side - depth)
        row_aligned = align_to_sites(boxes, *row_step)
        column_aligned = align_to_sites(boxes, *column_step)
        for alignment, candidate in (
            ("none", boxes), ("rows", row_aligned),
            ("rows_then_columns", align_to_sites(row_aligned, *column_step) if row_aligned else None),
            ("columns_then_rows", align_to_sites(column_aligned, *row_step) if column_aligned else None),
        ):
            if candidate is None:
                continue
            intervals, counts = inventory(candidate, strips, units, rule)
            if sum(counts.values()) < target:
                continue
            shifts = {name: (box[0] - halos[name][0], box[1] - halos[name][1])
                      for name, box in candidate.items() if box != halos[name]}
            slots, distribution = reserves(intervals, counts, strips, units, rule, target)
            areas = [*candidate.values(), *existing, *(rectangle for _, rectangle, _ in slots)]
            total, by_region = gpu_sites(rows, height, areas, regions)
            margins = {name: by_region[name] - count for name, count in required.items()}
            distances = [sum(delta) for delta in shifts.values()]
            rank = (sum(max(0, -value) for value in margins.values()), max(0, used - total),
                    max(distances), sum(distances), len(shifts))
            screened.append((rank, candidate, shifts, counts, slots, distribution, areas, total, margins, alignment))
        if checked >= 20:
            break
    rank, boxes, moved, counts, slots, distribution, areas, total, margins, alignment = min(
        screened, key=lambda row: row[0])
    die = (0, 0, side, side)
    obstacles = list(boxes.values())
    assert all(contains(die, box) for box in obstacles)
    assert not any(overlap(box, earlier) for index, box in enumerate(obstacles) for earlier in obstacles[:index])
    corner_boxes = [(x, y, x + corner, y + corner) for x in (0, side - corner) for y in (0, side - corner)]
    assert all(not overlap(corner, obstacle) for corner in corner_boxes for obstacle in obstacles)
    for index, (edge, keepout, body) in enumerate(slots):
        assert contains(strips[edge], keepout) and contains(keepout, body)
        assert all(value % grid == 0 for value in body), body
        assert not any(overlap(keepout, obstacle) for obstacle in obstacles)
        assert not any(overlap(keepout, other) for _, other, _ in slots[:index])
    # Independently verify the final site counts with integer intervals.
    blockers = {key: (x1, y1, x2 - x1, y2 - y1, (0, 0, 0, 0))
                for key, (x1, y1, x2, y2) in enumerate(areas)}
    assert row_sites(rows, height, die, blockers) == total
    for name, region in regions.items():
        assert row_sites(rows, height, region, blockers) == margins[name] + required[name], name
    pad_pitch = int((rule[0] + rule[1]) * units)
    ideal_sites = continuous_site_upper_bound(rows, height, side, depth, corner, pad_pitch, target, boxes)
    assert ideal_sites >= total
    area_in_site_units = Decimal(str(interface["mapped_area_square_micrometers"])) * units**2 / site_area
    assert area_in_site_units == int(area_in_site_units)
    adapter_sites = int(area_in_site_units)
    sensitivity = fewer_pads(rows, height, obstacles, existing, slots, used + adapter_sites, die)
    out.mkdir(parents=True, exist_ok=True)
    moves_path = out / "memory_macros.tsv"
    with moves_path.open("w") as stream:
        stream.write("instance\tmaster\tx_dbu\ty_dbu\torientation\n")
        for name, (dx, dy) in sorted(moved.items()):
            master, _, x, y, orientation, _ = fixed[name]
            assert (x + dx) % grid == (y + dy) % grid == 0
            stream.write(f"{name.decode()}\t{master}\t{x + dx}\t{y + dy}\t{orientation}\n")
    pads_path = out / "pad_slots.tsv"
    with pads_path.open("w") as stream:
        stream.write("edge\tkeepout_x1\tkeepout_y1\tkeepout_x2\tkeepout_y2\tbody_x1\tbody_y1\tbody_x2\tbody_y2\n")
        for edge, reserve, body in slots:
            stream.write("\t".join(map(str, (edge, *reserve, *body))) + "\n")
    return {
        "state": "independent_filler_pad_seed_screened_against_cold_chip",
        "cold_layout_sha256": inputs[str(design)],
        "old_slots": old, "new_slots": counts, "reserved_slots": distribution, "required_sites": target,
        "attempted_contiguous_blocker_windows": attempts, "pad_feasible_windows": len(candidates),
        "site_screened_candidates": len(screened),
        "site_grid_alignment_in_selected_candidate": alignment,
        "best_global_row_margin_without_row_alignment": max(
            item[7] - used for item in screened if item[-1] == "none"),
        "moved_static_ram_macros": len(moved),
        "max_vertical_macro_movement_micrometers": max(dy for _, dy in moved.values()) / units,
        "max_horizontal_macro_movement_micrometers": max(dx for dx, _ in moved.values()) / units,
        "global_row_sites_old": old_total, "global_row_sites_new": total, "required_standard_cell_sites": used,
        "global_remaining_sites_before_new_logic": total - used,
        "mapped_control_sites_required": adapter_sites,
        "site_margin_after_control_logic_by_additional_pads_released": sensitivity,
        "remaining_area_before_new_logic_square_micrometers": (total - used) * site_area / units**2,
        "continuous_site_upper_bound_before_rounding": ideal_sites,
        "continuous_margin_before_rounding_and_new_logic": ideal_sites - used,
        "min_group_remaining_sites_before_global_logic": min(margins.values()),
        "negative_fenced_region_site_margins": {key: value for key, value in margins.items() if value < 0},
        "initial_min_group_remaining_sites": min(old_regions[name] - required[name] for name in regions),
        "scope": "Geometric independent-filler pad reservations and static random-access memory macro positions, "
                 "with exact existing row-site and fenced compute site counts. A positive count is a necessary "
                 "capacity result with current cells. Native legalization, pad-cell connections, power delivery, "
                 "routing, setup and hold timing, and package escape are unverified.",
        "evidence_sha256": {str(path): digest(path) for path in
                            (design, *lefs, lef, release, technology, BONDED, CONTROLS, moves_path, pads_path,
                             Path(__file__).resolve().relative_to(ROOT))},
    }


if __name__ == "__main__":
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("out", type=Path)
    opts = args.parse_args()
    print(json.dumps(run(opts.out), indent=2, sort_keys=True))
