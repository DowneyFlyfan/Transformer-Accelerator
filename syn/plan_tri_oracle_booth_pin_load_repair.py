"""Find load-checked buffer positions on the unchanged, placed Booth floorplan."""

from collections import Counter
from pathlib import Path
import json

import torch

from audit_tri_oracle_booth_pin_loads import MODELS, PLACEMENT, ROOT, capacitance, digest
from audit_tri_oracle_physical_io_budget import macro_boxes
from place_tri_oracle_booth_operand_drivers import locations
from plan_tri_oracle_grouped_reset import CAPACITY_FRACTION, read_library
from verify_tri_oracle_booth_chip_geometry import geometry
from verify_tri_oracle_pad_cold_reload import components
from verify_tri_oracle_serialized_placement_transfer import dimensions


BUFFER = "BUFFD8BWP12T40P140"
WORK = PLACEMENT.parent.parent / ".cache/physical/whole_chip_xcelium_speed/booth_joined_chip/native_glue/retry/overloaded_net_repair"
CORNERS = ("slow", "typ", "fast")


def load_limits(models, endpoint):
    key = endpoint["master"], endpoint["pin"]
    limits = [models[name][key] for name in CORNERS]
    assert all(entry["direction"] == "output" for entry in limits), endpoint
    return tuple(capacitance(entry["max_capacitance"]) for entry in limits)


def input_caps(models, endpoint):
    key = endpoint["master"], endpoint["pin"]
    entries = [models[name][key] for name in CORNERS]
    assert all(entry["direction"] == "input" for entry in entries), endpoint
    return tuple(max(capacitance(entry[k]) for k in ("capacitance", "rise_capacitance", "fall_capacitance") if k in entry)
                 for entry in entries)


def sum_loads(endpoints):
    return tuple(map(sum, zip(*(entry["load"] for entry in endpoints), strict=True)))


def within_budget(load, limit):
    return all(value <= maximum * CAPACITY_FRACTION for value, maximum in zip(load, limit, strict=True))


def split_loads(sinks, limits):
    if within_budget(sum_loads(sinks), limits):
        return [sinks]
    assert len(sinks) > 1, sinks
    axis = max(("x", "y"), key=lambda name: max(sink[name] for sink in sinks) - min(sink[name] for sink in sinks))
    ordered = sorted(sinks, key=lambda sink: (sink[axis], sink["name"], sink["pin"]))
    middle = len(ordered) // 2
    return split_loads(ordered[:middle], limits) + split_loads(ordered[middle:], limits)


def empty_grid(layout, sizes, expected_geometry):
    _, units, rows, fences, groups, blockages = geometry(layout, verify_top=True)
    keys = sorted(rows)
    height = keys[1] - keys[0]
    assert keys == list(range(keys[0], keys[-1] + height, height))
    left, _, columns, pitch = rows[keys[0]]
    assert all((x, count, dx) == (left, columns, pitch) for x, _, count, dx in rows.values())
    grid = [bytearray(columns) for _ in keys]
    fixed = {}
    census = Counter()
    for name, pose in components(layout):
        assert b"/tri_load_repair_" not in name, name
        master, status, x, y, _, _ = pose
        census[status] += 1
        if status == "FIXED":
            fixed[name] = pose
            continue
        assert status == "PLACED"
        row, dy = divmod(y - keys[0], height)
        start, dx = divmod(x - left, pitch)
        width, cell_height = sizes[master]
        width, remainder = divmod(width, pitch)
        assert not (dx or dy or remainder) and cell_height == height
        assert 0 <= row < len(keys) and 0 <= start < start + width <= columns
        assert not any(grid[row][start:start + width]), name
        grid[row][start:start + width] = b"\x01" * width
    assert census == {"PLACED": expected_geometry["standard_cells"],
                      "FIXED": expected_geometry["fixed_memory_macros"]}
    _, halos = macro_boxes(fixed, sizes)
    for x1, y1, x2, y2 in blockages + list(halos.values()):
        first, last = max(0, (y1 - keys[0]) // height), min(len(keys), -(-(y2 - keys[0]) // height))
        start, stop = max(0, (x1 - left) // pitch), min(columns, -(-(x2 - left) // pitch))
        if start < stop:
            for row in range(first, last):
                assert grid[row].find(b"\x01", start, stop) == -1
                grid[row][start:stop] = b"\x02" * (stop - start)
    return grid, rows, keys, left, pitch, height, units, fences, groups


def choose_site(points, unused_sites, group_sites, endpoints, upstream):
    # For Manhattan distance, the maximum over sinks is obtained from extrema
    # along x+y and x-y. All arrays are [legal candidate site].
    x, y = points.unbind(dim=1)
    px, py = x + y, x - y
    plus = [item["x"] + item["y"] for item in endpoints]
    minus = [item["x"] - item["y"] for item in endpoints]
    distance = torch.maximum(
        torch.maximum(px - min(plus), max(plus) - px),
        torch.maximum(py - min(minus), max(minus) - py),
    )
    root_distance = (x - upstream["x"]).abs() + (y - upstream["y"]).abs()
    # Rank first by maximum distance to a load, then by upstream distance.
    score = (distance.to(torch.int64) << 24) + root_distance
    legal = unused_sites & group_sites
    assert bool(legal.any())
    index = int(torch.where(legal, score, torch.iinfo(torch.int64).max).argmin())
    sx, sy = map(int, points[index].tolist())
    exact = max(abs(sx - sink["x"]) + abs(sy - sink["y"]) for sink in endpoints)
    assert int(distance[index]) == exact
    return sx, sy, exact


def plan_nets(nets, models, sizes, board):
    grid, rows, keys, left, pitch, height, units, fences, groups = board
    width, cell_height = sizes[BUFFER]
    slots, remainder = divmod(width, pitch)
    assert not remainder and cell_height == height
    coordinates = locations(grid, left, pitch, keys, slots)
    # Placement candidates [site, coordinate]. Each selected cell occupies
    # slots adjacent positions in one row, so intersecting starts are removed.
    points = torch.as_tensor(coordinates, device="cuda", dtype=torch.int32)
    x, y = points.unbind(dim=1)
    unused = torch.ones_like(x, dtype=torch.bool)
    membership = {path.replace(b"\\", b"").decode(): region for path, region in groups.items()}
    # The export uses default DEF regions. Group members must stay within
    # their regions, while unassigned cells may occupy free sites anywhere.
    unrestricted = unused.clone()
    buffer_in = input_caps(models, {"master": BUFFER, "pin": "I"})
    buffer_out = load_limits(models, {"master": BUFFER, "pin": "Z"})
    assert all(models[corner][BUFFER, "Z"]["function"] == "I" for corner in CORNERS)
    results = []
    used_names = set()
    assigned_jobs = []
    for net_index, net in enumerate(nets):
        driver = net["driver"]
        prefix = driver["name"].rsplit("/", 1)[0] + "/"
        matching = [region for owner, region in membership.items() if prefix.startswith(owner)]
        assert len(matching) <= 1
        assigned_jobs.append((matching[0] if matching else None, net_index, net, prefix))
    for region, net_index, net, prefix in sorted(assigned_jobs, key=lambda job: job[0] is None):
        driver = net["driver"]
        if region:
            a, b, c, d = fences[region]
            legal = (x >= a) & (x + width <= c) & (y >= b) & (y + height <= d)
        else:
            legal = unrestricted
        sinks = [dict(item, load=input_caps(models, item)) for item in net["sinks"]]
        groups_of_sinks = split_loads(sinks, buffer_out)
        driver_limit = load_limits(models, driver)
        leaves_input = tuple(len(groups_of_sinks) * cap for cap in buffer_in)
        root_needed = not within_budget(leaves_input, driver_limit)
        if root_needed:
            assert within_budget(buffer_in, driver_limit) and within_budget(leaves_input, buffer_out)
        cells = []

        def reserve(suffix, loads):
            name = prefix + f"tri_load_repair_{net_index}_{suffix}"
            assert name not in used_names
            used_names.add(name)
            sx, sy, branch_distance = choose_site(points, unused, legal, loads, driver)
            row = (sy - keys[0]) // height
            start = (sx - left) // pitch
            stop = start + slots
            assert not any(grid[row][start:stop])
            grid[row][start:stop] = b"\x03" * (stop - start)
            left_edge, right_edge = left + start * pitch, left + stop * pitch
            unused.logical_and_(~((y == sy) & (x < right_edge) & (x + width > left_edge)))
            info = dict(name=name, master=BUFFER, x=sx, y=sy, orientation=rows[sy][1],
                        region=region, loads=[(sink["name"], sink["pin"]) for sink in loads],
                        furthest_sink_um=branch_distance / units, load=sum_loads(loads))
            assert within_budget(info["load"], buffer_out)
            cells.append(info)
            return info

        for number, group in enumerate(groups_of_sinks):
            reserve(f"leaf{number}", group)
        if root_needed:
            reserve("root", [dict(cell, pin="I", load=buffer_in) for cell in cells])
        original = {(sink["name"], sink["pin"]) for sink in sinks}
        reassigned = [tuple(pin) for cell in cells[:len(groups_of_sinks)] for pin in cell["loads"]]
        assert len(reassigned) == len(original) == len(sinks) and set(reassigned) == original
        driver_load = buffer_in if root_needed else leaves_input
        assert within_budget(driver_load, driver_limit)
        before_worst = max(value / cap for value, cap in zip(sum_loads(sinks), driver_limit, strict=True))
        after_worst = max(
            [value / cap for value, cap in zip(driver_load, driver_limit, strict=True)]
            + [value / cap for cell in cells for value, cap in zip(cell["load"], buffer_out, strict=True)]
        )
        results.append(dict(module=net["module"], net=net["net"], driver=driver, buffers=cells,
                            sinks=len(sinks), before_pin_limit_ratio=before_worst,
                            planned_pin_limit_ratio=after_worst, added_root=root_needed))
    return results, len(coordinates), slots


def main():
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    assert torch.cuda.is_available() and torch.cuda.mem_get_info()[0] >= 1024**3
    placed = json.loads(PLACEMENT.read_text())
    libs = json.loads(MODELS.read_text())
    path = WORK / "endpoints.json"
    inventory = json.loads(path.read_text())
    for name, wanted in inventory["evidence_sha256"].items():
        assert digest(ROOT / name) == wanted, name
    nets = inventory["overloaded_nets"]
    assert len(nets) == 40 and len({(net["driver"]["name"], net["driver"]["pin"]) for net in nets}) == 40
    database = ROOT / placed["database"]
    halo_lefs = [database / "libs/lef" / name for name in libs["physical_abstracts"]]
    for lef in halo_lefs:
        assert digest(lef) == libs["evidence_sha256"][str(lef.relative_to(ROOT))]
    sizes = dimensions(halo_lefs, 2000)
    masters = {entry["master"] for net in nets for entry in (net["driver"], *net["sinks"])} | {BUFFER}
    models, inputs = {}, [path, MODELS, PLACEMENT, Path(__file__).resolve(), *halo_lefs]
    for corner in CORNERS:
        (name,) = (name for name in libs["liberty_models_by_corner"][corner] if name.startswith("tcbn"))
        library = database / "libs/mmmc" / name
        assert digest(library) == libs["evidence_sha256"][str(library.relative_to(ROOT))], library
        models[corner] = read_library(library, masters)
        inputs.append(library)
    layout = database.parents[1] / "cold/layout.def"
    assert digest(layout) == inventory["layout_sha256"]
    torch.cuda.reset_peak_memory_stats()
    board = empty_grid(layout, sizes, placed["geometry"])
    proposed, candidates, slots = plan_nets(nets, models, sizes, board)
    plan = WORK / "buffer_plan.json"
    with plan.open("x") as stream:
        json.dump(dict(nets=proposed), stream, indent=2, sort_keys=True)
        stream.write("\n")
    inputs.extend((layout, plan))
    count = sum(len(net["buffers"]) for net in proposed)
    print(json.dumps(dict(
        state="corrected_booth_overload_buffer_plan_pin_and_site_checks_passed",
        cold_netlist_sha256=inventory["cold_netlist_sha256"],
        planned_nets=len(proposed), sinks=sum(net["sinks"] for net in proposed),
        buffers=count, consumed_placement_sites=count * slots, initial_candidate_origins=candidates,
        moved_existing_cells=0,
        buffer_master=BUFFER, maximum_planned_pin_limit_ratio=max(net["planned_pin_limit_ratio"] for net in proposed),
        characterized_corners=list(CORNERS), host_gpu=torch.cuda.get_device_name(),
        peak_device_bytes=torch.cuda.max_memory_allocated(),
        scope="Physical insertion plan on the exact placed layout. Sites and pin capacitances were checked in software. Native placement, estimated wire delays and routed timing require separate evidence.",
        evidence_sha256={str(entry.relative_to(ROOT)): digest(entry) for entry in inputs},
    ), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
