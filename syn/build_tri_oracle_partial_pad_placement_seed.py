"""Find legal cell coordinates for the existing partial pad-ring candidate."""
import argparse
from bisect import bisect_left, insort
from collections import Counter, defaultdict
import heapq
import json
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
from verify_tri_oracle_partial_pad_ring_geometry import check_geometry, mark_reserved, seed_geometry
from audit_tri_oracle_pad_ring_clearance import POSE, dimensions, get_units
from audit_tri_oracle_placed_chip_boundary import digest
from plan_tri_oracle_pad_ring_macros import ROW


def component_inventory(path):
    with path.open() as stream:
        for line in stream:
            if line == "COMPONENTS 3765868 ;\n":
                break
        else:
            raise ValueError("Missing component section")
        for line in stream:
            if line == "END COMPONENTS\n":
                return
            if line.startswith("- "):
                name, master, status, *_ = POSE.match(line).groups()
                yield name.encode(), (sys.intern(master), sys.intern(status))
        raise ValueError("Unterminated component section")


def verify_inventory(before, after):
    expected = {}
    for name, kind in component_inventory(before):
        assert name not in expected, name
        expected[name] = kind
    count = len(expected)
    assert count == 3765868
    for name, kind in component_inventory(after):
        assert expected.pop(name) == kind, name
    assert not expected
    return count


def build(active, seed, work):
    assert __debug__ and Path("/.dockerenv").is_file()
    assert work.is_relative_to(ROOT / ".cache") and work.is_dir()
    source_def = active / "active.def"
    plan = json.loads((ROOT / "records/tri_oracle_partial_pad_ring_seed.json").read_bytes())
    placement = json.loads((ROOT / "records/tri_oracle_grouped_active_placement.json").read_bytes())
    assert plan["candidate_netlist_sha256"] == placement["candidate_netlist_sha256"]
    assert digest(source_def) == placement["placed_design_exchange_sha256"]
    lefs = sorted((active / "active.db/libs/lef").glob("*.lef"))
    for path in (seed / "macros.tsv", seed / "blockages.tsv", *lefs):
        assert digest(path) == plan["evidence_sha256"][str(path.relative_to(ROOT))]
    assert shutil.disk_usage(work).free >= 10 * 1024**3
    rows = {}
    header = []
    jobs = defaultdict(list)
    kept = kept_sites = 0
    output = work / "seed.def"
    with source_def.open() as source, output.open("x") as target:
        units = get_units(source)
        assert units == 2000
        libs = dimensions(lefs, units)
        macros, reserved = seed_geometry(seed, units, libs)
        height = 2400
        for line in source:
            if line.startswith("DIEAREA "):
                header.append(line)
            if ROW.match(line):
                assert next(source).strip() == ";"
                header.append(line.strip() + " ;\n")
                x, y, direction, count, pitch = ROW.match(line).groups()
                x, y, count, pitch = map(int, (x, y, count, pitch))
                assert y not in rows and pitch == 280 and count == 25428 and x == 40000
                grid = bytearray(count)
                for box in reserved:
                    mark_reserved(grid, y, x, pitch, height, box)
                rows[y] = direction, grid
            if line.startswith("COMPONENTS "):
                assert line == "COMPONENTS 3765868 ;\n"
                break
        assert len(rows) == 2966
        target.write('VERSION 5.8 ;\nDIVIDERCHAR "/" ;\nBUSBITCHARS "[]" ;\n'
                     'DESIGN tri_oracle_chip_command_layer_parallel_chip ;\nUNITS DISTANCE MICRONS 2000 ;\n')
        target.writelines(header)
        target.write("COMPONENTS 3765868 ;\n")
        fixed = set()
        for line in source:
            if line == "END COMPONENTS\n":
                break
            if not line.startswith("- "):
                continue
            name, master, status, x, y, orientation = POSE.match(line).groups()
            x, y = int(x), int(y)
            dx, dy = libs[master]
            if status == "FIXED":
                key = name.replace("\\", "")
                wanted_master, px, py, rotate, halo = macros[key]
                assert key not in fixed and (master,orientation) == (wanted_master,rotate)
                fixed.add(key)
                target.write(f"- {name} {master} + FIXED ( {px} {py} ) {rotate}\n")
                target.write(f"  + HALO {' '.join(map(str, halo))}\n ;\n")
                continue
            assert dy == height and dx % pitch == 0 and (x - 40000) % pitch == 0
            side, grid = rows[y]
            start, width = (x - 40000) // pitch, dx // pitch
            assert 0 <= start < start + width <= len(grid)
            if ((y - 40000) // 2400) % 8 == 0 or any(grid[start:start + width]):
                jobs[width].append((x, y, name, master))
            else:
                grid[start:start + width] = b"\x02" * width
                target.write(line.rstrip(" ;\n") + " ;\n")
                kept += 1
                kept_sites += width
        assert len(fixed) == 631 and kept + sum(map(len, jobs.values())) == 3765237
        gaps = defaultdict(lambda: defaultdict(list))
        widths = defaultdict(list)
        columns_per_tile, rows_per_tile = 1600, 185

        def tile(y, column):
            return ((y - 40000)//height//rows_per_tile, column//columns_per_tile)

        def nearby(row, col, radius):
            for dy in range(-radius, radius + 1):
                dx = radius - abs(dy)
                for direction in ((1, -1) if dx else (1,)):
                    key = row + dy, col + direction * dx
                    if 0 <= key[0] <= 16 and 0 <= key[1] < 16:
                        yield key

        def add_gap(y, x, width):
            key = tile(y, x + width//2)
            if width not in gaps[key]:
                insort(widths[key], width)
            heapq.heappush(gaps[key][width], (y,x))

        for y, (_, grid) in rows.items():
            for match in re.finditer(rb"\x00+", grid):
                add_gap(y, match.start(), len(match[0]))
        assert (sum(width * len(options) for group in gaps.values() for width, options in group.items()) + kept_sites
                == plan["standard_cell_sites_required"] + plan["scenarios_by_reserved_bottom_slots"]["64"]["free_placement_sites"])
        moves = Counter()
        for width, cells in sorted(jobs.items(), reverse=True):
            cells.sort(key=lambda cell: (cell[1], cell[0]))
            for x, y, name, master in cells:
                row, col = tile(y, (x - 40000)//pitch)
                candidates = []
                for radius in range(32):
                    for key in nearby(row, col, radius):
                        at = bisect_left(widths[key], width)
                        if at == len(widths[key]):
                            continue
                        size = widths[key][at]
                        ny, column = gaps[key][size][0]
                        distance = abs(ny-y) + abs(column*pitch+40000-x)
                        candidates.append((distance, size, key, at))
                    if candidates:
                        break
                if not candidates:
                    raise ValueError(f"No interval for size {width}, placed {moves['count']} displaced cells")
                _, size, key, at = min(candidates)
                choices = gaps[key][size]
                ny, column = heapq.heappop(choices)
                if not choices:
                    del gaps[key][size]
                    del widths[key][at]
                if size > width:
                    add_gap(ny, column + width, size-width)
                direction, grid = rows[ny]
                assert not any(grid[column:column+width])
                grid[column:column+width] = b"\x02" * width
                nx = 40000 + column*pitch
                target.write(f"- {name} {master} + PLACED ( {nx} {ny} ) {direction} ;\n")
                delta = abs(nx-x)+abs(ny-y)
                moves["count"] += 1
                moves["distance"] += delta
                moves["maximum"] = max(moves["maximum"], delta)
        target.write("END COMPONENTS\nEND DESIGN\n")

    geometry = check_geometry(output, seed, lefs)
    assert geometry["used_sites"] == plan["standard_cell_sites_required"]
    assert geometry["free_unblocked_sites"] == plan["scenarios_by_reserved_bottom_slots"]["64"]["free_placement_sites"]
    receipt = dict(exact_component_names_masters_and_fixed_status=verify_inventory(source_def, output),
                   state="partial_pad_geometric_seed_verified", reopened_every_nth_row=8, prefer_nearby_gaps=True,
                   input_candidate_sha256=plan["candidate_netlist_sha256"],
                   input_def_sha256=placement["placed_design_exchange_sha256"],
                   seed_def_sha256=digest(output), preserved_standard_cell_locations=kept,
                   moved_standard_cells=moves["count"],
                   mean_moved_cell_manhattan_um=moves["distance"]/moves["count"]/units,
                   max_moved_cell_manhattan_um=moves["maximum"]/units, geometry=geometry)
    receipt["evidence_sha256"] = {
        str(path.relative_to(ROOT)): digest(path) for path in (
            Path(__file__).resolve(), ROOT / "syn/verify_tri_oracle_partial_pad_ring_geometry.py",
            ROOT / "records/tri_oracle_partial_pad_ring_seed.json",
            ROOT / "records/tri_oracle_grouped_active_placement.json",
        )
    }
    receipt["scope"] = (
        "Geometric placement seed checked against the candidate component inventory and planned "
        "memory halos and pad reservations. Innovus import, timing and pad connections require separate checks."
    )
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("active", "seed", "work"):
        parser.add_argument(name, type=lambda path: Path(path).resolve())
    print(json.dumps(build(**vars(parser.parse_args())), indent=2, sort_keys=True))
