"""Use the graphics processor to check every legal location for traced drivers."""

from collections import Counter
import json
from pathlib import Path
import re
import shutil

import numpy as np
import torch

from audit_tri_oracle_booth_operand_spans import lef_ports, locate
from audit_tri_oracle_physical_io_budget import macro_boxes
from build_tri_oracle_booth_chip_seed import orient
from verify_tri_oracle_booth_chip_geometry import geometry, layout
from verify_tri_oracle_booth_chip_link import WORK
from verify_tri_oracle_booth_fence_capacity import PAD
from verify_tri_oracle_gated_compute_array import ROOT, digest, read
from verify_tri_oracle_pad_cold_reload import components
from verify_tri_oracle_serialized_placement_transfer import dimensions

OUT = WORK / "operand_geometry"
TERMINALS = Path("records/tri_oracle_booth_chip_terminals.json")
ORIGINAL = WORK / "placement_with_terminal_seed.def"
HEIGHT = 2400
GAP = re.compile(rb"\x00+")
PLACED = re.compile(rb"(\+ PLACED \( )-?\d+ -?\d+( \) )(N|S|FN|FS)\b")


def metrics(point, other_pins):
    vector = [point, *other_pins]
    width = sum(max(axis) - min(axis) for axis in zip(*vector, strict=True))
    longest = max(abs(point[0] - x) + abs(point[1] - y) for x, y in other_pins)
    return width, longest


def locations(grid, left, pitch, row_keys, cells):
    all_points = []
    for row_number, line in enumerate(grid):
        for unused in GAP.finditer(line):
            start, stop = unused.span()
            if stop - start >= cells:
                xs = left + np.arange(start, stop - cells + 1, dtype=np.int32) * pitch
                all_points.append(
                    np.column_stack((xs, np.full_like(xs, row_keys[row_number])))
                )
    return np.concatenate(all_points)


def optimize(candidate, master_pose, points, rows, poses, shapes, sizes):
    older = tuple(master_pose[2:5])
    name = candidate["driver"]
    old_pin_data = {}
    metrics_by_candidate = torch.zeros(
        (len(points), 2), device="cuda", dtype=torch.float64
    )
    enabled = torch.ones(len(points), device="cuda", dtype=torch.bool)
    gpu_points = torch.as_tensor(points, device="cuda", dtype=torch.float64)
    mirror = torch.as_tensor([rows[y][1] == "FS" for y in points[:, 1]], device="cuda")
    bounds = {}
    for pin, record in candidate["incident"].items():
        original, sink_or_source = None, []
        for target, port, direction in record["endpoints"]:
            loc = locate(poses[target], port, shapes, sizes, direction)
            if target == name and port == pin:
                original = loc
            else:
                sink_or_source.append(loc)
        assert original is not None and sink_or_source
        hpwl, maximum = metrics(original, sink_or_source)
        old_pin_data[pin] = (hpwl, maximum)
        bounds[pin] = sink_or_source
        master = master_pose[0]
        _, px, py = shapes[master][pin]
        width, height = sizes[master]
        if older[2] in ("FN", "S"):
            px = width - px
        offset_y = torch.where(mirror, height - py, py)
        x, y = gpu_points[:, 0] + px, gpu_points[:, 1] + offset_y
        points_per_axis = list(zip(*sink_or_source, strict=True))
        candidate_hpwl = (
            x.clamp(min=max(points_per_axis[0]))
            - x.clamp(max=min(points_per_axis[0]))
            + y.clamp(min=max(points_per_axis[1]))
            - y.clamp(max=min(points_per_axis[1]))
        )
        enabled &= candidate_hpwl <= hpwl + 1e-6
        metrics_by_candidate[:, 1] += candidate_hpwl
        if pin == candidate["output_pin"]:
            diag = [
                [a + b for a, b in sink_or_source],
                [a - b for a, b in sink_or_source],
            ]
            pp, pm = x + y, x - y
            longest = torch.maximum(
                torch.maximum(pp - min(diag[0]), max(diag[0]) - pp),
                torch.maximum(pm - min(diag[1]), max(diag[1]) - pm),
            )
            metrics_by_candidate[:, 0] = longest
            enabled &= longest < maximum - 1e-6
    if not bool(enabled.any()):
        return None
    objective = torch.where(enabled, metrics_by_candidate[:, 0], torch.inf)
    best_point = int(objective.argmin())
    x, y = (int(value) for value in points[best_point])
    direction = orient(rows[y][1].encode(), older[2].encode()).decode()
    after_pose = (master_pose[0], master_pose[1], x, y, direction, master_pose[5])
    after = {}
    for pin, endpoints in bounds.items():
        geom = locate(after_pose, pin, shapes, sizes, shapes[master_pose[0]][pin][0])
        after[pin] = metrics(geom, endpoints)
        assert after[pin][0] <= old_pin_data[pin][0] + 1e-6
    output = candidate["output_pin"]
    assert after[output][1] < old_pin_data[output][1]
    assert abs(after[output][1] - float(metrics_by_candidate[best_point, 0])) < 1e-3
    return after_pose, {
        "driver": name,
        "region": candidate["region"],
        "positions_examined": len(points),
        "before_origin": list(older),
        "after_origin": [x, y, direction],
        "incident_net_count": len(bounds),
        "incident_net_hpwl_change_um": round(
            sum(after[p][0] - old_pin_data[p][0] for p in bounds) / 2000, 3
        ),
        "longest_output_span_before_um": round(old_pin_data[output][1] / 2000, 3),
        "longest_output_span_after_um": round(after[output][1] / 2000, 3),
    }


def run():
    graph = read(OUT / "incident.json")
    assert graph["state"] == "driver_pin_neighborhoods_traced"
    assert all(
        digest(Path(name)) == value for name, value in graph["evidence_sha256"].items()
    )
    receipt = read(TERMINALS)
    assert digest(ORIGINAL) == receipt["evidence_sha256"][str(ORIGINAL)]
    pad = read(PAD)
    lefs = [Path(name) for name in pad["evidence_sha256"] if name.endswith(".lef")]
    assert all(digest(path) == pad["evidence_sha256"][str(path)] for path in lefs)
    sizes, shapes = dimensions(lefs, 2000), lef_ports(lefs)
    _, units, rows, regions, groups, blockages = geometry(ORIGINAL, verify_top=True)
    assert units == 2000
    keys = sorted(rows)
    left, _, count, pitch = rows[keys[0]]
    grid = [bytearray(count) for _ in rows]
    wanted = {
        name
        for candidate in graph["candidates"]
        for net in candidate["incident"].values()
        for name, _, _ in net["endpoints"]
    }
    poses = {}
    fixed = {}
    census = Counter()
    for raw, state in components(ORIGINAL):
        master, status, x, y, _, _ = state
        name = raw.decode().replace("\\", "")
        if name in wanted:
            assert name not in poses
            poses[name] = state
        census[status] += 1
        if status == "PLACED":
            i, rem_y = divmod(y - keys[0], HEIGHT)
            j, rem_x = divmod(x - left, pitch)
            width = sizes[master][0] // pitch
            assert not (rem_x or rem_y) and not any(grid[i][j : j + width])
            grid[i][j : j + width] = b"\x01" * width
        else:
            assert status == "FIXED"
            fixed[raw] = state
    assert wanted == poses.keys() and len(fixed) == 631
    _, halos = macro_boxes(fixed, sizes)
    obstacles = blockages + list(halos.values())
    for x1, y1, x2, y2 in obstacles:
        ylo, yhi = (
            max(0, (y1 - keys[0]) // HEIGHT),
            min(len(keys), -(-(y2 - keys[0]) // HEIGHT)),
        )
        xlo, xhi = max(0, (x1 - left) // pitch), min(count, -(-(x2 - left) // pitch))
        if xlo < xhi:
            for i in range(ylo, yhi):
                assert grid[i].find(b"\x01", xlo, xhi) == -1
                grid[i][xlo:xhi] = b"\x02" * (xhi - xlo)

    torch.cuda.reset_peak_memory_stats()
    moves, outcomes, held = {}, [], []
    for candidate in graph["candidates"]:
        driver = candidate["driver"]
        previous = poses[driver]
        width = sizes[previous[0]][0] // pitch
        assert previous[1] == "PLACED"
        points = locations(grid, left, pitch, keys, width)
        selected = optimize(candidate, previous, points, rows, poses, shapes, sizes)
        if selected is None:
            held.append(driver)
            continue
        poses[driver], facts = selected
        outcomes.append(facts)
        x, y, side = poses[driver][2:5]
        old_x, old_y = previous[2:4]
        i, j = (y - keys[0]) // HEIGHT, (x - left) // pitch
        a, b = (old_y - keys[0]) // HEIGHT, (old_x - left) // pitch
        assert not any(grid[i][j : j + width]) and all(grid[a][b : b + width])
        grid[i][j : j + width] = b"\x01" * width
        grid[a][b : b + width] = b"\x00" * width
        moves[driver.encode()] = (x, y, side.encode())
    assert moves
    target = OUT / "placement_with_driver_relocation.def"
    partial = target.with_suffix(".partial")
    assert shutil.disk_usage(OUT).free > ORIGINAL.stat().st_size
    missed = moves.copy()
    with ORIGINAL.open("rb") as src, partial.open("wb") as dst:
        for line in src:
            if line.startswith(b"- "):
                name = line.split(None, 2)[1].replace(b"\\", b"")
                if name in missed:
                    x, y, direction = missed.pop(name)
                    line, count = PLACED.subn(
                        lambda m: m[1] + b"%d %d" % (x, y) + m[2] + direction, line
                    )
                    assert count == 1
            dst.write(line)
    assert not missed
    assert geometry(partial, verify_top=True) == geometry(ORIGINAL, verify_top=True)
    counts, arrays, _, _, _, sites = layout(
        partial, sizes, rows, regions, groups, obstacles, fixed.copy(), HEIGHT
    )
    assert (
        counts == census
        and len(arrays) == 20
        and sites == sum(line.count(0) for line in grid)
    )
    partial.replace(target)
    return dict(
        state="traced_parent_driver_relocations_geometrically_verified",
        moves=outcomes,
        retained_resolved_drivers=held,
        skipped_unresolved_drivers=len(graph["unresolved_parents"]),
        peak_gpu_allocated_bytes=torch.cuda.max_memory_allocated(),
        output_sha256=digest(target),
        placement_checks=dict(
            cells=counts.total(), array_regions=len(arrays), remaining_row_sites=sites
        ),
        scope="For each moved driver, every traced incident net had no larger half-perimeter in the candidate check, and the largest driver-to-load span fell. These are geometric proxies. Full-chip static timing is pending.",
        evidence_sha256={
            str(path): digest(path)
            for path in (
                TERMINALS,
                PAD,
                ORIGINAL,
                target,
                OUT / "incident.json",
                Path(__file__).resolve().relative_to(ROOT),
            )
        },
    )


if __name__ == "__main__":
    assert torch.cuda.is_available() and __debug__
    print(json.dumps(run(), sort_keys=True, indent=2))
