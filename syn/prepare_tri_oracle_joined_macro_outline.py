"""Find room for the joined predictor macros on the verified chip outline."""

import argparse
from collections import Counter
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
import json
from pathlib import Path
import re

from prepare_tri_oracle_joined_decoder_candidate import ROOT, read
from prepare_tri_oracle_parallel_chip_synthesis import pin, verify
from prepare_tri_oracle_parallel_macro_seed import PHYSICAL, check_geometry, footprint


BASE = PHYSICAL / "shared_memory_layer_boundary/physical_inputs/macro_seed.json"
VIEWS = PHYSICAL / "wac_budgeted_parent_boundary/linked_tsmc_physical_views.json"
SMALL = "TS5N28HPCPSVTA32X128M2FW"
LARGE = "TS5N28HPCPSVTA512X64M4F"
PREVIOUS = "layer.layer.feedforward.predictor.replay_table."


def positions(seed, sizes, removed, masters, grid):
    die_x, die_y = map(Decimal, seed["die_um"])
    halo = Decimal(seed["halo_um"])
    margin = Decimal(seed["core_margin_um"])
    gap = Decimal(5)
    height, = {sizes[master][1] for master in masters}
    width = sum(sizes[master][0] + 2 * halo for master in masters) + gap * (len(masters) - 1)
    anchor_x = sum(Decimal(pose["x_um"]) + sizes[pose["master"]][0] / 2 for pose in removed) / len(removed)
    anchor_y = sum(Decimal(pose["y_um"]) for pose in removed) / len(removed)

    boxes = []
    for pose in seed["placements"].values():
        x, y = map(Decimal, (pose["x_um"], pose["y_um"]))
        w, h = sizes[pose["master"]]
        boxes.append((x - halo, y - halo, x + w + halo, y + h + halo))

    def snap(value, rounding):
        return (value / grid).to_integral_value(rounding=rounding) * grid

    top = die_y - margin - height - halo
    possible_y = {anchor_y, margin + halo, top}
    for _, lower, _, upper in boxes:
        possible_y.add(snap(lower - height - halo, ROUND_FLOOR))
        possible_y.add(snap(upper + halo, ROUND_CEILING))
    candidates = []
    for y in sorted(possible_y):
        if not margin + halo <= y <= top:
            continue
        blocked = sorted((x1, x2) for x1, y1, x2, y2 in boxes if y - halo < y2 and y1 < y + height + halo)
        left = margin
        for start, end in (*blocked, (die_x - margin, die_x - margin)):
            lower = snap(left, ROUND_CEILING)
            upper = snap(start - width, ROUND_FLOOR)
            if lower <= upper:
                x = min(upper, max(lower, snap(anchor_x - width / 2, ROUND_HALF_UP)))
                displacement = abs(x + width / 2 - anchor_x) + abs(y - anchor_y)
                candidates.append((displacement, x, y))
            left = max(left, end)
    _, x, y = min(candidates)
    row = []
    for master in masters:
        row.append({"master": master, "x_um": str(x + halo), "y_um": str(y), "orientation": "r0"})
        x += sizes[master][0] + 2 * halo + gap
    return row


def run(output):
    records = ROOT / "records"
    baseline = records / "wac_parallel_chip_macro_outline_preflight_result.json"
    census = records / "wac_dual_lane_packed_sign_memory_result.json"
    proof, memory = read(baseline), read(census)
    assert proof["state"] == "parallel_chip_macro_outline_preflight"
    assert memory["state"] == "packed_sign_source_chip_compiled_memory_census_verified"
    pins = {}
    for path in (baseline, census, Path(__file__).resolve()):
        pin(pins, path)
    for path in (BASE, VIEWS, records / "paper_result_targets.json"):
        pin(pins, path, proof["evidence_sha256"][str(path.relative_to(ROOT))])
    seed, views = read(BASE), read(VIEWS)
    tech, _, *macros = views["physical_abstracts"]
    for name in (tech, *macros):
        pin(pins, ROOT / name, proof["evidence_sha256"][name])
    grid, = re.findall(r"(?m)^\s*MANUFACTURINGGRID\s+(\S+)\s*;", (ROOT / tech).read_text())
    sizes = dict(footprint((ROOT / name).read_text()) for name in macros)
    target = read(records / "paper_result_targets.json")["silicon"]
    outline = tuple(1000 * Decimal(str(value)) for value in target["die_dimensions_mm"])
    grid = Decimal(grid)
    seed["placements"] = {"layer." + path: pose for path, pose in seed["placements"].items()}
    original = check_geometry(seed, sizes, outline, grid)
    assert all(original[key] == proof[key] for key in original)
    paths = [path for path in seed["placements"] if path.startswith(PREVIOUS)]
    removed = [seed["placements"].pop(path) for path in paths]
    assert len(removed) == 2 and all(pose["master"] == LARGE for pose in removed)
    preserved = seed["placements"].copy()
    slots = ("metadata_lower", *(f"metadata_upper_{i}" for i in range(5)), *(f"sign_cache_{i}" for i in range(4)))
    replacement = dict(zip(slots, positions(seed, sizes, removed, [LARGE] + [SMALL] * 9, grid), strict=True))
    seed["placements"].update(replacement)
    counts = Counter(pose["master"] for pose in seed["placements"].values())
    assert counts == memory["compiled_by_master"] and counts.total() == 631 and len(preserved) == 621
    updated = check_geometry(seed, sizes, outline, grid)
    verify(pins)
    result = {"state": "joined_predictor_macro_outline_geometry_verified", "die_um": seed["die_um"],
              "preserved_macro_locations": len(preserved), "memory_macros": counts.total(),
              "halo_um": seed["halo_um"], "manufacturing_grid_um": str(grid), "predictor_slots": replacement,
              "original_outline": original, "updated_outline": updated,
              "scope": "Static library footprints, nonoverlapping halos and die bounds. Candidate instance binding and native placement remain pending.",
              "input_sha256": pins}
    with output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(result["state"], counts.total(), updated, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=lambda value: Path(value).resolve())
    run(parser.parse_args().output)
