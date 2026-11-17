"""Check contiguous space for the characterized buffer on the repaired placement."""

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re

from audit_tri_oracle_pad_ring_clearance import dimensions, overlap
from plan_tri_oracle_booth_pin_load_repair import empty_grid
from verify_tri_oracle_booth_buffered_row_capacity import MODELS, PLACEMENT, ROOT, digest
from verify_tri_oracle_booth_chip_native_layout import POSE
from verify_tri_oracle_pad_cold_reload import components


BASELINE = Path("records/tri_oracle_corrected_booth_placement_roundtrip.json")
REPAIR = Path("records/tri_oracle_corrected_booth_pin_load_repair.json")
CAPACITY = Path("records/tri_oracle_corrected_booth_buffered_row_capacity.json")
FREE_RUN = re.compile(rb"\x00+")


def region_gaps(grid, bounds, left, bottom, pitch, height, buffer_width):
    x1, y1, x2, y2 = bounds
    assert (x1 - left) % pitch == (x2 - left) % pitch == 0
    assert (y1 - bottom) % height == (y2 - bottom) % height == 0
    start, stop = (x1 - left) // pitch, (x2 - left) // pitch
    first, last = (y1 - bottom) // height, (y2 - bottom) // height
    assert 0 <= start < stop <= len(grid[0]) and 0 <= first < last <= len(grid)
    lengths = Counter(
        match.end() - match.start()
        for index in range(first, last)
        for match in FREE_RUN.finditer(grid[index], start, stop)
    )
    return {
        "free_sites": sum(length * count for length, count in lengths.items()),
        "longest_free_run_sites": max(lengths, default=0),
        "nonoverlapping_buffer_slots": sum((length // buffer_width) * count for length, count in lengths.items()),
    }


def occupy_repair_buffers(grid, added, left, bottom, pitch, height, sizes):
    checksum = 0
    for name, (master, status, x, y, orientation, halo) in added.items():
        row, dy = divmod(y - bottom, height)
        start, dx = divmod(x - left, pitch)
        width, cell_height = sizes[master]
        sites, remainder = divmod(width, pitch)
        assert not (dx or dy or remainder) and cell_height == height
        assert not halo and status == "PLACED"
        assert 0 <= row < len(grid) and 0 <= start < start + sites <= len(grid[row])
        assert not any(grid[row][start:start + sites]), name
        grid[row][start:start + sites] = b"\x01" * sites
        fields = (name, master.encode(), status.encode(), orientation.encode(), POSE.pack(x, y, 0, 0, 0, 0))
        checksum += int.from_bytes(sha256(b"\0".join(fields)).digest(), "big")
    return checksum


def verify():
    evidence = {}

    def pin(path, expected=None):
        actual = digest(path)
        assert expected is None or actual == expected, path
        evidence[str(path)] = actual
        return path

    before, placed, models, repair, capacity = (
        json.loads(pin(path).read_text()) for path in (BASELINE, PLACEMENT, MODELS, REPAIR, CAPACITY)
    )
    database = Path(placed["database"])
    fingerprint = placed["database_fingerprint_sha256"]
    assert models["database_fingerprint_sha256"] == capacity["database_fingerprint_sha256"] == fingerprint
    source = Path(before["database"]).parents[1] / "cold/layout.def"
    final = database.parents[1] / "cold/layout.def"
    pin(source, before["evidence_sha256"][str(source)])
    pin(final, placed["evidence_sha256"][str(final)])
    assert capacity["evidence_sha256"][str(final)] == evidence[str(final)]
    plan_path, = (Path(name) for name in repair["evidence_sha256"] if name.endswith("/buffer_plan.json"))
    plan = json.loads(pin(plan_path, repair["evidence_sha256"][str(plan_path)]).read_text())
    master = repair["buffer_master"]
    planned = {
        node["name"].replace("\\", "").encode():
        (node["master"], "PLACED", node["x"], node["y"], node["orientation"], ())
        for net in plan["nets"] for node in net["buffers"]
    }
    added = {
        name.replace(b"\\", b""): pose for name, pose in components(final)
        if name.rsplit(b"/", 1)[-1].startswith(b"tri_load_repair_")
    }
    assert added == planned and len(added) == repair["added_buffers"] == 84
    assert {pose[0] for pose in added.values()} == {master}
    libraries = [
        pin(path, models["evidence_sha256"][str(path)])
        for path in sorted((database / "libs/lef").glob("*.lef"))
    ]
    assert len(libraries) == 7
    sizes = dimensions(libraries, 2000)
    grid, _, levels, left, pitch, height, units, regions, _ = empty_grid(source, sizes, before["geometry"])
    assert units == 2000
    buffer_width, remainder = divmod(sizes[master][0], pitch)
    assert remainder == 0 and sizes[master][1] == height
    assert buffer_width * len(added) == repair["consumed_placement_sites"]
    delta = occupy_repair_buffers(grid, added, left, levels[0], pitch, height, sizes)
    old_pose_hash = int(before["geometry"]["pose_sha256_sum"], 16)
    new_pose_hash = int(placed["geometry"]["pose_sha256_sum"], 16)
    assert (old_pose_hash + delta) % (1 << 256) == new_pose_hash
    bounds = list(regions.values())
    assert not any(overlap(bound, previous) for i, bound in enumerate(bounds) for previous in bounds[:i])
    by_region = {
        region: region_gaps(grid, bounds, left, levels[0], pitch, height, buffer_width)
        for region, bounds in regions.items()
    }
    assert {region: result["free_sites"] for region, result in by_region.items()} == capacity["row_sites_free_by_region"]
    zero_fit = sorted(region for region, result in by_region.items() if result["nonoverlapping_buffer_slots"] == 0)
    pin(Path(__file__).resolve().relative_to(ROOT))
    pin(Path("syn/plan_tri_oracle_booth_pin_load_repair.py"))
    return {
        "state": "repaired_booth_contiguous_buffer_capacity_verified",
        "database_fingerprint_sha256": fingerprint,
        "buffer_master": master,
        "buffer_width_sites": buffer_width,
        "nonoverlapping_buffer_slots": sum(region["nonoverlapping_buffer_slots"] for region in by_region.values()),
        "regions_without_buffer_slots": zero_fit,
        "regions": by_region,
        "scope": "Standard-cell space for one full row-height buffer master. Each slot has sufficient contiguous legal "
                 "sites inside its region after the 84 verified additions. Timing, wire congestion and pin access require "
                 "native analysis.",
        "evidence_sha256": evidence,
    }


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").is_file()
    print(json.dumps(verify(), indent=2, sort_keys=True))
