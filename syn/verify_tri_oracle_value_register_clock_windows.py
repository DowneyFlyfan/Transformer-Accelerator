"""Replay proposed coordinate-only edits against the exact native placement."""

from collections import defaultdict
from hashlib import file_digest
import json
from pathlib import Path
import re

from audit_tri_oracle_pad_ring_clearance import dimensions, overlap
from audit_tri_oracle_physical_io_budget import macro_boxes
from verify_tri_oracle_pad_cold_reload import boundary_sections, components
from verify_tri_oracle_value_register_clock_rows import ROOT, row_geometry
from plan_tri_oracle_value_register_clock_windows import (
    GEOMETRY, PROTECTED, TIMING, WORK, group_prefixes,
)


def digest(path):
    with Path(path).open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def intersects(cell, left, right):
    start, stop, _ = cell
    return min(stop, right) > max(start, left)


def validate(path):
    plan = json.loads(path.read_text())
    evidence = plan["evidence_sha256"]
    for name, expected in evidence.items():
        assert digest(Path(name)) == expected, name
    layout = Path(plan["layout"])
    assert plan["layout_sha256"] == evidence[str(layout)]
    geometry = json.loads(GEOMETRY.read_text())
    assert plan["cold_netlist_sha256"] == geometry["placement"]["control_buffered"]["cold_netlist_sha256"]
    assert plan["layout_sha256"] == geometry["evidence_sha256"][str(layout)]
    source = re.compile(r"/expanded_timing/critical_geometry\.json$")
    timing_geometry, = (Path(name) for name in evidence if source.search(name))
    assert json.loads(TIMING.read_text())["evidence_sha256"][str(timing_geometry)] == evidence[str(timing_geometry)]
    diagnosed = json.loads(timing_geometry.read_text())["per_array"]
    drivers = {driver.encode() for view in diagnosed.values()
               for node in view.values() for driver, _, _ in node["drivers"]}
    assert len(drivers) == plan["preserved_timing_driver_names"]

    sizes = dimensions([Path(name) for name in evidence if name.endswith(".lef")], 2000)
    width, height = sizes[plan["buffer"]]
    rows, regions = row_geometry(layout)
    array_prefixes = tuple(group_prefixes(layout).values())
    all_moves = {}
    windows = defaultdict(list)
    for name, region in plan["windows"].items():
        bounds = regions[name]
        for rec in region:
            y = rec["y"]
            first, last = rec["start"], rec["stop"]
            left, polarity, columns, pitch = rows[y]
            edges = (first, rec["buffer_x"], last)
            assert first <= rec["buffer_x"] < last and last-rec["buffer_x"] == width
            assert all((edge-left) % pitch == 0 and left <= edge <= left+columns*pitch
                       for edge in edges)
            assert bounds[0] <= first < last <= bounds[2] and bounds[1] <= y < y+height <= bounds[3]
            windows[y].append((first, last, rec))
            for entry in rec["moves"]:
                key = entry["name"].encode()
                assert key not in all_moves
                old, new, wide = entry["old_x"], entry["new_x"], entry["width"]
                assert first <= new < old and old+wide <= last and new+wide <= rec["buffer_x"]
                assert (old-new) % pitch == 0 and old-new <= width-pitch
                assert entry["orient"] in (("N", "FN") if polarity == "N" else ("FS", "S"))
                all_moves[key] = (entry, y)
    for group in windows.values():
        group.sort()
        assert all(a[1] <= b[0] for a, b in zip(group, group[1:]))

    fixed, actual_moves, resident_cells = {}, set(), defaultdict(list)
    for name, pose in components(layout):
        master, status, x, y, orient, _ = pose
        if status == "FIXED":
            fixed[name] = pose
            continue
        if y not in windows:
            continue
        wide, high = sizes[master]
        assert high == height
        old_span = (x, x+wide, name)
        now = x
        if name in all_moves:
            entry, planned_y = all_moves[name]
            assert (x, y, wide, master, orient) == (entry["old_x"], planned_y, entry["width"],
                                                   entry["master"], entry["orient"])
            leaf = name.rsplit(b"/", 1)[-1]
            assert not leaf.startswith(PROTECTED) and leaf not in drivers
            assert plan["array_moves_allowed"] or not name.startswith(array_prefixes)
            now = entry["new_x"]
            actual_moves.add(name)
        for left, right, rec in windows[y]:
            if intersects(old_span, left, right):
                assert left <= x < x+wide <= right
                resident_cells[(y, left)].append((now, now+wide, name))
                break
    assert actual_moves == all_moves.keys()
    assert len(fixed) == 631

    _, halos = macro_boxes(fixed, sizes)
    _, blockages = boundary_sections(layout)["BLOCKAGES"]
    for y, group in windows.items():
        for left, right, rec in group:
            assert not any(overlap((left, y, right, y+height), obstruction)
                           for obstruction in (*halos.values(), *blockages))
            residents = resident_cells[(y, left)]
            placed = sorted(residents + [(rec["buffer_x"], rec["buffer_x"]+width, b"future-buffer-slot")])
            assert placed[0][0] == left and placed[-1][1] == right
            assert all(a[1] == b[0] for a, b in zip(placed, placed[1:])), (y, left)

    summaries = {}
    for region, records in plan["windows"].items():
        generated = plan["summaries"][region]
        moves = [item for rec in records for item in rec["moves"]]
        measured = {
            "required": generated["required"], "slots": len(records),
            "moved_cells": len(moves), "affected_rows": len({rec["y"] for rec in records}),
            "moved_array_cells": sum(move["name"].encode().startswith(array_prefixes) for move in moves),
            "max_shift_um": max((item["old_x"]-item["new_x"] for item in moves), default=0)/2000,
        }
        assert measured == generated
        summaries[region] = measured
    return {
        "cold_netlist_sha256": plan["cold_netlist_sha256"],
        "plan_sha256": digest(path),
        "layout_sha256": plan["layout_sha256"],
        "regions": summaries,
        "verified_slot_count": sum(m["slots"] for m in summaries.values()),
        "preserved_timing_driver_names": len(drivers),
        "evidence_sha256": evidence,
    }


def main():
    checked = {}
    for mode in ("frozen", "bounded"):
        checked[mode] = validate(WORK / f"plan_{mode}.json")
    assert checked["bounded"]["cold_netlist_sha256"] == checked["frozen"]["cold_netlist_sha256"]
    assert checked["bounded"]["layout_sha256"] == checked["frozen"]["layout_sha256"]
    assert all(r["slots"] == r["required"] for r in checked["bounded"]["regions"].values())
    assert all(r["moved_array_cells"] == 0 for r in checked["frozen"]["regions"].values())
    assert len(checked["bounded"]["regions"]) == len(checked["frozen"]["regions"]) == 3
    return {
        "state": "wide_write_control_buffered_candidate_clock_slot_geometry_verified",
        "placement_proposals": checked,
        "verification_source_sha256": digest(Path(__file__)),
        "scope": ("Replay of coordinate-only proposed edits against the connected Innovus placement. "
                  "Every slot and move preserves memory halos, blockages, array-region fences, existing "
                  "control and prior buffers, and the drivers identified in the archived timing diagnosis. "
                  "The 153 CKBD8 locations cover the regional pin-capacitance lower bound. Native import, "
                  "clock wiring, max transition and skew, and timing closure remain unverified."),
    }


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT
    print(json.dumps(main(), indent=2, sort_keys=True))
