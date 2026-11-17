"""Bind clock-pin capacitance to legal row capacity on both wide-write placements."""

from bisect import bisect_right
from collections import Counter
from decimal import Decimal
from functools import cache
import json
from mmap import ACCESS_READ, mmap
from pathlib import Path
import re

from audit_tri_oracle_placed_chip_boundary import TOP
from link_tri_oracle_indexed_whole_chip import signature, spans
from verify_tri_oracle_booth_chip_link import named_bindings
from verify_tri_oracle_booth_clock_loads import CELL, PIN, library_clocks
from verify_tri_oracle_pad_cold_reload import components
from verify_tri_oracle_serialized_placement_transfer import INSTANCE
from verify_tri_oracle_value_register_clock_rows import INPUTS, MASTERS, ROOT, linked_file, pin


ROW_RECORD = Path("records/tri_oracle_value_register_clock_rows.json")
CORNERS = {"slow": "ssg0p9v125c.lib", "typical": "tt1v25c.lib", "fast": "ffg1p05vm40c.lib"}
VIEW_PATH = re.compile(r"(?m)^#@ Begin verbose source (.+/views\.tcl) \(pre\)$")
LIB_HOME = re.compile(r"(?m)^set ::IMEX::dataVar \{([^}]+)\}$")
LIBS = re.compile(r"\$\{::IMEX::libVar\}/mmmc/(\S+\.lib)\b")
OUTPUT = re.compile(rb"(?m)^\s*direction\s*:\s*output\s*;")
MAX_CAP = re.compile(rb"(?m)^\s*max_capacitance\s*:\s*([0-9.eE+-]+)\s*;")
CAP_SCALE = 10 ** 12


def fixed_units(capacitance):
    value = capacitance * CAP_SCALE
    assert value == int(value) and value > 0
    return int(value)


def pfs(value):
    return str(Decimal(value) / CAP_SCALE)


def buffer_limits(liberty):
    result = {}
    masters = {name + "BWP12T40P140": name for name in MASTERS}
    with liberty.open("rb") as stream, mmap(stream.fileno(), 0, access=ACCESS_READ) as text:
        cells = list(CELL.finditer(text))
        for index, cell in enumerate(cells):
            master = masters.get(cell[1].decode())
            if master is None:
                continue
            end = cells[index+1].start() if index+1 < len(cells) else len(text)
            pins = list(PIN.finditer(text, cell.end(), end))
            limits = []
            for i, port in enumerate(pins):
                stop = pins[i+1].start() if i+1 < len(pins) else end
                if OUTPUT.search(text, port.end(), stop):
                    limit, = MAX_CAP.findall(text, port.end(), stop)
                    assert port[1] == b"Z"
                    limits.append(fixed_units(Decimal(limit.decode())))
            result[master], = limits
    assert set(result) == set(MASTERS)
    return result


def clock_models(views, evidence):
    text = views.read_text()
    data_home = Path(LIB_HOME.search(text)[1]).relative_to(ROOT)
    paths = [data_home / "libs/mmmc" / name for name in LIBS.findall(text)]
    assert len(paths) == len(set(paths)) == 21
    by_corner, limits = {}, {}
    for corner, suffix in CORNERS.items():
        entries = {}
        libraries = [path for path in paths if path.name.endswith(suffix)]
        assert len(libraries) == 7
        for path in libraries:
            lib = library_clocks(pin(path, evidence))
            assert not entries.keys() & lib.keys()
            entries.update(lib)
            if path.name.startswith("tcbn28"):
                assert corner not in limits
                limits[corner] = buffer_limits(path)
        by_corner[corner] = entries
    assert limits.keys() == CORNERS.keys()
    typical = by_corner["typical"]
    assert all(view.keys() == typical.keys() for view in by_corner.values())
    model = {}
    for cell, terminals in typical.items():
        assert all(view[cell].keys() == terminals.keys() for view in by_corner.values())
        model[cell] = {port: (1, *(fixed_units(by_corner[corner][cell][port][1])
                                    for corner in CORNERS)) for port in terminals}
    return model, limits


def add(a, b):
    return tuple(left + right for left, right in zip(a, b, strict=True))


def direct_clock_loads(source, model):
    definitions = {name.encode(): bounds for name, bounds in spans(source).items()}
    zero = (0,) * (1 + len(CORNERS))

    @cache
    def scan(master):
        start, stop = definitions[master]
        header = source.find(b");", start, stop)
        assert header >= 0
        ports = signature(source[start:stop])
        inputs = {name.encode() for name, (direction, vector) in ports.items()
                  if direction == b"input" and not vector}
        branches, sums = {}, {}
        for instance in INSTANCE.finditer(source, header+2, stop):
            child, name = instance.groups()
            leaf = child in model
            if leaf:
                clock_ports = model[child]
            else:
                clock_ports = scan(child)[1]
            if not clock_ports:
                continue
            at = source.find(b"(", instance.start(), instance.end()) + 1
            end = source.find(b");", instance.end(), stop)
            assert at < end
            bindings = named_bindings(source[at:end])
            qualified_name = name.removeprefix(b"\\")
            for port, cap in clock_ports.items():
                link = bindings[port.decode()]
                if link in inputs:
                    branches.setdefault(link, []).append((qualified_name, child, leaf, port))
                    sums[link] = add(sums.get(link, zero), cap)
        return branches, sums

    leaves = {}

    def walk(master, port, prefix):
        for name, child, leaf, child_port in scan(master)[0][port]:
            path = prefix + name
            if leaf:
                old_master, old_load = leaves.get(path, (child, zero))
                assert old_master == child
                leaves[path] = child, add(old_load, model[child][child_port])
            else:
                walk(child, child_port, path+b"/")

    root = TOP.encode()
    aggregate = scan(root)[1][b"clk"]
    walk(root, b"clk", b"")
    scan.cache_clear()
    assert aggregate == tuple(map(sum, zip(*(load for _, load in leaves.values()), strict=True)))
    return leaves, aggregate


def place_loads(layout, loads, regions):
    left = sorted({box[0] for box in regions.values()})
    bottom = sorted({box[1] for box in regions.values()})
    names = {(box[0], box[1]): name for name, box in regions.items()}
    assert len(left) * len(bottom) == len(names) == len(regions)
    meters = {name: Counter() for name in regions}
    for name, (master, status, x, y, _, _) in components(layout):
        key = name.replace(b"\\[", b"[").replace(b"\\]", b"]")
        value = loads.pop(key, None)
        if value is None:
            continue
        expected, (pins, *caps) = value
        assert master.encode() == expected, (name, master, expected)
        column, row = bisect_right(left, x)-1, bisect_right(bottom, y)-1
        region = names[left[column], bottom[row]]
        lx, by, rx, ty = regions[region]
        assert lx <= x < rx and by <= y < ty
        meters[region].update(pins=pins, leaves=1, fixed=int(status == "FIXED"))
        meters[region].update(dict(zip(CORNERS, caps, strict=True)))
    assert not loads, (len(loads), list(loads)[:10])
    return meters


def compare_capacity(meters, limits, room):
    regions = {}
    for name, meter in meters.items():
        capacity = room[name]["copies_that_fit_by_master"]
        detail = {}
        for master in MASTERS:
            floor = max((meter[corner] + limit[master] - 1) // limit[master]
                        for corner, limit in limits.items())
            detail[master] = {
                "minimum_local_leaf_outputs": floor,
                "existing_contiguous_slots": capacity[master],
                "shortfall_before_wire_load": max(0, floor - capacity[master]),
            }
        regions[name] = {
            "direct_clock_pins": meter["pins"],
            "clocked_component_instances": meter["leaves"],
            "fixed_clocked_memory_macros": meter["fixed"],
            "pin_capacitance_by_corner_pf": {corner: pfs(meter[corner]) for corner in CORNERS},
            "single_master_scenarios": detail,
        }
    return regions


def verify():
    evidence = {}
    row_record = json.loads(pin(ROW_RECORD, evidence).read_text())
    models, views, results = None, None, {}
    for label, (path, receipt_suffix, layout_suffix, _) in INPUTS.items():
        placement = json.loads(pin(path, evidence).read_text())
        receipt = json.loads(linked_file(placement, receipt_suffix, evidence).read_text())
        design = linked_file(receipt, "/cold.v", evidence)
        layout = linked_file(receipt, layout_suffix, evidence)
        assert evidence[str(design)] == row_record["placement"][label]["cold_netlist_sha256"]
        assert evidence[str(layout)] == row_record["evidence_sha256"][str(layout)]
        console_suffix = "/cold/console.log" if label == "resized" else "/native/console.log"
        console = linked_file(receipt, console_suffix, evidence).read_text()
        observed = VIEW_PATH.findall(console)
        if label == "resized":
            # The cold session reads the saved database, whose physical import used these same views.
            original = linked_file(receipt, "/import/console.log", evidence)
            observed = VIEW_PATH.findall(original.read_text())
        native_views, = set(observed)
        native_views = Path(native_views).relative_to(ROOT)
        if models is None:
            views = pin(native_views, evidence)
            models, limits = clock_models(views, evidence)
        else:
            assert native_views == views

        with design.open("rb") as stream, mmap(stream.fileno(), 0, access=ACCESS_READ) as source:
            loads, total = direct_clock_loads(source, models)
        leaf_count = len(loads)
        meters = place_loads(layout, loads, row_record["comparison_regions"])
        assert tuple(sum(meter[k] for meter in meters.values()) for k in ("pins", *CORNERS)) == total
        assert sum(meter["leaves"] for meter in meters.values()) == leaf_count
        results[label] = {
            "cold_netlist_sha256": evidence[str(design)],
            "direct_clock_pins": total[0],
            "clocked_component_instances": leaf_count,
            "direct_pin_capacitance_by_corner_pf": dict(zip(CORNERS, map(pfs, total[1:]), strict=True)),
            "regions": compare_capacity(meters, limits, row_record["placement"][label]["region_details"]),
        }
    pin(Path(__file__).resolve().relative_to(ROOT), evidence)
    return {
        "state": "wide_write_placement_direct_clock_pin_load_and_contiguous_row_capacity_verified",
        "candidate": results,
        "master_max_output_capacitance_pf": {
            corner: {master: pfs(value) for master, value in corner_limits.items()}
            for corner, corner_limits in limits.items()
        },
        "scope": ("Physical region origin of every mapped direct root-clock input and nominal library "
                  "pin capacitive load. The local leaf-output floor assigns each region's direct pins "
                  "to its own clock branches, using one selected master at a time. Wire load, slew, "
                  "clock skew, clock-tree synthesis, and routing require separate verification."),
        "evidence_sha256": evidence,
    }


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT
    print(json.dumps(verify(), indent=2, sort_keys=True))
