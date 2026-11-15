"""Verify existing poses and the supply of legal sites for the wider chip."""

import argparse
from bisect import bisect_left, insort
from collections import Counter
import json
from pathlib import Path
import re

from audit_tri_oracle_pad_ring_clearance import POSE, dimensions
from audit_tri_oracle_placed_chip_boundary import digest
from plan_tri_oracle_pad_ring_macros import ROW, macro_box, validate_boxes
from prepare_tri_oracle_dual_group_placement_seed import NATIVE, RAW_CHILD, old_rows, read
from verify_tri_oracle_pad_cold_reload import COMPONENTS, HALO, boundary_sections
from verify_tri_oracle_partial_pad_ring_geometry import mark_reserved


UNPLACED = re.compile(r"^- (\S+) (\S+) \+ UNPLACED ;\n$")
OUTLINE = (0, 0, 7200000, 7200000)
PITCH = 280
HEIGHT = 2400
CLEAR_MOVABLE = bytes.maketrans(b"\x02", b"\x00")


def candidates(stream):
    for line in stream:
        if line == "END COMPONENTS\n":
            return
        if line.startswith("- "):
            if item := UNPLACED.fullmatch(line):
                yield item[1], item[2], "UNPLACED", None
                continue
            match = POSE.match(line)
            assert match, line
            name, master, status, x, y, orient = match.groups()
            clearance = ()
            if status == "FIXED":
                halo = HALO.fullmatch(next(stream))
                assert halo, name
                clearance = tuple(map(int, halo.groups()))
            yield name, master, status, (int(x), int(y), orient, clearance)
    raise ValueError("Missing end of components")


def read_rows(stream):
    rows = {}
    for line in stream:
        if row := ROW.fullmatch(line.rstrip("\n")):
            x, y, orient, count, pitch = row.groups()
            x, y, count, pitch = map(int, (x, y, count, pitch))
            assert x == 40000 and y not in rows and pitch == PITCH and count == 25428
            rows[y] = orient, bytearray(count)
        if mark := COMPONENTS.fullmatch(line):
            assert len(rows) == 2966
            return rows, int(mark[1])
    raise ValueError("Missing placement rows")


def require_free_space(fragments, needed):
    available = sorted(fragments)
    for width, amount in sorted(needed.items(), reverse=True):
        for _ in range(amount):
            index = bisect_left(available, width)
            if index == len(available):
                raise ValueError(f"No legal interval remains for a {width}-site cell")
            best = available[index]
            fragments[best] -= 1
            if fragments[best] == 0:
                available.pop(index)
            left = best - width
            if left:
                if fragments[left] == 0:
                    insort(available, left)
                fragments[left] += 1
    return sum(width * count for width, count in fragments.items())


def fragments(grid):
    return Counter(len(match[0]) for match in re.finditer(rb"\x00+", grid))


def protected(name):
    return name.rsplit("/", 1)[-1].startswith("TRI_") or name.startswith(RAW_CHILD)


def choose_released_rows(rows, demand, free, movable):
    # A regular subset spreads additional room across the die. Evaluate a
    # sparse subset first and open more rows only if the fit still fails.
    row_positions = sorted(rows)
    for stride in (256, 128, 64, 48, 32, 24, 16, 12, 8, 6, 4, 3, 2, 1):
        for offset in range(min(stride, 4)):
            selected = row_positions[offset::stride]
            gaps, cells = free.copy(), demand.copy()
            for y in selected:
                _, grid = rows[y]
                gaps.subtract(fragments(grid))
                gaps.update(fragments(grid.translate(CLEAR_MOVABLE)))
                cells.update(movable.get(y, ()))
            try:
                remaining = require_free_space(+gaps, cells)
            except ValueError:
                continue
            return selected, cells.total() - demand.total(), remaining
    raise ValueError("Row release did not produce an interval-packing certificate")


def release_placements(seed, output, selected):
    wanted = set(selected)
    replaced = 0
    with seed.open() as source, output.open("x") as destination:
        in_components = False
        for line in source:
            if COMPONENTS.fullmatch(line):
                in_components = True
            elif line == "END COMPONENTS\n":
                in_components = False
            pose = POSE.match(line) if in_components else None
            if pose and pose[3] == "PLACED" and int(pose[5]) in wanted and not protected(pose[1]):
                destination.write(f"- {pose[1]} {pose[2]} + UNPLACED ;\n")
                replaced += 1
            else:
                destination.write(line)
    return replaced


def verify_geometry(seed, parent, sizes, *, allow_release=False):
    sections = boundary_sections(seed)
    assert sections == boundary_sections(parent)
    reference_macros = {}
    for line in old_rows(parent):
        name, master, status, *pose = line.decode().split("\t")
        if status == "FIXED":
            x, y, orient, *clearance = pose
            reference_macros[name] = master, (int(x), int(y), orient, tuple(map(int, clearance)))
    assert len(reference_macros) == 631
    boxes = {}
    with seed.open() as stream:
        rows, total = read_rows(stream)
        for name, master, status, pose in candidates(stream):
            if status == "FIXED":
                assert reference_macros.pop(name.replace("\\", "")) == (master, pose)
                x, y, orient, halo = pose
                assert orient == "N"
                boxes[name] = x, y, *sizes[master], halo
    assert len(boxes) == 631 and not reference_macros
    validate_boxes(boxes, OUTLINE)
    reservations = [macro_box(box) for box in boxes.values()] + list(sections["BLOCKAGES"][1])
    for y, (_, grid) in rows.items():
        for box in reservations:
            mark_reserved(grid, y, 40000, PITCH, HEIGHT, box)

    counts = Counter()
    unplaced = Counter()
    movable = {}
    occupied = 0
    with seed.open() as stream:
        for line in stream:
            if COMPONENTS.fullmatch(line):
                break
        for name, master, status, pose in candidates(stream):
            counts[status] += 1
            if status == "FIXED":
                continue
            width, height = sizes[master]
            assert width % PITCH == 0 and height == HEIGHT
            width //= PITCH
            if status == "UNPLACED":
                unplaced[width] += 1
                continue
            x, y, orient, _ = pose
            side, grid = rows[y]
            assert orient in ({"N", "FN"} if side == "N" else {"FS", "S"}), name
            assert (x - 40000) % PITCH == 0, name
            first = (x - 40000) // PITCH
            end = first + width
            assert 0 <= first < end <= len(grid) and not any(grid[first:end]), name
            held = protected(name)
            grid[first:end] = (b"\x03" if held else b"\x02") * width
            if allow_release and not held:
                movable.setdefault(y, Counter())[width] += 1
            occupied += width
    assert counts.total() == total and counts["FIXED"] == 631
    free = Counter()
    for _, grid in rows.values():
        free.update(fragments(grid))
    available = sum(width * count for width, count in free.items())
    required = sum(width * count for width, count in unplaced.items())
    print(f"WIDENED_SEED_SITE_SUPPLY available={available} required={required} "
          f"largest_interval={max(free, default=0)} largest_unplaced_width={max(unplaced, default=0)}",
          flush=True)
    result = dict(component_counts=counts, existing_occupied_sites=occupied, available_sites=available,
                  sites_required_for_unplaced_cells=required)
    assert available >= required
    try:
        remaining = require_free_space(free.copy(), unplaced)
    except ValueError:
        if not allow_release:
            raise
        selected, cells, remaining = choose_released_rows(rows, unplaced, free, movable)
        result.update(reopened_rows=selected, released_standard_cells=cells)
    assert remaining == available - required
    result["unassigned_sites_after_packing"] = remaining
    return result


def main():
    assert __debug__ and Path("/.dockerenv").is_file()
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("seed", "parent", "library", "output"):
        parser.add_argument(name, type=Path)
    parser.add_argument("--relaxed-def", type=Path)
    args = parser.parse_args()
    seed = args.seed / "seed.def"
    receipt = read(args.seed / "receipt.json")
    assert digest(seed) == receipt["seed_def_sha256"]
    assert digest(args.parent) == receipt["source_def_sha256"]
    paths = sorted(args.library.glob("*.lef"))
    recorded = read(NATIVE)["evidence_sha256"]
    original_inputs = args.parent.parent.parent / "reload_inputs.json"
    assert digest(original_inputs) == recorded[str(original_inputs)]
    references = read(original_inputs)["checkpoint_fingerprint"]["files"]
    assert len(paths) == 7
    evidence = {str(path): digest(path) for path in paths}
    assert all(references[f"libs/lef/{Path(name).name}"]["sha256"] == value
               for name, value in evidence.items())
    sizes = dimensions(paths, 2000)
    result = verify_geometry(seed, args.parent, sizes, allow_release=args.relaxed_def is not None)
    assert {key: receipt["positions"][key] for key in result["component_counts"]} == result["component_counts"]
    if "reopened_rows" in result:
        count = release_placements(seed, args.relaxed_def, result["reopened_rows"])
        assert count == result["released_standard_cells"]
        revised = verify_geometry(args.relaxed_def, args.parent, sizes)
        assert revised["component_counts"]["PLACED"] == result["component_counts"]["PLACED"] - count
        assert revised["component_counts"]["UNPLACED"] == result["component_counts"]["UNPLACED"] + count
        assert revised["unassigned_sites_after_packing"] == result["unassigned_sites_after_packing"]
        result["relaxed_seed"] = str(args.relaxed_def)
        result["relaxed_seed_sha256"] = digest(args.relaxed_def)
        result["relaxed_geometry"] = revised
    result.update(state="widened_layout_seed_geometry_and_site_supply_verified",
                  candidate_sha256=receipt["candidate_sha256"],
                  seed_def_sha256=receipt["seed_def_sha256"],
                  evidence_sha256=evidence,
                  scope="Retained instances checked for legal coordinates. A width-packing certificate "
                        "establishes spare site capacity, without specifying final placement or wire delays.")
    with args.output.open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2)
        stream.write("\n")
    print(result["state"], result["available_sites"], result["sites_required_for_unplaced_cells"], flush=True)


if __name__ == "__main__":
    main()
