"""Construct and check local row moves that expose one buffer slot per crowded region."""

from collections import defaultdict
from dataclasses import dataclass
import json
from pathlib import Path
import re

import numpy as np

from audit_tri_oracle_pad_ring_clearance import dimensions
from plan_tri_oracle_booth_pin_load_repair import empty_grid
from verify_tri_oracle_booth_buffered_repair_slots import BASELINE, CAPACITY, REPAIR, occupy_repair_buffers
from verify_tri_oracle_booth_buffered_row_capacity import MODELS, PLACEMENT, ROOT, digest
from verify_tri_oracle_pad_cold_reload import components


SLOTS = Path("records/tri_oracle_corrected_booth_buffered_repair_slots.json")
CORRIDOR = re.compile(rb"[^\x02]+")


@dataclass(frozen=True)
class Window:
    row: int
    start: int
    stop: int

    @property
    def span(self):
        return self.stop - self.start


def shortest_window(grid, bounds, origin_x, origin_y, pitch, height, width):
    x1, y1, x2, y2 = bounds
    col0, col1 = (x1 - origin_x) // pitch, (x2 - origin_x) // pitch
    row0, row1 = (y1 - origin_y) // height, (y2 - origin_y) // height
    best = None
    for row in range(row0, row1):
        line = np.frombuffer(grid[row], dtype=np.uint8)
        for corridor in CORRIDOR.finditer(grid[row], col0, col1):
            start, stop = corridor.span()
            free = np.flatnonzero(line[start:stop] == 0) + start
            if len(free) < width:
                continue
            spans = free[width - 1:] - free[:len(free) - width + 1]
            index = int(np.argmin(spans))
            candidate = Window(row, int(free[index]), int(free[index + width - 1] + 1))
            if best is None or candidate.span < best.span:
                best = candidate
    if best is None:
        raise ValueError("No row corridor has enough space to form one buffer slot")
    return best


def compact(cells, window, row, origin_x, pitch, width):
    """Try stable left and right compaction on whole cells within the selected window."""
    contents = sorted(cells, key=lambda cell: cell[1])
    assert contents and row[window.start] == row[window.stop - 1] == 0
    restored = bytearray(window.span)
    geometry = {}
    for name, column, sites in contents:
        offset = column - window.start
        assert offset >= 0 and offset + sites <= len(restored)
        assert not any(restored[offset:offset + sites])
        restored[offset:offset + sites] = b"\x01" * sites
        geometry[name] = (column, sites)
    assert restored == row[window.start:window.stop] and restored.count(0) == width

    def move_cells(direction):
        right = direction == "right"
        cursor = window.stop if right else window.start
        moves = []
        for name, column, sites in reversed(contents) if right else contents:
            new_column = cursor - sites if right else cursor
            cursor = new_column if right else new_column + sites
            if new_column != column:
                moves.append((name, column, new_column, sites))
        return moves, (window.start if right else window.stop - width)

    def move_cost(solution):
        moves, _ = solution
        return sum(abs(after - before) for _, before, after, _ in moves)

    moves, buffer_start = min((move_cells("left"), move_cells("right")), key=move_cost)
    for name, _, after, sites in moves:
        geometry[name] = after, sites
    packed = bytearray(window.span)
    for column, sites in geometry.values():
        offset = column - window.start
        assert offset >= 0 and offset + sites <= len(packed) and not any(packed[offset:offset + sites])
        packed[offset:offset + sites] = b"\x01" * sites
    start = buffer_start - window.start
    assert packed.count(0) == width and packed[start:start + width] == bytearray(width)
    return {
        "window_sites": window.span,
        "buffer_start_x": origin_x + pitch * buffer_start,
        "moved_cells": len(moves),
        "maximum_cell_shift_sites": max(abs(after - before) for _, before, after, _ in moves),
        "total_cell_shift_sites": move_cost((moves, buffer_start)),
    }, [
        {"instance": name.decode(), "old_x": origin_x + before * pitch, "new_x": origin_x + after * pitch}
        for name, before, after, _ in moves
    ]


def verify(plan_path):
    evidence = {}

    def pin(path, expected=None):
        actual = digest(path)
        assert expected is None or expected == actual, path
        evidence[str(path)] = actual
        return path

    before, placed, models, repair, capacity, slots = (
        json.loads(pin(path).read_text()) for path in (BASELINE, PLACEMENT, MODELS, REPAIR, CAPACITY, SLOTS)
    )
    database = Path(placed["database"])
    fingerprints = [item["database_fingerprint_sha256"] for item in (placed, models, capacity, slots)]
    assert len(set(fingerprints)) == 1
    source = Path(before["database"]).parents[1] / "cold/layout.def"
    final = database.parents[1] / "cold/layout.def"
    pin(source, before["evidence_sha256"][str(source)])
    pin(final, placed["evidence_sha256"][str(final)])
    assert slots["evidence_sha256"][str(final)] == capacity["evidence_sha256"][str(final)] == evidence[str(final)]
    libraries = sorted((database / "libs/lef").glob("*.lef"))
    assert len(libraries) == 7
    for library in libraries:
        pin(library, models["evidence_sha256"][str(library)])
    sizes = dimensions(libraries, 2000)
    grid, _, levels, left, pitch, height, units, regions, _ = empty_grid(source, sizes, before["geometry"])
    added = {
        name.replace(b"\\", b""): pose for name, pose in components(final)
        if name.rsplit(b"/", 1)[-1].startswith(b"tri_load_repair_")
    }
    assert len(added) == repair["added_buffers"] and {pose[0] for pose in added.values()} == {slots["buffer_master"]}
    delta = occupy_repair_buffers(grid, added, left, levels[0], pitch, height, sizes)
    old_hash = int(before["geometry"]["pose_sha256_sum"], 16)
    assert (old_hash + delta) % (1 << 256) == int(placed["geometry"]["pose_sha256_sum"], 16)

    width = slots["buffer_width_sites"]
    windows_by_row = defaultdict(list)
    windows = {}
    for region in slots["regions_without_buffer_slots"]:
        window = shortest_window(grid, regions[region], left, levels[0], pitch, height, width)
        windows[region] = window
        windows_by_row[levels[window.row]].append((region, window))
    assert len(windows) == 7 and width == sizes[slots["buffer_master"]][0] // pitch
    candidates = defaultdict(list)
    for name, (master, status, x, y, _, _) in components(final):
        if status != "PLACED" or y not in windows_by_row:
            continue
        column = (x - left) // pitch
        sites = sizes[master][0] // pitch
        for region, window in windows_by_row[y]:
            if column + sites > window.start and column < window.stop:
                assert window.start <= column and column + sites <= window.stop
                candidates[region].append((name, column, sites))

    results, moves_by_region = {}, {}
    for region, window in windows.items():
        results[region], moves_by_region[region] = compact(
            candidates[region], window, grid[window.row], left, pitch, width,
        )
        results[region]["row_y"] = levels[window.row]
        assert results[region]["maximum_cell_shift_sites"] <= width
    plan_path.write_text(json.dumps(moves_by_region, indent=2, sort_keys=True) + "\n")
    pin(plan_path)
    pin(Path(__file__).resolve().relative_to(ROOT))
    pin(Path("syn/verify_tri_oracle_booth_buffered_repair_slots.py"))
    pin(Path("syn/plan_tri_oracle_booth_pin_load_repair.py"))
    return {
        "state": "repaired_booth_row_move_candidates_constructed_and_verified",
        "database_fingerprint_sha256": fingerprints[0],
        "buffer_master": slots["buffer_master"],
        "buffer_width_sites": width,
        "candidate_slots_by_region": results,
        "maximum_cell_shift_micrometers": max(result["maximum_cell_shift_sites"] for result in results.values())
                                         * pitch / units,
        "scope": "One independent candidate slot per crowded region. Each dry run preserves row, orientation, and "
                 "regional boundaries. These moves were verified on the host and have yet to be applied or timed.",
        "evidence_sha256": evidence,
    }


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").is_file()
    directory = Path(json.loads(PLACEMENT.read_text())["database"]).parents[1]
    print(json.dumps(verify(directory / "buffer_slot_recovery_plan.json"), indent=2, sort_keys=True))
