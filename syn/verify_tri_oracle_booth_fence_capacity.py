"""Check exact row-site capacity for the buffered Booth chip geometry."""

from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from contextlib import ExitStack
import csv
from functools import lru_cache
from hashlib import sha256
from itertools import accumulate, combinations
import json
import mmap
import multiprocessing as mp
from pathlib import Path
import re
import struct
import sys

import numpy as np

from plan_tri_oracle_bonded_pad_recovery import layout, section
from prepare_tri_oracle_local_array_placement import pack
from verify_tri_oracle_booth_placement import components, dimensions
from verify_tri_oracle_gated_compute_array import ROOT, digest, read
from verify_tri_oracle_serialized_placement_transfer import INSTANCE, WRAPPED, catalog

PAD = Path("records/tri_oracle_497_pad_floorplan.json")
TRANSFER = Path("records/tri_oracle_serialized_placement_transfer.json")
RECEIVER = Path("records/tri_oracle_gated_receive_storage.json")
ARRAY = Path("records/tri_oracle_booth_array.json")
PLACEMENT = Path("records/tri_oracle_booth_control_buffers.json")
REFINED = Path("records/tri_oracle_booth_timing_swaps.json")
TARGET = Path("records/paper_result_targets.json")


def read_table(path):
    with path.open() as stream:
        return list(csv.DictReader(stream, delimiter="\t"))


def ceil_div(value, divisor):
    return -(-value // divisor)


def occupied_rectangle(board, x_start, y_start, pitch, height, box):
    x0, y0, x1, y1 = box
    col0 = max(0, (x0 - x_start) // pitch)
    col1 = min(board.shape[1], ceil_div(x1 - x_start, pitch))
    row0 = max(0, (y0 - y_start) // height)
    row1 = min(board.shape[0], ceil_div(y1 - y_start, height))
    if col0 < col1 and row0 < row1:
        board[row0:row1, col0:col1] = 1


def region_indices(region):
    x0, y0, x1, y1 = region
    col0, col1 = (
        max(0, ceil_div(x0 - LEFT, PITCH)),
        min(BOARD.shape[1], (x1 - LEFT) // PITCH),
    )
    row0, row1 = (
        max(0, ceil_div(y0 - BOTTOM, HEIGHT)),
        min(BOARD.shape[0], (y1 - BOTTOM) // HEIGHT),
    )
    return row0, row1, col0, col1


def prove_region(entry):
    name, region = entry
    row0, row1, col0, col1 = region_indices(region)
    grid = [bytearray(line) for line in BOARD[row0:row1, col0:col1]]
    available = sum(line.count(0) for line in grid)
    x = LEFT + col0 * PITCH
    y = BOTTOM + row0 * HEIGHT
    rows = [(x, y + r * HEIGHT, "N", col1 - col0, PITCH) for r in range(row1 - row0)]
    slots = pack(grid, DEMAND, rows)
    result = dict(
        site_capacity=available,
        required_sites=REQUIRED,
        raw_site_margin=available - REQUIRED,
    )
    if slots is None:
        result.update(exact_width_assignment=False)
        return name, result, None
    certificate = sha256()
    assert Counter({width: len(poses) for width, poses in slots.items()}) == DEMAND
    for width, poses in sorted(slots.items()):
        for px, py, _ in sorted(poses):
            row, dy = divmod(py - y, HEIGHT)
            col, dx = divmod(px - x, PITCH)
            assert (
                (dx, dy) == (0, 0)
                and 0 <= row < len(grid)
                and 0 <= col < col + width <= len(grid[row])
            )
            assert not any(grid[row][col : col + width]), (name, width, px, py)
            grid[row][col : col + width] = b"\x01" * width
            certificate.update(struct.pack("<III", width, px, py))
    assert sum(line.count(0) for line in grid) == available - REQUIRED
    result.update(
        exact_width_assignment=True, assigned_widths_sha256=certificate.hexdigest()
    )
    return name, result, b"".join(grid)


def release_parent_cells(cold, sizes, owner, name, region, initial, displaced_widths):
    row0, row1, col0, col1 = region_indices(region)
    candidates = []
    for instance, (master, status, x, y, _, _) in components(cold):
        if status != "PLACED" or owner.match(instance):
            continue
        row, col = (y - BOTTOM) // HEIGHT, (x - LEFT) // PITCH
        if not (row0 <= row < row1 and col0 <= col < col1):
            continue
        width = sizes[master][0] // PITCH
        if col + width <= col1 and np.all(BOARD[row, col : col + width] == 2):
            candidates.append((width, row, col, instance))
    candidates.sort(key=lambda cell: (-cell[0], cell[1], cell[2], cell[3]))
    needed = -initial["raw_site_margin"]
    assert sum(cell[0] for cell in candidates) >= needed
    start = next(
        index
        for index, sites in enumerate(accumulate(cell[0] for cell in candidates), 1)
        if sites >= max(1, needed)
    )
    cursor = 0
    for stop in [*range(start, len(candidates), 512), len(candidates)]:
        for width, row, col, _ in candidates[cursor:stop]:
            assert np.all(BOARD[row, col : col + width] == 2)
            BOARD[row, col : col + width] = 0
            displaced_widths[width] += 1
        cursor = stop
        _, result, packed = prove_region((name, region))
        if packed is not None:
            selected = candidates[:stop]
            result.update(
                relocated_parent_cells=stop,
                relocated_parent_sites=sum(item[0] for item in selected),
                relocated_parent_names_sha256=sha256(
                    b"\n".join(item[3] for item in selected)
                ).hexdigest(),
            )
            return result, packed
    return result, None


def leaf_census(paths, root):
    with ExitStack() as stack:
        modules = catalog(stack, paths)

        @lru_cache(maxsize=None)
        def walk(master):
            if master not in modules:
                return Counter({master: 1})
            source, start, end = modules[master]
            children = Counter(
                match[1].decode() for match in INSTANCE.finditer(source, start, end)
            )
            result = Counter()
            for child, copies in children.items():
                for leaf, count in walk(child).items():
                    result[leaf] += copies * count
            return result

        assert root in modules
        return walk(root)


def global_assignment(rows, demand):
    grid = [bytearray(row) for row in BOARD]
    geometry = [(x, y, "N", n, step) for x, y, n, step in rows]
    slots = pack(grid, demand, geometry)
    if slots is None:
        return None
    assert Counter({width: len(records) for width, records in slots.items()}) == demand
    signature = sha256()
    for width, positions in sorted(slots.items()):
        for x, y, _ in sorted(positions):
            row, ry = divmod(y - BOTTOM, HEIGHT)
            col, rx = divmod(x - LEFT, PITCH)
            assert (
                (ry, rx) == (0, 0)
                and 0 <= row < len(grid)
                and 0 <= col < col + width <= len(grid[row])
            )
            assert not any(grid[row][col : col + width])
            grid[row][col : col + width] = b"\x01" * width
            signature.update(struct.pack("<III", width, x, y))
    return dict(
        assigned_widths_sha256=signature.hexdigest(),
        remaining_sites=sum(line.count(0) for line in grid),
    )


def run():
    global BOARD, LEFT, BOTTOM, PITCH, HEIGHT, DEMAND, REQUIRED
    evidence = {}

    def pin(path, expected=None):
        value = digest(path)
        assert expected is None or value == expected, path
        evidence[str(path)] = value
        return path

    pad = read(pin(PAD))
    transfer = read(pin(TRANSFER))
    receiver = read(pin(RECEIVER))
    array = read(pin(ARRAY))
    buffered = read(pin(PLACEMENT))
    refined = read(pin(REFINED))
    target = read(pin(TARGET))
    sources = pad["evidence_sha256"]
    (cold,) = [
        pin(Path(k), v) for k, v in sources.items() if k.endswith("/cold/layout.def")
    ]
    assert evidence[str(cold)] == transfer["input_layout_sha256"]
    assert not transfer["unmatched_original_components"]
    with cold.open() as stream:
        die = next((line for line in stream if line.startswith("DIEAREA "))).strip()
    outline = tuple(
        map(
            int,
            re.fullmatch(
                r"DIEAREA \( (\d+) (\d+) \) \( (\d+) (\d+) \) ;", die
            ).groups(),
        )
    )

    lefs = [pin(Path(k), v) for k, v in sources.items() if k.endswith(".lef")]
    units, rows, fixed, halos, regions, blockages, area, prior_usage = layout(
        cold, lefs
    )
    sizes = dimensions(lefs, units)
    LEFT, BOTTOM, columns, PITCH = rows[0]
    HEIGHT = rows[1][1] - BOTTOM
    assert all(
        row == (LEFT, BOTTOM + i * HEIGHT, columns, PITCH) for i, row in enumerate(rows)
    )
    assert (units, PITCH, HEIGHT) == (2000, 280, 2400)
    die_mm = target["silicon"]["die_dimensions_mm"]
    assert outline == (0, 0, *(round(side * 1000 * units) for side in die_mm))

    cell_site_area = PITCH * HEIGHT
    assert area == transfer["old_standard_cell_sites"] * cell_site_area
    BOARD = np.zeros((len(rows), columns), dtype=np.uint8)
    moved = {}
    (memory_table,) = [
        pin(Path(k), v) for k, v in sources.items() if k.endswith("/memory_macros.tsv")
    ]
    for row in read_table(memory_table):
        name = row["instance"].encode()
        master, status, x, y, orientation, _ = fixed[name]
        assert (
            status == "FIXED"
            and master == row["master"]
            and orientation == row["orientation"]
        )
        dx, dy = int(row["x_dbu"]) - x, int(row["y_dbu"]) - y
        assert name not in moved and (dx or dy)
        moved[name] = dx, dy
    assert len(moved) == pad["moved_memory_macros"]
    obstacles = list(blockages)
    for name, (x0, y0, x1, y1) in halos.items():
        dx, dy = moved.get(name, (0, 0))
        obstacles.append((x0 + dx, y0 + dy, x1 + dx, y1 + dy))
    (slot_table,) = [
        pin(Path(k), v) for k, v in sources.items() if k.endswith("/pad_slots.tsv")
    ]
    pads = read_table(slot_table)
    assert len(pads) == pad["pad_reservations"]
    for row in pads:
        obstacles.append(
            tuple(int(row["keepout_" + field]) for field in ("x1", "y1", "x2", "y2"))
        )
    for box in obstacles:
        occupied_rectangle(BOARD, LEFT, BOTTOM, PITCH, HEIGHT, box)
    capacity = int(BOARD.size - np.count_nonzero(BOARD))
    assert capacity == pad["new_geometric_site_capacity"]

    with (
        cold.open("rb") as stream,
        mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data,
    ):
        prefixes = {
            name.rstrip("*").encode(): fence
            for name, fence in re.findall(
                r"(?m)^ +([^\s]+\*)\n +\+ REGION (\w+) ;$", section(data, b"GROUPS")
            )
        }
    assert len(prefixes) == len(regions) == 20 and set(prefixes.values()) == set(
        regions
    )
    prefix = re.escape(next(iter(prefixes)).split(b"cores")[0].split(b"clusters")[0])
    owner = re.compile(prefix + rb".*?/cores\\\[\d+\\\]/compute/compute/")
    freed = Counter()
    displaced_widths = Counter()
    previous_population = Counter()
    displaced_cells = displaced_sites = fixed_parent = fixed_parent_sites = 0
    for name, (master, status, x, y, _, _) in components(cold):
        previous_population[master] += 1
        if status == "FIXED":
            continue
        width, height = sizes[master]
        sites, unused = divmod(width, PITCH)
        r, off_y = divmod(y - BOTTOM, HEIGHT)
        c, off_x = divmod(x - LEFT, PITCH)
        assert (
            status == "PLACED" and height == HEIGHT and not any((unused, off_y, off_x))
        ), name
        assert 0 <= r < len(rows) and 0 <= c < c + sites <= columns
        if match := owner.match(name):
            freed[prefixes[match[0]]] += sites
            continue
        row = BOARD[r, c : c + sites]
        if row.any():
            assert not np.any(row == 2), name
            displaced_cells += 1
            displaced_sites += sites
            displaced_widths[sites] += 1
            continue
        row[:] = 2
        fixed_parent += 1
        fixed_parent_sites += sites
    assert {name: sites * cell_site_area for name, sites in freed.items()} == dict(
        prior_usage
    )
    assert (
        sum(freed.values()) + fixed_parent_sites + displaced_sites
        == transfer["old_standard_cell_sites"]
    )
    assert capacity - fixed_parent_sites == BOARD.size - np.count_nonzero(BOARD)
    print(
        "PARENT_FLOORPLAN_VERIFIED",
        capacity,
        fixed_parent,
        displaced_cells,
        displaced_sites,
        file=sys.stderr,
        flush=True,
    )

    (new,) = [
        pin(Path(k), v)
        for k, v in refined["evidence_sha256"].items()
        if k.endswith("/timing_swaps/placed.def")
    ]
    DEMAND = Counter()
    for _, (master, status, *_) in components(new):
        width, height = sizes[master]
        assert status == "PLACED" and width % PITCH == 0 and height == HEIGHT
        DEMAND[width // PITCH] += 1
    REQUIRED = sum(w * n for w, n in DEMAND.items())
    assert REQUIRED == array["booth_row_sites"] + buffered["added_row_sites"]
    assert (
        sum(DEMAND.values()) == buffered["added_buffers"] + array["booth_mapped_cells"]
    )
    assert (
        len(regions)
        == target["silicon"]["clusters"] * target["silicon"]["cores_per_cluster"]
    )
    for a, b in combinations(map(region_indices, regions.values()), 2):
        assert max(a[0], b[0]) >= min(a[1], b[1]) or max(a[2], b[2]) >= min(a[3], b[3])
    with ProcessPoolExecutor(max_workers=8, mp_context=mp.get_context("fork")) as pool:
        initial = list(pool.map(prove_region, sorted(regions.items())))
    by_region = {}
    for name, first, packed in initial:
        region = regions[name]
        if packed is None:
            result, packed = release_parent_cells(
                cold, sizes, owner, name, region, first, displaced_widths
            )
            result["raw_site_margin_before_relocation"] = first["raw_site_margin"]
        else:
            result = first.copy()
        by_region[name] = result
        if packed is not None:
            r0, r1, c0, c1 = region_indices(region)
            BOARD[r0:r1, c0:c1] = np.frombuffer(packed, dtype=np.uint8).reshape(
                r1 - r0, c1 - c0
            )
    packed_count = sum(
        result["exact_width_assignment"] for result in by_region.values()
    )
    print(
        "EXACT_ARRAY_FENCES_VERIFIED",
        packed_count,
        sum(displaced_widths.values()),
        file=sys.stderr,
        flush=True,
    )
    new_logic = (
        transfer["wrapped_standard_cell_sites"]
        - transfer["old_standard_cell_sites"]
        - receiver["sites_saved"]
    )
    margin = (
        capacity
        - fixed_parent_sites
        - len(regions) * REQUIRED
        - displaced_sites
        - new_logic
    )
    assert margin == array["projected_chip_margin_with_same_buffer_allowance"]
    transfer_sources = transfer["evidence_sha256"]
    (bundle,) = [
        pin(Path(key), value)
        for key, value in transfer_sources.items()
        if key.endswith("/credit_request_link/chip_bundle.sv")
    ]
    includes = []
    for filename in re.findall(r'(?m)^`include "([^"]+)"$', bundle.read_text()):
        file = Path(filename)
        relative = file.relative_to(ROOT)
        expected = transfer_sources.get(str(relative), transfer_sources.get(filename))
        assert expected, file
        pin(relative, expected)
        if file.parent.name != "VERILOG" and file.name != "tcbn28hpcplusbwp12t40p140.v":
            includes.append(relative)
    wrapped = leaf_census(includes, WRAPPED.decode())
    wrapped.subtract(previous_population)
    assert all(count >= 0 for count in wrapped.values())
    receiver_sources = receiver["evidence_sha256"]
    (old_receive,) = [
        pin(Path(key), value)
        for key, value in receiver_sources.items()
        if key.endswith("/shared_edge_metadata/genus/netlist.v")
    ]
    (new_receive,) = [
        pin(Path(key), value)
        for key, value in receiver_sources.items()
        if key.endswith("/gated_receive_storage/netlist.v")
    ]
    top = "tri_oracle_credit_metadata_ingress"
    wrapped.subtract(leaf_census([old_receive], top))
    wrapped.update(leaf_census([new_receive], top))
    assert all(count >= 0 for count in wrapped.values())
    wrapper_widths = Counter()
    for master, count in wrapped.items():
        if count:
            width, height = sizes[master]
            assert width % PITCH == 0 and height == HEIGHT
            wrapper_widths[width // PITCH] += count
    assert sum(width * count for width, count in wrapper_widths.items()) == new_logic
    total_relocated_cells = sum(displaced_widths.values())
    total_relocated_sites = sum(
        width * count for width, count in displaced_widths.items()
    )
    assert total_relocated_cells == displaced_cells + sum(
        row.get("relocated_parent_cells", 0) for row in by_region.values()
    )
    assert total_relocated_sites == displaced_sites + sum(
        row.get("relocated_parent_sites", 0) for row in by_region.values()
    )
    floating = displaced_widths + wrapper_widths
    total_floating_sites = sum(width * count for width, count in floating.items())
    assert (
        BOARD.size - int(np.count_nonzero(BOARD)) - total_floating_sites
        == margin + (len(regions) - packed_count) * REQUIRED
    )
    floating_placement = (
        global_assignment(rows, floating) if packed_count == len(regions) else None
    )
    if floating_placement is not None:
        assert floating_placement["remaining_sites"] == margin
    for helper in (layout, pack, catalog, run):
        pin(Path(helper.__code__.co_filename).resolve().relative_to(ROOT))
    return dict(
        state="buffered_booth_chip_geometry_assigned"
        if floating_placement
        else "buffered_booth_chip_geometry_screened",
        die_dimensions_mm=die_mm,
        geometric_capacity=capacity,
        row_sites_per_array=REQUIRED,
        leaf_cells_per_array=sum(DEMAND.values()),
        fences=len(regions),
        exact_width_assignments=packed_count,
        fences_fitting_before_additional_relocation=sum(
            row["exact_width_assignment"] for _, row, _ in initial
        ),
        kept_parent_cells=fixed_parent - (total_relocated_cells - displaced_cells),
        parent_cells_to_relocate=total_relocated_cells,
        parent_cells_conflicting_with_pad_or_macro_reservations=displaced_cells,
        parent_sites_to_relocate=total_relocated_sites,
        incremental_wrapper_sites=new_logic,
        movable_and_new_parent_leaves=sum(floating.values()),
        movable_and_new_parent_sites=total_floating_sites,
        projected_remaining_global_sites=margin,
        all_fences=by_region,
        floating_parent_placement=floating_placement,
        scope="A host geometry check with the recorded pad keepouts and shifted memory halos. "
        "Conflicting parent cells and siblings released from an undersized region are checked together with new wrapper logic. "
        "The global width assignment may use any unoccupied row site while array assignments are confined to their regions.",
        evidence_sha256=evidence,
    )


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    with Path("/proc/meminfo").open() as info:
        assert (
            next(
                int(line.split()[1])
                for line in info
                if line.startswith("MemAvailable:")
            )
            >= 8 * 1024**2
        )
    print(json.dumps(run(), indent=2, sort_keys=True))
