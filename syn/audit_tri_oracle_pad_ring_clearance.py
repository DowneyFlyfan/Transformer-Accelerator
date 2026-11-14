"""Count pad slots that clear the current fixed memory macro footprints."""

import argparse
from collections import Counter
from decimal import Decimal
import json
from pathlib import Path
import re

from audit_tri_oracle_placed_chip_boundary import PAD_ARCHIVE, digest, pad_views


ROOT = Path(__file__).resolve().parents[1]
POSE = re.compile(r"^- (\S+) (\S+) (?:\+ SOURCE \w+ )?\+ (PLACED|FIXED) \( (-?\d+) (-?\d+) \) (\w+)\b")
PAD_DEPTH_UM = Decimal(110)


def dimensions(files, units):
    result = {}
    for path in files:
        macros = re.finditer(r"(?ms)^MACRO (\w+)\n(.*?)^END \1\s*$", path.read_text())
        for macro in macros:
            name, body = macro.groups()
            origin, = re.findall(r"(?m)^\s+ORIGIN (\S+) (\S+)\s*;", body)
            size, = re.findall(r"(?m)^\s+SIZE (\S+) BY (\S+)\s*;", body)
            assert all(Decimal(value) == 0 for value in origin)
            scaled = [Decimal(value) * units for value in size]
            assert all(value > 0 and value == int(value) for value in scaled)
            assert name not in result
            result[name] = tuple(map(int, scaled))
    return result


def get_units(stream):
    for line in stream:
        if match := re.fullmatch(r"UNITS DISTANCE MICRONS (\d+) ;\n", line):
            return int(match[1])
    raise ValueError("No coordinate units")


def overlap(left, right):
    return (max(left[0], right[0]) < min(left[2], right[2]) and
            max(left[1], right[1]) < min(left[3], right[3]))


def contains(outer, inner):
    return outer[0] <= inner[0] < inner[2] <= outer[2] and outer[1] <= inner[1] < inner[3] <= outer[3]


def inventory(design, libraries, depth):
    fixed = {}
    displaced = Counter()
    read = 0
    with design.open() as stream:
        units = get_units(stream)
        sizes = dimensions(libraries, units)
        outline = None
        for line in stream:
            if match := re.fullmatch(r"DIEAREA \( (\d+) (\d+) \) \( (\d+) (\d+) \) ;\n", line):
                outline = tuple(map(int, match.groups()))
            if match := re.fullmatch(r"COMPONENTS (\d+) ;\n", line):
                count = int(match[1])
                break
        else:
            raise ValueError("Missing component header")
        assert outline == (0, 0, 3600 * units, 3600 * units)
        margin = int(depth * units)
        interior = (margin, margin, outline[2] - margin, outline[3] - margin)
        for line in stream:
            if line == "END COMPONENTS\n":
                break
            if not line.startswith("- "):
                continue
            match = POSE.match(line)
            assert match, line
            name, master, status, x, y, orient = match.groups()
            assert orient in {"N", "S", "FN", "FS", "W", "E", "FW", "FE"}, orient
            width, height = sizes[master]
            if orient in {"W", "E", "FW", "FE"}:
                width, height = height, width
            x, y = int(x), int(y)
            box = x, y, x + width, y + height
            assert contains(outline, box), (name, box)
            if status == "FIXED":
                assert master.startswith(("TS5N28", "TS6N28")) and name not in fixed
                fixed[name] = box
            if not contains(interior, box):
                displaced[status] += 1
            read += 1
        else:
            raise ValueError("Missing end of components")
    assert count == read == 3765868 and len(fixed) == 631
    return units, outline, fixed, displaced


def screen(units, outline, fixed, pad_width, corner_width, depth):
    _, _, right, top = outline
    slot = int(pad_width * units)
    corner = int(corner_width * units)
    inset = int(depth * units)
    edges = {
        "left": [(0, at, inset, at + slot) for at in range(corner, top - corner - slot + 1, slot)],
        "right": [(right - inset, at, right, at + slot) for at in range(corner, top - corner - slot + 1, slot)],
        "bottom": [(at, 0, at + slot, inset) for at in range(corner, right - corner - slot + 1, slot)],
        "top": [(at, top - inset, at + slot, top) for at in range(corner, right - corner - slot + 1, slot)],
    }
    result = {}
    for name, slots in edges.items():
        conflicts = [tuple(master for master, box in fixed.items() if overlap(rect, box)) for rect in slots]
        blocked = sum(bool(matches) for matches in conflicts)
        result[name] = dict(slots=len(slots), fixed_blocked=blocked, clear_of_fixed=len(slots) - blocked,
                            conflicting_fixed_macros=len({master for matches in conflicts for master in matches}))
    # Allow each pad to slide along a continuous edge. The sum of complete
    # pad widths in each unobstructed interval is the best geometric count
    # without moving the fixed macros, before technology spacing and halos.
    strips = {
        "left": ((0, corner, inset, top - corner), 1),
        "right": ((right - inset, corner, right, top - corner), 1),
        "bottom": ((corner, 0, right - corner, inset), 0),
        "top": ((corner, top - inset, right - corner, top), 0),
    }
    for name, (strip, axis) in strips.items():
        cursor, end = strip[axis], strip[axis + 2]
        available = 0
        forbidden = sorted((max(cursor, box[axis]), min(end, box[axis + 2]))
                           for box in fixed.values() if overlap(strip, box))
        for start, stop in forbidden:
            available += max(0, start - cursor) // slot
            cursor = max(cursor, stop)
        available += (end - cursor) // slot
        assert result[name]["clear_of_fixed"] <= available <= result[name]["slots"]
        result[name]["sliding_slots_clear_of_fixed"] = available
    return result


def run(design, lib_directory, pad_archive):
    record_path = ROOT / "records/tri_oracle_grouped_active_boundary.json"
    record = json.loads(record_path.read_text())
    assert record["state"] == "grouped_active_placement_boundary_verified"
    assert record["placement_definition_sha256"] == digest(design)
    libraries = sorted(lib_directory.glob("*.lef"))
    assert len(libraries) == 7
    _, _, width, corner, abstract = pad_views(pad_archive)
    assert abstract == record["pad_abstract_sha256"]
    assert width == Decimal(record["minimum_signal_pad_micrometers"])
    assert corner == Decimal(record["minimum_corner_cell_micrometers"])
    units, outline, fixed, displaced = inventory(design, libraries, PAD_DEPTH_UM)
    edges = screen(units, outline, fixed, width, corner, PAD_DEPTH_UM)
    clear = sum(value["clear_of_fixed"] for value in edges.values())
    sliding = sum(value["sliding_slots_clear_of_fixed"] for value in edges.values())
    assert sum(value["slots"] for value in edges.values()) == record["single_row_signal_pad_limit"]
    receive = record["modeled_payload_rate"]["bounds_by_bits_per_pad_per_cycle"]["2"]["minimum_payload_pads"]
    return dict(
        state="placed_pad_ring_clearance_screened",
        candidate_netlist_sha256=record["candidate_netlist_sha256"],
        full_perimeter_component_clearance_micrometers=str(PAD_DEPTH_UM),
        components_intersecting_full_perimeter_strip=dict(displaced),
        no_macro_relocation_slots_clear_of_fixed=clear,
        optimistic_sliding_slots_clear_of_fixed=sliding,
        ideal_two_bit_payload_pads=receive,
        clear_slots_after_ideal_payload=clear - receive,
        optimistic_sliding_slots_after_ideal_payload=sliding - receive,
        no_macro_relocation_slots_by_edge=edges,
        evidence_sha256={str(path.relative_to(ROOT)): digest(path) for path in
                         (record_path, design, Path(__file__).resolve(), *libraries)},
        scope="Regular slots and optimally slid 20-micrometer-wide, 110-micrometer-deep pad bodies after corner cells. "
              "A pad slot can still require local standard-cell relocation. The comparison excludes macro halos, "
              "power and ground allocation, package wiring and pad spacing rules.",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("design", type=lambda path: Path(path).absolute())
    parser.add_argument("libraries", type=lambda path: Path(path).absolute())
    parser.add_argument("--pad-archive", type=Path, default=PAD_ARCHIVE)
    args = parser.parse_args()
    print(json.dumps(run(args.design, args.libraries, args.pad_archive), sort_keys=True, indent=2))
