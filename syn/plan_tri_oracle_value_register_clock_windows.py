"""Find disjoint legal row windows for the control-buffered clock load floor."""
import argparse
from bisect import bisect_left, bisect_right, insort
from collections import Counter, defaultdict
from hashlib import file_digest
from mmap import ACCESS_READ, mmap
import json
from pathlib import Path
import re

import numpy as np

from audit_tri_oracle_pad_ring_clearance import dimensions
from audit_tri_oracle_physical_io_budget import macro_boxes
from verify_tri_oracle_pad_cold_reload import boundary_sections, components
from verify_tri_oracle_value_register_clock_rows import ROOT, row_geometry, slice_for

WORK = ROOT / ".cache/value_register_clock_windows"
LOADS = Path("records/tri_oracle_value_register_clock_loads.json")
GEOMETRY = Path("records/tri_oracle_value_register_clock_rows.json")
TIMING = Path("records/tri_oracle_resized_chip_expanded_control_placement_and_timing.json")
BUFFER = "CKBD8"
PROTECTED = (b"TRI_BOUNDED_RST_", b"TRI_BOUNDED_PROB_", b"TRI_BOUNDED_MAP_", b"TRI_ARRAY_CTL_")
GROUP = re.compile(rb"(?m)^- (tri_array_region_\d+)\n\s+(\S+/)\*\n\s*\+ REGION \1 ;$")
INPUT_SUFFIX = "/expanded_connected/native/layout.def"
FREE, MOVABLE, FIXED = 0, 1, 2


def sha(path):
    with Path(path).open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def exact_inputs():
    geometry, loads = [json.loads(path.read_text()) for path in (GEOMETRY, LOADS)]
    hashes = geometry["evidence_sha256"]
    layout, = (Path(path) for path in hashes if path.endswith(INPUT_SUFFIX))
    assert sha(layout) == hashes[str(layout)] == loads["evidence_sha256"][str(layout)]
    lefs = [Path(name) for name in hashes if name.endswith(".lef")]
    assert len(lefs) == 7 and all(sha(path) == hashes[str(path)] for path in lefs)
    scenario = loads["candidate"]["control_buffered"]
    assert scenario["cold_netlist_sha256"] == geometry["placement"]["control_buffered"]["cold_netlist_sha256"]
    requested = {
        region: d["single_master_scenarios"][BUFFER]["minimum_local_leaf_outputs"]
        for region, d in scenario["regions"].items()
        if d["single_master_scenarios"][BUFFER]["shortfall_before_wire_load"]
    }
    return layout, lefs, scenario["cold_netlist_sha256"], requested


def group_prefixes(layout):
    with layout.open("rb") as handle, mmap(handle.fileno(), 0, access=ACCESS_READ) as raw:
        start = raw.find(b"\nGROUPS 20 ;\n")
        stop = raw.find(b"\nEND GROUPS\n", start)
        assert 0 < start < stop
        entries = GROUP.findall(raw, start, stop)
    assert len(entries) == len({item[1] for item in entries}) == 20
    return dict(entries)


def moves_blocked(name, prefixes, timing_drivers):
    leaf = name.rsplit(b"/", 1)[-1]
    return leaf.startswith(PROTECTED) or leaf in timing_drivers or name.startswith(prefixes)


def select_windows(grid, limits, requested, sites):
    rows = defaultdict(list)
    selected = {}
    for name, boxes in limits.items():
        lo, first, hi, last = boxes
        candidates = []
        for row in range(first, last):
            view = grid[row, lo:hi]
            segment_ends = np.flatnonzero(np.diff(view != FIXED, prepend=False, append=False))
            for a, b in zip(segment_ends[::2], segment_ends[1::2], strict=True):
                empty = np.flatnonzero(view[a:b] == FREE) + lo + a
                ends = empty[sites-1:] + 1
                starts = empty[:len(ends)]
                candidates.extend((int(r-l), row, int(l), int(r))
                                  for l, r in zip(starts, ends, strict=True))
        group = []
        occupied = defaultdict(list)
        for _, row, start, stop in sorted(candidates):
            existing = occupied[row]
            pos = bisect_left(existing, (start, stop))
            if (pos and existing[pos-1][1] > start) or (pos < len(existing) and existing[pos][0] < stop):
                continue
            insort(existing, (start, stop))
            window = {"row": row, "start": start, "stop": stop, "cells": []}
            group.append(window)
            rows[row].append(window)
            if len(group) == requested[name]:
                break
        print(name, "selected", len(group), "required", requested[name],
              "eligible windows", len(candidates), flush=True)
        selected[name] = group
    for row, group in rows.items():
        group.sort(key=lambda w: w["start"])
        assert all(a["stop"] <= b["start"] for a, b in zip(group, group[1:]))
    return rows, selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-array-moves", action="store_true")
    args = parser.parse_args()
    layout, lefs, candidate, requested = exact_inputs()
    rows, regions = row_geometry(layout)
    sizes = dimensions(lefs, 2000)
    levels = sorted(rows)
    left, _, columns, pitch = rows[levels[0]]
    bottom, height = levels[0], levels[1] - levels[0]
    width, bh = sizes[BUFFER + "BWP12T40P140"]
    assert width % pitch == 0 and bh == height
    buffer_sites = width // pitch
    fences = group_prefixes(layout)
    assert {name.decode() for name in fences} == regions.keys()
    prefixes = tuple(fences.values())
    timing = json.loads(TIMING.read_text())
    path, = (Path(name) for name in timing["evidence_sha256"]
             if name.endswith("/expanded_timing/critical_geometry.json"))
    assert sha(path) == timing["evidence_sha256"][str(path)]
    critical = json.loads(path.read_text())["per_array"]
    assert len(critical) == len(fences)
    timing_drivers = {driver.encode() for array in critical.values()
                      for node in array.values() for driver, _, _ in node["drivers"]}
    assert timing_drivers
    frozen_prefixes = () if args.allow_array_moves else prefixes
    bounds = {name: slice_for(regions[name], left, bottom, pitch, height, columns, len(rows))
              for name in requested}

    fixed = {name: rec for name, rec in components(layout) if rec[1] == "FIXED"}
    assert len(fixed) == 631
    _, halos = macro_boxes(fixed, sizes)
    _, blocks = boundary_sections(layout)["BLOCKAGES"]
    grid = np.zeros((len(rows), columns), dtype=np.uint8)
    for box in (*halos.values(), *blocks):
        l, a, r, b = slice_for(box, left, bottom, pitch, height, columns, len(rows))
        if l < r and a < b:
            grid[a:b, l:r] = FIXED

    placed = Counter()
    for name, rec in components(layout):
        kind, status, x, y, orient, _ = rec
        if status == "FIXED":
            continue
        assert status == "PLACED" and y in rows
        wide, high = sizes[kind]
        col, dx = divmod(x-left, pitch)
        sites, dw = divmod(wide, pitch)
        row = (y-bottom)//height
        assert dx == dw == 0 and high == height
        assert 0 <= col < col+sites <= columns and not grid[row,col:col+sites].any()
        is_anchor = name.rsplit(b"/", 1)[-1].startswith(PROTECTED)
        is_array = name.startswith(prefixes)
        placed.update(protected=int(is_anchor), arrays=int(is_array), total=1)
        grid[row,col:col+sites] = FIXED if moves_blocked(name, frozen_prefixes, timing_drivers) else MOVABLE
    assert placed["protected"] == 2869 + 18800
    assert placed["arrays"] == 1091600 + 18800
    assert placed["total"] == 3887458 - len(fixed)
    by_row, selected = select_windows(grid, bounds, requested, buffer_sites)
    positions = {row: [w["start"] for w in group] for row, group in by_row.items()}
    for name, rec in components(layout):
        kind, status, x, y, orient, _ = rec
        row = (y-bottom)//height
        group = by_row.get(row)
        if status != "PLACED" or not group:
            continue
        col = (x-left)//pitch
        size = sizes[kind][0]//pitch
        first = max(0, bisect_right(positions[row], col)-1)
        last = bisect_left(positions[row], col+size)
        for window in group[first:last]:
            if window["stop"] <= col:
                continue
            assert not moves_blocked(name, frozen_prefixes, timing_drivers)
            assert window["start"] <= col < col+size <= window["stop"]
            window["cells"].append((col, size, name.decode(), kind, orient))

    detail, summaries, moved = {}, {}, set()
    for region, group in selected.items():
        records = []
        for window in group:
            row, start, stop = map(window.__getitem__, ("row", "start", "stop"))
            before = grid[row,start:stop]
            assert not (before == FIXED).any()
            expected = np.zeros(stop-start, dtype=np.uint8)
            cursor = start
            changes = []
            for col, sites, name, master, orient in sorted(window["cells"]):
                assert col >= cursor and not expected[col-start:col-start+sites].any()
                expected[col-start:col-start+sites] = MOVABLE
                if col > cursor:
                    assert name not in moved
                    moved.add(name)
                    changes.append(dict(name=name, master=master, orient=orient, old_x=left+col*pitch,
                                        new_x=left+cursor*pitch, width=sites*pitch))
                cursor += sites
            assert np.array_equal(expected, before) and stop-cursor == buffer_sites
            records.append(dict(y=bottom+row*height, buffer_x=left+cursor*pitch,
                                start=left+start*pitch, stop=left+stop*pitch, moves=changes))
        summaries[region] = dict(
            required=requested[region], slots=len(records),
            moved_cells=sum(len(rec["moves"]) for rec in records),
            moved_array_cells=sum(move["name"].encode().startswith(prefixes)
                                  for rec in records for move in rec["moves"]),
            affected_rows=len({rec["y"] for rec in records}),
            max_shift_um=max((move["old_x"]-move["new_x"] for rec in records
                              for move in rec["moves"]), default=0)/2000,
        )
        detail[region] = records
    assert sum(r["moved_cells"] for r in summaries.values()) == len(moved)
    result = dict(cold_netlist_sha256=candidate, buffer=BUFFER + "BWP12T40P140",
                  layout=str(layout), layout_sha256=sha(layout), summaries=summaries, windows=detail,
                  array_moves_allowed=args.allow_array_moves, preserved_timing_driver_names=len(timing_drivers),
                  evidence_sha256={str(p.relative_to(ROOT) if p.is_absolute() else p): sha(p)
                                   for p in (LOADS, GEOMETRY, TIMING, path, layout, Path(__file__), *lefs)})
    suffix = "bounded" if args.allow_array_moves else "frozen"
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK/f"plan_{suffix}.json").write_text(json.dumps(result, indent=2, sort_keys=True)+"\n")
    print(summaries, flush=True)


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT
    main()
