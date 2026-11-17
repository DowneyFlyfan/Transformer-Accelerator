"""Build and independently check the wide-request whole-chip placement seed."""

from collections import Counter, defaultdict
from itertools import chain
import json
import mmap
import os
from pathlib import Path
import re
import shutil
import sys
from tempfile import TemporaryDirectory

import numpy as np

from audit_tri_oracle_pad_ring_clearance import contains, dimensions, overlap
from audit_tri_oracle_physical_io_budget import macro_boxes
from link_tri_oracle_indexed_whole_chip import module_at, signature, spans, update_instance
from plan_tri_oracle_bonded_pad_recovery import section
from prepare_tri_oracle_dual_group_placement_seed import def_name, sorted_rows, top_ports
from prepare_tri_oracle_local_array_placement import pack, pairs
from verify_tri_oracle_booth_chip_geometry import geometry, layout
from verify_tri_oracle_booth_fence_capacity import occupied_rectangle
from verify_tri_oracle_corrected_booth_roundtrip import ROOT, TOP, digest
from verify_tri_oracle_pad_cold_reload import boundary_sections, components
from verify_tri_oracle_seed_components import INSTANCE
from verify_tri_oracle_wide_request_timing import MODELS, PLACEMENT, TRIAL
from verify_tri_oracle_wide_request_trial import MODULE, TX


FLOORPLAN = Path("records/tri_oracle_511_pad_floorplan.json")
PREFIX = b"request_link/"
VIEWS = ("setup_slow", "setup_typ", "hold_fast")
PIN = re.compile(r"^- (\S+) \+ NET \1 \+ DIRECTION (INPUT|OUTPUT) \+ USE SIGNAL\n$")
COORDINATES = re.compile(r"^  \+ FIXED \( (\d+) (\d+) \) (\w+) ;\n$")


def netlist(base, mapped, output):
    standalone = mapped.read_bytes()
    wide = module_at(standalone, spans(standalone), MODULE)
    assert signature(wide)["pad_data"] == (b"output", b"[21:0]")
    additions = {PREFIX + instance.removeprefix(b"\\"): master.decode()
                 for master, instance in INSTANCE.findall(wide)}
    assert len(additions) == 52
    with base.open("rb") as handle, mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as source:
        index = spans(source)
        assert MODULE not in index
        original = module_at(source, index, TOP)
        reference = signature(original)
        assert reference["memory_tx_data"] == (b"output", b"[7:0]")
        assert original.count(b"output [7:0] memory_tx_data;") == 1
        converted = original.replace(b"output [7:0] memory_tx_data;", b"output [21:0] memory_tx_data;")
        converted = update_instance(converted, TX, "request_link", replacement=MODULE)
        assert signature(converted) == reference | {"memory_tx_data": (b"output", b"[21:0]")}
        first, last = index[TOP]
        with output.open("xb") as target, memoryview(source) as memory:
            target.write(memory[:first])
            target.write(converted)
            target.write(memory[last:])
            target.write(b"\n")
            target.write(wide)
            target.write(b"\n")
    return top_ports(converted), additions


def pin_locations(base, reserved, logical):
    count, raw = boundary_sections(base)["PINS"]
    assert count == 484 and len(raw) == 3 * count
    pins = {}
    for index in range(0, len(raw), 3):
        block = raw[index:index + 3]
        name, direction = PIN.fullmatch(block[0]).groups()
        x, y, orientation = COORDINATES.fullmatch(block[2]).groups()
        pins[name] = direction, int(x), int(y), orientation, block
    assert len(pins) == count
    additions = [f"memory_tx_data[{bit}]" for bit in range(8, 22)]
    assert logical == {name: info[0] for name, info in pins.items()} | dict.fromkeys(additions, "OUTPUT")
    template = pins["memory_tx_data[0]"]
    assert template[2:4] == (218000, "N") and template[4][1].startswith("  + LAYER M5 ")
    bottom = [x for _, x, y, _, _ in pins.values() if y == template[2]]
    free = sorted(
        ((reserve, body) for edge, reserve, body in reserved if edge == "bottom"
         and not any(reserve[0] <= x < reserve[2] for x in bottom)),
        key=lambda entry: (abs((entry[1][0] + entry[1][2]) // 2 - template[1]), entry[1][0]),
    )
    assert len(free) >= len(additions)
    selected = []
    for name, (_, body) in zip(additions, sorted(free[:len(additions)]), strict=True):
        # Snap to the existing M5 track grid. Retain the bottom pin shape
        # and its 2,000 database-unit extension toward the core.
        x = ((body[0] + body[2]) // 2) // 200 * 200
        assert body[0] + 50 <= x <= body[2] - 50
        selected.extend((f"- {name} + NET {name} + DIRECTION OUTPUT + USE SIGNAL\n",
                         template[4][1], f"  + FIXED ( {x} 218000 ) N ;\n"))
    with base.open() as source:
        assert any(line == "TRACKS X 200 DO 35999 STEP 200 LAYER M5 ;\n" for line in source)
    return raw + tuple(selected)


def separate_blockages(keepouts, planned):
    sizes = {(box[2] - box[0], box[3] - box[1]) for _, box, _ in planned}
    assert sizes == {(50000, 220000), (220000, 50000)}
    other = tuple(box for box in keepouts if (box[2] - box[0], box[3] - box[1]) not in sizes)
    assert len(keepouts) == 501 and len(other) == 4 and len(planned) == 511
    return other + tuple(tuple(box) for _, box, _ in planned)


def write_def(base, output, die, row_map, regions, groups, blockages, macros, dimensions_by_master,
              new_cells, signal_pins, relocated_macros):
    _, halos = macro_boxes(macros, dimensions_by_master)
    for index, halo in enumerate(halos.values()):
        assert contains(die, halo)
        assert not any(overlap(halo, prior) for prior in list(halos.values())[:index])
        assert not any(overlap(halo, keepout) for keepout in blockages[4:])
    rows = [(x, y, orient, count, step) for y, (x, orient, count, step) in sorted(row_map.items())]
    x0, y0, _, cols, pitch = rows[0]
    height = rows[1][1] - y0
    # Reopen some complete rows in the strip affected by the pad and macro
    # changes. Isolated short gaps there cannot accommodate all cell widths.
    repack_until = max(halos[name][3] for name in relocated_macros) + 8 * height
    board = np.zeros((len(rows), cols), dtype=np.uint8)
    for box in chain(blockages, halos.values()):
        occupied_rectangle(board, x0, y0, pitch, height, box)
    grid = [bytearray(row) for row in board]
    del board
    pending = defaultdict(lambda: defaultdict(list))
    counters = Counter()
    seen = set()
    anchor_x, anchor_y = [], []
    ownership = re.compile(re.escape(next(iter(groups)).split(b"/clusters")[0])
                           + rb"/clusters.*?/cores\\\[\d+\\\]/compute/compute/")

    def put(stream, name, master, x, y, direction, halo=()):
        status = "FIXED" if halo else "PLACED"
        stream.write(f"- {name.decode()} {master} + {status} ( {x} {y} ) {direction}")
        if halo:
            stream.write("\n  + HALO " + " ".join(map(str, halo)) + "\n")
        stream.write(" ;\n")

    def pack_group(group, stream):
        if not pending[group]:
            return
        if group is None:
            first, stop, left, right = 0, len(rows), 0, cols
        else:
            x1, y1, x2, y2 = regions[group]
            first, stop = -(-(y1 - y0) // height), (y2 - y0) // height
            left, right = -(-(x1 - x0) // pitch), (x2 - x0) // pitch
        demand = Counter({width: len(cells) for width, cells in pending[group].items()})
        target_rows = [(cell[1] - y0) // height for cells in pending[group].values() for cell in cells]
        lo, hi = min(target_rows), max(target_rows) + 1
        slots = None
        # Try nearby complete rows first. Expand the search only when those
        # rows cannot fit the full group at its exact cell widths.
        for margin in range(0, len(rows) + 64, 64):
            start, end = max(first, lo - margin), min(stop, hi + margin)
            region_rows = [(x0 + pitch * left, y, orient, right - left, pitch)
                           for _, y, orient, _, _ in rows[start:end]]
            available = grid[start:end] if group is None else [row[left:right] for row in grid[start:end]]
            slots = pack(available, demand, region_rows)
            if slots is not None or (start, end) == (first, stop):
                break
        if slots is None:
            raise ValueError(f"Existing anchors left fragmented sites for {group}")
        for width, cells in pending[group].items():
            for (previous_x, previous_y, name, master, is_new), (x, y, direction) in pairs(cells, slots[width]):
                if group is not None:
                    assert contains(regions[group], (x, y, x + width * pitch, y + height))
                row, col = grid[(y - y0) // height], (x - x0) // pitch
                assert row.find(b"\x01", col, col + width) < 0
                row[col:col + width] = b"\x01" * width
                put(stream, name, master, x, y, direction)
                counters["new_link_cells" if is_new else "repacked_cells"] += 1
                if not is_new and (x, y) != (previous_x, previous_y):
                    counters["relocated_cells"] += 1
                distance = abs(x - previous_x) + abs(y - previous_y)
                counters["max_displacement_dbu"] = max(counters["max_displacement_dbu"], distance)
                counters["total_displacement_dbu"] += distance

    with base.open() as current, output.open("x") as stream:
        for line in current:
            if line.startswith("COMPONENTS "):
                count = int(line.split()[1])
                break
            stream.write(line)
        assert count == 4104616
        combined = count - 61 + len(new_cells)
        stream.write(f"COMPONENTS {combined} ;\n")
        for name, pose in components(base):
            master, status, x, y, direction, _ = pose
            if status == "FIXED":
                wanted = macros[name]
                put(stream, name, master, *wanted[2:])
                seen.add(name)
                continue
            if name.startswith(PREFIX):
                anchor_x.append(x)
                anchor_y.append(y)
                continue
            width, cell_height = dimensions_by_master[master]
            assert cell_height == height and width % pitch == 0
            cells = width // pitch
            row_index, col = (y - y0) // height, (x - x0) // pitch
            row = grid[row_index]
            reopens = y < repack_until and row_index % 8 == 0
            if reopens or row.find(b"\x01", col, col + cells) >= 0:
                match = ownership.match(name)
                group = groups[match[0]] if match else None
                pending[group][cells].append((x, y, name, master, False))
                counters["cells_in_reopened_rows"] += reopens
            else:
                row[col:col + cells] = b"\x01" * cells
                put(stream, name, master, x, y, direction)
                counters["retained_cells"] += 1
        assert seen == macros.keys() and len(anchor_x) == len(anchor_y) == 61
        x, y = sum(anchor_x) // 61, sum(anchor_y) // 61
        for name, master in new_cells.items():
            width, cell_height = dimensions_by_master[master]
            assert cell_height == height and width % pitch == 0
            pending[None][width // pitch].append((x, y, def_name(name), master, True))
        for group in sorted(name for name in pending if name is not None):
            pack_group(group, stream)
        pack_group(None, stream)
        assert len(seen) + sum(counters[key] for key in ("retained_cells", "repacked_cells", "new_link_cells")) == combined
        stream.write(f"END COMPONENTS\n\nPINS {len(signal_pins)//3} ;\n")
        stream.writelines(signal_pins)
        stream.write(f"END PINS\n\nBLOCKAGES {len(blockages)} ;\n")
        for x1, y1, x2, y2 in blockages:
            stream.write(f"   - PLACEMENT RECT ( {x1} {y1} ) ( {x2} {y2} ) ;\n")
        stream.write("END BLOCKAGES\n\n")
        with base.open("rb") as base_file, mmap.mmap(base_file.fileno(), 0, access=mmap.ACCESS_READ) as data:
            stream.write(f"GROUPS {len(groups)} ;\n")
            stream.write(section(data, b"GROUPS"))
        stream.write("\nEND GROUPS\n\nEND DESIGN\n")
    return counters, halos, height


def verify_inventory(mapped, seed):
    def logical_leaves():
        with mapped.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as content:
            index = spans(content)

            def walk(module, prefix):
                start, end = index[module]
                for match in INSTANCE.finditer(content, start, end):
                    master, instance = match.groups()
                    name = prefix + instance.removeprefix(b"\\")
                    child = master.decode()
                    if child in index:
                        yield from walk(child, name + b"/")
                    else:
                        yield name + b"\t" + master

            yield from walk(TOP, b"")

    with TemporaryDirectory(dir=seed.parent, prefix="inventory_") as folder:
        cpus = min(4, len(os.sched_getaffinity(0)))
        logical, expected = sorted_rows(Path(folder), "logical", logical_leaves(), cpus)
        physical, counted = sorted_rows(Path(folder), "physical",
                                        (name.replace(b"\\", b"") + b"\t" + pose[0].encode()
                                         for name, pose in components(seed)), cpus)
        assert expected == counted
        with logical.open("rb") as left, physical.open("rb") as right:
            previous = b""
            for a, b in zip(left, right, strict=True):
                assert a == b, (a, b)
                current = b.split(b"\t", 1)[0]
                assert previous < current
                previous = current
        return counted, digest(physical)


def run():
    evidence = {}

    def pin(path, expected=None):
        checksum = digest(path)
        assert expected is None or checksum == expected, path
        evidence[str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path)] = checksum
        return path

    placement, models, trial, floorplan = (json.loads(pin(record).read_text()) for record in
                                           (PLACEMENT, MODELS, TRIAL, FLOORPLAN))
    assert floorplan["regional_and_global_site_demands_met"] and floorplan["pad_reservations"] == 511
    database = Path(placement["database"])
    stage = database.parents[1]
    cold = stage / "cold"
    base = pin(cold / "cold.v", floorplan["cold_netlist_sha256"])
    source = pin(cold / "layout.def", placement["evidence_sha256"][str(cold / "layout.def")])
    layouts = stage / "wide_request_trial/pad_floorplan/screened_floorplan.json"
    plan = json.loads(pin(layouts, floorplan["evidence_sha256"][str(layouts)]).read_text())
    mapped = stage / "wide_request_trial/genus/netlist.v"
    pin(mapped, trial["evidence_sha256"][str(mapped)])
    lefs = [pin(path, models["evidence_sha256"][str(path)]) for path in sorted((database / "libs/lef").glob("*.lef"))]
    assert len(lefs) == 7
    die, units, rows, regions, groups, original = geometry(source, verify_top=True)
    assert die == (0, 0, 3600 * units, 3600 * units)
    masters = dimensions(lefs, units)
    macros = {name: pose for name, pose in components(source) if pose[1] == "FIXED"}
    assert len(macros) == 631 and len(plan["moved_macros"]) == 9
    for key, (master, x, y, orientation) in plan["moved_macros"].items():
        before = macros[key.encode()]
        assert (master, orientation) == (before[0], before[4]) and before[2:4] != (x, y)
        macros[key.encode()] = master, "FIXED", x, y, orientation, before[-1]
    blockages = separate_blockages(original, plan["pad_slots"])
    out = stage / "wide_request_trial/placement_seed"
    assert shutil.disk_usage(out.parent).free >= 12 * 1024**3
    out.mkdir()
    candidate, seed = out / "candidate.v", out / "seed.def"
    ports, added = netlist(base, mapped, candidate)
    pins = pin_locations(source, plan["pad_slots"], ports)
    print(f"PORTS_VERIFIED {len(ports)}", file=sys.stderr, flush=True)
    counters, halos, height = write_def(source, seed, die, rows, regions, groups, blockages,
                                        macros, masters, added, pins, [name.encode() for name in plan["moved_macros"]])
    print(f"PLACEMENT_COORDINATES_WRITTEN {dict(counters)}", file=sys.stderr, flush=True)
    assert geometry(seed, verify_top=True) == (die, units, rows, regions, groups, list(blockages))
    vectors = boundary_sections(seed)
    assert vectors["PINS"] == (498, pins) and vectors["BLOCKAGES"] == (515, blockages)
    census, _, _, _, _, remaining = layout(seed, masters, rows, regions, groups,
                                            list(blockages) + list(halos.values()), macros.copy(), height)
    count, inventory_digest = verify_inventory(candidate, seed)
    assert count == 4104607 and census == {"PLACED": count - 631, "FIXED": 631}
    assert remaining == floorplan["global_site_margin"]
    for view in VIEWS:
        old = cold / f"{view}.sdc"
        constraints = pin(old, placement["evidence_sha256"][str(old)]).read_text()
        template = [line for line in constraints.splitlines() if "{memory_tx_data[0]}" in line]
        assert len(template) == 3 and sum(line.startswith("set_output_delay") for line in template) == 1
        new_sdc = out / old.name
        new_sdc.write_text(constraints + "\n" + "\n".join(
            line.replace("memory_tx_data[0]", f"memory_tx_data[{bit}]")
            for bit in range(8, 22) for line in template) + "\n")
        pin(new_sdc)
    for path in (candidate, seed, Path(__file__).resolve()):
        pin(path)
    return {
        "state": "wide_request_whole_chip_placement_seed_checked",
        "candidate_sha256": digest(candidate),
        "matched_component_names_and_masters": count,
        "sorted_inventory_sha256": inventory_digest,
        "reserved_pad_sites": len(plan["pad_slots"]),
        "logical_pins": len(ports), "retained_pin_positions": 484,
        "unchanged_memory_halos": 631, "moved_memory_macros": len(plan["moved_macros"]),
        "remaining_sites": remaining, "cell_positions": counters,
        "added_constraint_commands_per_view": 42,
        "scope": "Offline exact placement coordinates and logical component inventory. Pads are geometric "
                 "reservations. The added request data pins use existing port shapes and M5 tracks. "
                 "Innovus import, pad cells, routing and timing remain to be verified.",
        "evidence_sha256": evidence,
    }


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").is_file()
    with Path("/proc/meminfo").open() as stream:
        assert next(int(line.split()[1]) for line in stream if line.startswith("MemAvailable:")) >= 8 * 1024**2
    print(json.dumps(run(), indent=2, sort_keys=True))
