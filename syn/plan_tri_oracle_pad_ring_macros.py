"""Generate a macro placement seed that leaves room for a perimeter pad row."""

import argparse
from collections import Counter
from decimal import Decimal
import json
from pathlib import Path
import re

from audit_tri_oracle_pad_ring_clearance import POSE, contains, dimensions, get_units, overlap
from audit_tri_oracle_placed_chip_boundary import PAD_ARCHIVE, digest, pad_views


ROOT = Path(__file__).resolve().parents[1]
ROW = re.compile(r"ROW \S+ core12T (\d+) (\d+) (N|FS) DO (\d+) BY 1 STEP (\d+) 0\b")


def macro_box(pose):
    x, y, width, height, halo = pose
    left, bottom, right, top = halo
    return x - left, y - bottom, x + width + right, y + height + top


def load_floorplan(design, libraries, technology):
    with design.open() as source:
        units = get_units(source)
        sizes = dimensions(libraries, units)
        tech = technology.read_text()
        grid = Decimal(re.search(r"MANUFACTURINGGRID ([\d.]+)", tech)[1]) * units
        assert grid == int(grid) and grid > 0
        grid = int(grid)
        count = None
        rows, fixed, masters = [], {}, {}
        for line in source:
            if match := ROW.match(line):
                x, y, _, sites, pitch = match.groups()
                rows.append(tuple(map(int, (x, y, sites, pitch))))
            if match := re.fullmatch(r"COMPONENTS (\d+) ;\n", line):
                count = int(match[1])
                break
        assert count == 3765868 and len(rows) == len({row[1] for row in rows}) == 2966
        movable_area = 0
        seen = 0
        for line in source:
            if line == "END COMPONENTS\n":
                break
            if not line.startswith("- "):
                continue
            seen += 1
            name, master, status, x, y, orient = POSE.match(line).groups()
            width, height = sizes[master]
            if status == "PLACED":
                movable_area += width * height
                continue
            assert orient in {"N", "S", "FN", "FS"} and name not in fixed
            assert int(x) % grid == int(y) % grid == 0
            halo_line = next(source)
            assert re.fullmatch(r"\s*\+ HALO (?:\d+ ){3}\d+\s*\n", halo_line)
            halo = tuple(map(int, halo_line.split()[2:]))
            fixed[name] = (int(x), int(y), width, height, halo)
            masters[name] = (master, orient)
        assert seen == count and len(fixed) == len(masters) == 631
    return units, grid, rows, fixed, masters, movable_area


def shift_inward(fixed, axis, minimum, grid):
    other = 1 - axis
    result = {}
    for name, pose in sorted(fixed.items(), key=lambda item: (item[1][axis], item[0])):
        before = macro_box(pose)
        required = minimum + pose[4][axis]
        for placed in result.values():
            box = macro_box(placed)
            if max(box[other], before[other]) < min(box[other + 2], before[other + 2]):
                required = max(required, box[axis + 2] + pose[4][axis])
        position = max(pose[axis], -(-required // grid) * grid)
        result[name] = (position, *pose[1:]) if axis == 0 else (pose[0], position, *pose[2:])
    return result


def validate_boxes(fixed, outline):
    boxes = list(map(macro_box, fixed.values()))
    assert all(contains(outline, box) for box in boxes)
    for index, box in enumerate(boxes):
        assert not any(overlap(box, other) for other in boxes[:index]), index


def row_sites(rows, height, outline, fixed):
    boxes = list(map(macro_box, fixed.values()))
    left, bottom, right, top = outline
    total = 0
    for x, y, length, pitch in rows:
        if y < bottom or y + height > top:
            continue
        start = max(0, -(-(left - x) // pitch))
        end = min(length, (right - x) // pitch)
        intervals = []
        for x1, y1, x2, y2 in boxes:
            if max(y, y1) < min(y + height, y2):
                lo = max(start, (x1 - x) // pitch)
                hi = min(end, -(-(x2 - x) // pitch))
                if lo < hi:
                    intervals.append((lo, hi))
        cursor = start
        for lo, hi in sorted(intervals):
            total += max(0, lo - cursor)
            cursor = max(cursor, hi)
        total += end - cursor
    return total


def area_budget(outline, fixed, movable_area, units):
    left, bottom, right, top = outline
    interior = (right - left) * (top - bottom)
    occupied = sum((x2 - x1) * (y2 - y1) for x1, y1, x2, y2 in map(macro_box, fixed.values()))
    free = interior - occupied
    assert free > 0
    to_mm2 = units**2 * 10**6
    return dict(interior_mm2=interior / to_mm2, fixed_macro_halo_area_mm2=occupied / to_mm2,
                area_available_to_movable_cells_mm2=free / to_mm2,
                standard_cell_area_margin_mm2=(free - movable_area) / to_mm2)


def run(design, libdir, pad_archive, output):
    reference = ROOT / "records/tri_oracle_pad_ring_clearance.json"
    prior = ROOT / "records/tri_oracle_grouped_active_placement.json"
    clearance, checkpoint = (json.loads(path.read_text()) for path in (reference, prior))
    assert clearance["candidate_netlist_sha256"] == checkpoint["candidate_netlist_sha256"]
    assert digest(design) == checkpoint["placed_design_exchange_sha256"]
    libraries = sorted(libdir.glob("*.lef"))
    technology, = libdir.glob("*.tlef")
    assert len(libraries) == 7
    assert all(digest(path) == clearance["evidence_sha256"][str(path.relative_to(ROOT))] for path in libraries)
    _, _, width, corner, abstract = pad_views(pad_archive)
    boundary_path = ROOT / "records/tri_oracle_grouped_active_boundary.json"
    assert digest(boundary_path) == clearance["evidence_sha256"][str(boundary_path.relative_to(ROOT))]
    boundary = json.loads(boundary_path.read_text())
    assert (width, corner, abstract) == (Decimal(20), Decimal(110), boundary["pad_abstract_sha256"])
    units, grid, rows, fixed, masters, movable_area = load_floorplan(design, libraries, technology)
    side = 3600 * units
    depth = int(Decimal(clearance["full_perimeter_component_clearance_micrometers"]) * units)
    outline = (depth, depth, side - depth, side - depth)
    validate_boxes(fixed, (0, 0, side, side))
    revised = shift_inward(shift_inward(fixed, 0, depth, grid), 1, depth, grid)
    validate_boxes(revised, outline)
    moves = {name: sum(revised[name][axis] - pose[axis] for axis in (0, 1))
             for name, pose in fixed.items() if revised[name] != pose}
    blockers = sum(not contains(outline, macro_box(pose)) for pose in fixed.values())
    height = int(Decimal("1.2") * units)
    current = row_sites(rows, height, (0, 0, side, side), fixed)
    reserved = row_sites(rows, height, outline, revised)
    pitch, = {row[3] for row in rows}
    site_area = pitch * height
    assert current >= reserved > 0
    site_deficit = max(0, -(-movable_area // site_area) - reserved)
    counts = Counter(masters[name][0] for name in moves)
    with output.open("x") as stream:
        stream.write("instance\tmaster\tx_um\ty_um\torient\n")
        for name in sorted(moves):
            x, y, *_ = revised[name]
            master, orientation = masters[name]
            stream.write(f"{name}\t{master}\t{Decimal(x)/units}\t{Decimal(y)/units}\t{orientation}\n")
    return dict(
        state="pad_ring_macro_seed_screened_for_chip_cell_capacity",
        candidate_netlist_sha256=checkpoint["candidate_netlist_sha256"],
        existing_macros=631, moved_macros=len(moves), original_halos_intersecting_perimeter=blockers,
        moved_macros_by_master=counts, maximum_macro_manhattan_move_micrometers=float(Decimal(max(moves.values()))/units),
        reserved_pad_depth_micrometers=str(Decimal(depth)/units),
        potential_perimeter_slots=4 * int((Decimal(3600) - 2 * corner) // width),
        continuous_area_budget=area_budget(outline, revised, movable_area, units),
        site_capacity=dict(original_geometric_sites=current, new_geometric_sites=reserved,
                           existing_standard_cell_area_mm2=movable_area / (units**2 * 10**6),
                           original_geometric_utilization_percent=100 * movable_area / (current * site_area),
                           new_geometric_utilization_percent=100 * movable_area / (reserved * site_area),
                           minimum_site_deficit=site_deficit,
                           fits_existing_standard_cell_area=site_deficit == 0),
        evidence_sha256={str(path.relative_to(ROOT)): digest(path) for path in
                         (reference, boundary_path, prior, design, technology, output, Path(__file__).resolve())},
        scope="The seed preserves each memory master and orientation and keeps all macro halos clear of the reserved perimeter. "
              "Row counts are geometric and exclude new pad control logic, native blockage accounting, congestion and timing. "
              "If the cell area exceeds the geometric bound, this seed cannot proceed to legalization with the existing cells.",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("design", "libdir", "output"):
        parser.add_argument(name, type=lambda value: Path(value).absolute())
    parser.add_argument("--pad-archive", type=Path, default=PAD_ARCHIVE)
    args = parser.parse_args()
    print(json.dumps(run(**vars(args)), sort_keys=True, indent=2))
