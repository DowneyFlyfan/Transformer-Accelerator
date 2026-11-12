"""Count usable full standard-cell sites after snapping macro halos to rows."""

import argparse
from collections import defaultdict
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from itertools import combinations
import json
from pathlib import Path
import re

from prepare_tri_oracle_joined_decoder_candidate import ROOT, read
from prepare_tri_oracle_joined_macro_outline import BASE, PREVIOUS, VIEWS, check_geometry, footprint
from prepare_tri_oracle_parallel_chip_synthesis import pin, verify


def whole_sites(placements, sizes, die, margin, halo, step):
    def floor(value):
        return int(value.to_integral_value(rounding=ROUND_FLOOR))

    def ceil(value):
        return int(value.to_integral_value(rounding=ROUND_CEILING))

    columns, rows = [floor((extent - 2 * margin) / pitch) for extent, pitch in zip(die, step, strict=True)]
    assert columns > 0 and rows > 0
    blocked = {}
    begin, end = defaultdict(list), defaultdict(list)
    for name, pose in placements.items():
        x, y = map(Decimal, (pose["x_um"], pose["y_um"]))
        width, height = sizes[pose["master"]]
        x1 = max(0, floor((x - halo - margin) / step[0]))
        y1 = max(0, floor((y - halo - margin) / step[1]))
        x2 = min(columns, ceil((x + width + halo - margin) / step[0]))
        y2 = min(rows, ceil((y + height + halo - margin) / step[1]))
        assert x1 < x2 and y1 < y2
        blocked[name] = x1, y1, x2, y2
        begin[y1].append(name)
        end[y2].append(name)

    active = set()
    occupied = 0
    boundaries = sorted(begin.keys() | end.keys() | {rows})
    for row, next_row in zip(boundaries, boundaries[1:]):
        active.difference_update(end[row])
        active.update(begin[row])
        occupied_columns = 0
        right = 0
        for left, stop in sorted((blocked[name][0], blocked[name][2]) for name in active):
            occupied_columns += max(0, stop - max(left, right))
            right = max(right, stop)
        occupied += occupied_columns * (next_row - row)
    overlaps = [(left, right) for (left, a), (right, b) in combinations(blocked.items(), 2)
                if max(a[0], b[0]) < min(a[2], b[2]) and max(a[1], b[1]) < min(a[3], b[3])]
    assert 0 < occupied < columns * rows
    return columns, rows, occupied, overlaps


def check_site_clearance(placements, replacement, sizes, halo, step):
    boxes = {}
    for name, pose in placements.items():
        x, y = map(Decimal, (pose["x_um"], pose["y_um"]))
        width, height = sizes[pose["master"]]
        boxes[name] = x - halo, y - halo, x + width + halo, y + height + halo
    for left in replacement:
        a = boxes[left]
        for right, b in boxes.items():
            if left != right:
                horizontal = max(a[0] - b[2], b[0] - a[2])
                vertical = max(a[1] - b[3], b[1] - a[3])
                assert horizontal >= step[0] or vertical >= step[1], (left, right)


def run(output):
    outline = ROOT / "records/wac_joined_predictor_macro_outline_result.json"
    proof, base, views = map(read, (outline, BASE, VIEWS))
    assert proof["state"] == "joined_predictor_macro_outline_geometry_verified"
    assert views["placement_site"] == "core12T"
    pins = proof["input_sha256"].copy()
    for path in (outline, Path(__file__).resolve()):
        pin(pins, path)
    _, standard, *lefs = views["physical_abstracts"]
    pin(pins, ROOT / standard, views["evidence_sha256"][standard])
    sizes = dict(footprint((ROOT / name).read_text()) for name in lefs)
    site, = re.findall(r"(?ms)^SITE core12T\n(.*?)^END core12T$", (ROOT / standard).read_text())
    dims, = re.findall(r"(?m)^\s*SIZE (\S+) BY (\S+)\s*;", site)
    step = tuple(map(Decimal, dims))
    die = tuple(map(Decimal, proof["die_um"]))
    margin, halo = map(Decimal, (base["core_margin_um"], base["halo_um"]))
    old = {"layer." + path: pose for path, pose in base["placements"].items()}
    joined = {name: pose for name, pose in old.items() if not name.startswith(PREVIOUS)} | proof["predictor_slots"]
    assert len(old) == 623 and len(joined) == 631
    adjusted = {name: {**pose, "x_um": str(Decimal(pose["x_um"]) - step[0]),
                       "y_um": str(Decimal(pose["y_um"]) - step[1])}
                for name, pose in proof["predictor_slots"].items()}
    adjusted_outline = joined | adjusted
    grid = Decimal(proof["manufacturing_grid_um"])
    assert check_geometry({**base, "placements": adjusted_outline}, sizes, die, grid) == proof["updated_outline"]
    check_site_clearance(adjusted_outline, adjusted, sizes, halo, step)
    results = {}
    for name, placements in (("earlier_linked_outline", old), ("packed_predictor_outline", joined),
                             ("packed_predictor_outline_with_site_clearance", adjusted_outline)):
        columns, rows, blocked, overlaps = whole_sites(placements, sizes, die, margin, halo, step)
        available = columns * rows - blocked
        results[name] = {"columns": columns, "rows": rows, "blocked_sites": blocked, "available_sites": available,
                         "available_site_area_mm2": str(available * step[0] * step[1] / 10**6),
                         "pairs_sharing_a_blocked_site": len(overlaps),
                         "predictor_halo_sharing_pairs": sum(left in proof["predictor_slots"] or right in proof["predictor_slots"]
                                                             for left, right in overlaps)}
    assert results["packed_predictor_outline_with_site_clearance"]["predictor_halo_sharing_pairs"] == 0
    verify(pins)
    report = {"state": "tri_oracle_floorplan_site_capacity_checked", "site_pitch_um": list(map(str, step)),
              "modeled_site_origin_um": [str(margin), str(margin)], "results": results,
              "adjusted_predictor_slots": adjusted,
              "scope": "Full-site capacity for a core-margin-anchored row grid. Actual Innovus row origins and blockages require native verification.",
              "input_sha256": pins}
    with output.open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(report["state"], results, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    run(parser.parse_args().output)
