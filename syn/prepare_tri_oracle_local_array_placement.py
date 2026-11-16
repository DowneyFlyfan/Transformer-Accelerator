"""Keep legal native coordinates while repacking the rest of the compute array."""

from bisect import bisect_left, insort
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
from verify_tri_oracle_gated_array_placement import (
    WORK as BASE,
    ROOT,
    LEF,
    dimensions,
    digest,
    row_grid,
    section,
    gates_script,
)

WORK = BASE / "local_seed"


def pack(grid, demand, rows):
    gaps = defaultdict(list)
    for row, bits in enumerate(grid):
        for match in re.finditer(rb"\x00+", bits):
            gaps[len(match[0])].append((row, match.start()))
    lengths = sorted(gaps)
    slots = defaultdict(list)
    for width, count in sorted(demand.items(), reverse=True):
        for _ in range(count):
            index = bisect_left(lengths, width)
            if index == len(lengths):
                return None
            size = lengths[index]
            row, col = gaps[size].pop()
            if not gaps[size]:
                lengths.pop(index)
            if size > width:
                remainder = size - width
                if not gaps[remainder]:
                    insort(lengths, remainder)
                gaps[remainder].append((row, col + width))
            slots[width].append(
                (rows[row][0] + col * rows[row][4], rows[row][1], rows[row][2])
            )
    return slots


def pairs(targets, slots):
    if len(targets) <= 1:
        yield from zip(targets, slots, strict=True)
        return
    axis = max(
        range(2),
        key=lambda k: (
            max(p[k] for p in targets)
            - min(p[k] for p in targets)
            + max(p[k] for p in slots)
            - min(p[k] for p in slots)
        ),
    )
    targets.sort(key=lambda p: (p[axis], p[1 - axis], p[2]))
    slots.sort(key=lambda p: (p[axis], p[1 - axis]))
    middle = len(targets) // 2
    yield from pairs(targets[:middle], slots[:middle])
    yield from pairs(targets[middle:], slots[middle:])


def positions():
    sizes = dimensions([LEF], 2000)
    region = (BASE / "region.def").read_text()
    rows, grid, height = row_grid(region)
    left, bottom, _, columns, pitch = rows[0]
    count, body = section((BASE / "attempt.def").read_text(), "COMPONENTS")
    candidates = defaultdict(list)
    for name, master, x, y, side in re.findall(
        r"(?m)^- (\S+) (\S+) \+ PLACED \( (\d+) (\d+) \) (\w+)", body
    ):
        width, cell_height = sizes[master]
        assert width % pitch == 0 and cell_height == height
        candidates[width // pitch].append((int(x), int(y), name, master, side))
    demand = Counter({width: len(cells) for width, cells in candidates.items()})
    assert sum(demand.values()) == count
    exact = {}
    for width, cells in sorted(candidates.items(), reverse=True):
        trial_grid = [bits.copy() for bits in grid]
        choices = []
        for x, y, name, master, side in sorted(
            cells, key=lambda cell: (cell[1], cell[0], cell[2])
        ):
            row, y_offset = divmod(y - bottom, height)
            col, x_offset = divmod(x - left, pitch)
            if (
                not x_offset
                and not y_offset
                and 0 <= row < len(rows)
                and 0 <= col <= columns - width
                and rows[row][2] == side
                and not any(trial_grid[row][col : col + width])
            ):
                trial_grid[row][col : col + width] = b"\x01" * width
                choices.append((row, col, name, master, x, y, side))
        low, high = 0, len(choices)
        while low < high:
            test = (low + high + 1) // 2
            trial_demand = demand.copy()
            trial_demand[width] -= test
            trial_grid = [bits.copy() for bits in grid]
            for row, col, *_ in choices[:test]:
                trial_grid[row][col : col + width] = b"\x01" * width
            if pack(trial_grid, trial_demand, rows) is None:
                high = test - 1
            else:
                low = test
        for row, col, name, master, x, y, side in choices[:low]:
            grid[row][col : col + width] = b"\x01" * width
            exact[name] = (master, x, y, side)
        demand[width] -= low
    slots = pack(grid, demand, rows)
    assert slots is not None
    positioned = exact.copy()
    shift = 0
    for width, cells in candidates.items():
        targets = [
            (x, y, name, master)
            for x, y, name, master, side in cells
            if name not in exact
        ]
        for (x, y, name, master), (sx, sy, side) in pairs(targets, slots[width]):
            positioned[name] = (master, sx, sy, side)
            shift += abs(x - sx) + abs(y - sy)
    assert len(positioned) == count
    first, _, rest = region.partition("\nPINS ")
    seed = WORK / "seed.def"
    with seed.open("w") as stream:
        stream.write(first + f"\nCOMPONENTS {count} ;\n")
        for name, (master, x, y, side) in positioned.items():
            stream.write(f"- {name} {master} + PLACED ( {x} {y} ) {side} ;\n")
        stream.write("END COMPONENTS\n\nPINS " + rest)
    print(
        json.dumps(
            dict(
                cells=count,
                exact=len(exact),
                mean_displacement_um=shift / (count * 2000),
                seed_sha256=digest(seed),
            )
        )
    )
    (WORK / "place.tcl").write_text(gates_script())
    for name in ("netlist.v", "emitted.sdc"):
        path = WORK / name
        if not path.is_symlink():
            path.symlink_to((BASE / name).resolve(strict=True))


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    WORK.mkdir(exist_ok=True)
    positions()
