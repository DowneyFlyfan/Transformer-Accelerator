"""Screen exact mapped local nets for pin load above the slow-corner Liberty limit."""

from argparse import ArgumentParser
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from decimal import Decimal
from functools import cache
from hashlib import file_digest
from multiprocessing import get_context
from pathlib import Path
import json
import mmap
import re
import resource
import subprocess
import sys

from link_tri_oracle_indexed_whole_chip import spans
from plan_tri_oracle_grouped_reset import read_library
from verify_tri_oracle_booth_chip_native_connectivity import REFERENCE_TOOLS, normalize_module
from audit_tri_oracle_booth_operand_spans import CELL
from verify_tri_oracle_booth_chip_link import INSTANCE, named_bindings
from verify_tri_oracle_pad_cold_reload import components


ROOT = Path(__file__).resolve().parents[1]
sys.path.extend(str(ROOT / path) for path in REFERENCE_TOOLS)
from verify_tri_oracle_placement_connectivity import bits, pin_fields, read_module


PLACEMENT = ROOT / "records/tri_oracle_corrected_booth_placement_roundtrip.json"
MODELS = ROOT / "records/tri_oracle_corrected_booth_physical_models.json"
CAPACITANCE_SCALE = 10**12  # Work in integer units of 1e-12 picofarads.
MINIMUM_SINKS = 64


def digest(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def capacitance(value):
    exact = Decimal(value) * CAPACITANCE_SCALE
    assert int(exact) == exact and exact >= 0
    return int(exact)


def pin_models(path):
    # Only this standard-cell library contributes pin loads. Unsupported
    # connections are excluded during traversal, including SRAM terminals.
    with path.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as source:
        names = {name.decode() for name in re.findall(rb"(?m)^cell\s*\(([^)]+)\)\s*\{", source)}
    raw = read_library(path, names)
    models = {name: {} for name in names}
    for (master, pin), attrs in raw.items():
        limit = None
        if attrs.get("direction") == "input":
            options = [capacitance(attrs[name]) for name in
                       ("capacitance", "rise_capacitance", "fall_capacitance") if name in attrs]
            if options:
                limit = min(options)
        elif attrs.get("direction") == "output" and "max_capacitance" in attrs:
            limit = capacitance(attrs["max_capacitance"])
        models.setdefault(master, {})[pin] = (attrs.get("direction"), limit)
    assert names == models.keys() and any(models.values())
    return models


def exclude(wires, expressions, blocked):
    for expression in expressions:
        expanded = bits(expression, wires)
        assert expanded or not expression, expression
        blocked.update(expanded)


def scan_module(source, library, threshold):
    _, ports, wires, instances, assignments = read_module(normalize_module(source))
    # External ports, any continuous assignment, and every unresolved child
    # connection may introduce additional drivers or aliases. Exclude the
    # exact affected bits from the single-driver proof.
    blocked = set()
    for name, (_, shape) in ports.items():
        if shape is None:
            blocked.add(("scalar", name))
        else:
            blocked.update(("vector", name, bit) for bit in range(min(shape), max(shape) + 1))
    for pair in assignments:
        exclude(wires, pair, blocked)
    drivers, multiple_drivers, sinks, sink_cap = {}, set(), Counter(), Counter()
    child_counts = Counter()
    for name, (master, fields) in instances.items():
        child_counts[master] += 1
        pins = pin_fields(fields)
        known = library.get(master)
        if known is None:
            exclude(wires, pins.values(), blocked)
            continue
        for pin, expression in pins.items():
            if not expression:
                continue
            expanded = bits(expression, wires)
            assert expanded, (master, pin, expression)
            if len(expanded) != 1 or pin not in known:
                blocked.update(expanded)
                continue
            net, = expanded
            # Constants cannot be driven local nets.
            if net[0] == "constant":
                continue
            direction, cap = known[pin]
            if direction == "output":
                if net in drivers:
                    multiple_drivers.add(net)
                drivers[net] = (name, master, pin, cap)
            elif direction == "input" and cap is not None:
                sinks[net] += 1
                sink_cap[net] += cap
            else:
                blocked.add(net)
    checked, violations = 0, []
    for net, count in sinks.items():
        if count < threshold or net in blocked or net in multiple_drivers or net not in drivers:
            continue
        name, master, pin, cap = drivers[net]
        if not cap:
            continue
        checked += 1
        load = sink_cap[net]
        if load > cap:
            net_name = net[1] if net[0] == "scalar" else f"{net[1]}[{net[2]}]"
            violations.append(dict(net=net_name, driver_instance=name, master=master, driver_pin=pin,
                                   sinks=count, pin_load_lower_pf=load / CAPACITANCE_SCALE,
                                   driver_limit_pf=cap / CAPACITANCE_SCALE,
                                   lower_bound_ratio=load / cap))
    return child_counts, checked, violations


def init_worker(path, library, threshold):
    global netlist, pin_library, minimum_sinks
    # The structural parser imports tools with large shared virtual mappings.
    # Bound this worker's extra address space after those imports.
    inherited = next(int(line.split()[1]) * 1024 for line in Path("/proc/self/status").read_text().splitlines()
                     if line.startswith("VmSize:"))
    limit = inherited + path.stat().st_size + 384 * 1024**2
    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    with path.open("rb") as stream:
        netlist = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
    pin_library = library
    minimum_sinks = threshold


def scan_range(bounds):
    first, last = bounds
    return scan_module(netlist[first:last], pin_library, minimum_sinks)


def reachable_summaries(top, modules):
    def walk(module, ancestry):
        assert module not in ancestry, module
        reachable = Counter({module: 1})
        for child, instances in modules[module][0].items():
            if child in modules:
                for descendant, count in walk(child, ancestry | {module}).items():
                    reachable[descendant] += count * instances
        return reachable

    return walk(top, set())


def verify_worst_locations(source, layout, top, reachable, nets, library):
    """Recount the worst sinks from named bindings and find their placed origins."""
    by_module = defaultdict(list)
    for net in nets:
        by_module[net["module"]].append(net)
    parents = defaultdict(list)
    endpoints = {}
    with source.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
        definitions = spans(data)
        reachable_names = {name.encode() for name in reachable}
        for module in reachable:
            for ref in INSTANCE.finditer(data, *definitions[module]):
                master, name = ref.groups()
                if master in reachable_names:
                    parents[master.decode()].append((module, name.decode().removeprefix("\\")))
        for module, rows in by_module.items():
            keys = {row["net"].encode(): row for row in rows}
            hits = defaultdict(list)
            for master, name, fields in CELL.findall(data, *definitions[module]):
                roles = library.get(master.decode(), {})
                for pin, signal in named_bindings(fields).items():
                    if signal in keys:
                        direction, cap = roles[pin]
                        hits[signal].append((name.decode().removeprefix("\\"), master.decode(), pin, direction, cap))
            for key, row in keys.items():
                found = hits[key]
                (driver,) = (entry for entry in found if entry[3] == "output")
                assert driver[:3] == (row["driver_instance"], row["master"], row["driver_pin"]), row
                loads = [entry for entry in found if entry[3] == "input"]
                assert len(loads) == row["sinks"]
                assert all(entry[-1] is not None for entry in loads)
                assert sum(entry[-1] for entry in loads) / CAPACITANCE_SCALE == row["pin_load_lower_pf"]
                assert driver[-1] / CAPACITANCE_SCALE == row["driver_limit_pf"]
                endpoints[module, row["net"]] = (driver, loads)

    @cache
    def paths(module):
        if module == top:
            return ("",)
        return tuple(prefix + child + "/" for owner, child in parents[module] for prefix in paths(owner))

    placed_names = set()
    for row in nets:
        parents_for_row = paths(row["module"])
        assert len(parents_for_row) == row["physical_occurrences"]
        driver, sinks = endpoints[row["module"], row["net"]]
        placed_names.update((prefix + entry[0]).encode() for prefix in parents_for_row for entry in (driver, *sinks))
    locations = {name.replace(b"\\", b""): pose for name, pose in components(layout)
                 if name.replace(b"\\", b"") in placed_names}
    assert locations.keys() == placed_names
    with layout.open("rb") as stream:
        (units,) = re.findall(rb"(?m)^UNITS DISTANCE MICRONS (\d+) ;$", stream.read(4096))
    physical_nets = []
    for row in nets:
        driver, sinks = endpoints[row["module"], row["net"]]
        distance = 0
        for prefix in paths(row["module"]):
            def details(entry):
                name, master, pin, _, _ = entry
                physical_name = prefix + name
                placed_master, status, x, y, _, _ = locations[physical_name.encode()]
                assert master == placed_master and status == "PLACED", physical_name
                return dict(name=physical_name, master=master, pin=pin, x=x, y=y)

            physical_driver = details(driver)
            physical_sinks = [details(sink) for sink in sinks]
            distance = max(distance, max(abs(physical_driver["x"] - sink["x"]) + abs(physical_driver["y"] - sink["y"])
                                         for sink in physical_sinks))
            physical_nets.append(dict(module=row["module"], net=row["net"], driver=physical_driver,
                                      sinks=physical_sinks))
        row["driver_hierarchy"] = paths(row["module"])[0] + driver[0]
        row["furthest_sink_origin_manhattan_um"] = distance / int(units)
    return physical_nets


def verify(workers, endpoint_inventory=None):
    evidence = {}

    def pin(path, expected=None):
        actual = digest(path)
        assert expected is None or actual == expected, path
        evidence[str(path.relative_to(ROOT))] = actual
        return path

    placed = json.loads(pin(PLACEMENT).read_text())
    physical = json.loads(pin(MODELS).read_text())
    assert placed["state"] == "corrected_booth_placement_reload_and_connectivity_verified"
    assert physical["database_fingerprint_sha256"] == placed["database_fingerprint_sha256"]
    database = ROOT / placed["database"]
    source = database.parents[1] / "cold/cold.v"
    pin(source, physical["cold_netlist_sha256"])
    layout = source.with_name("layout.def")
    pin(layout, placed["evidence_sha256"][str(layout.relative_to(ROOT))])
    (library_file,) = (
        name for name in physical["liberty_models_by_corner"]["slow"] if name.startswith("tcbn")
    )
    lib = database / "libs/mmmc" / library_file
    pin(lib, physical["evidence_sha256"][str(lib.relative_to(ROOT))])
    models = pin_models(lib)
    with source.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
        definitions = spans(data)
    with ProcessPoolExecutor(max_workers=workers, mp_context=get_context("fork"),
                             initializer=init_worker, initargs=(source, models, MINIMUM_SINKS)) as pool:
        scanned = dict(zip(definitions, pool.map(scan_range, definitions.values(), chunksize=1), strict=True))
    reachable = reachable_summaries(placed["top"], scanned)
    leaf_count = sum(occurrences * sum(count for master, count in scanned[name][0].items()
                                       if master not in scanned) for name, occurrences in reachable.items())
    assert leaf_count == placed["geometry"]["standard_cells"] + placed["geometry"]["fixed_memory_macros"]
    known_nets = sum(scanned[name][1] * count for name, count in reachable.items())
    violated = sum(len(scanned[name][2]) * count for name, count in reachable.items())
    distinct = [dict(module=name, physical_occurrences=count, **net)
                for name, count in reachable.items() for net in scanned[name][2]]
    distinct.sort(key=lambda net: (-net["lower_bound_ratio"], net["module"], net["net"]))
    worst = distinct[:12]
    physical_nets = verify_worst_locations(source, layout, placed["top"], reachable,
                                            distinct if endpoint_inventory else worst, models)
    grouping = {name: len(scanned[name][2]) * count for name, count in reachable.items() if scanned[name][2]}
    assert sum(grouping.values()) == violated
    for function in (read_library, normalize_module, read_module, bits, named_bindings, components):
        pin(Path(function.__code__.co_filename))
    pin(Path(__file__).resolve())
    if endpoint_inventory:
        assert len(physical_nets) == violated
        with endpoint_inventory.open("x") as stream:
            json.dump(dict(cold_netlist_sha256=physical["cold_netlist_sha256"],
                           layout_sha256=evidence[str(layout.relative_to(ROOT))],
                           overloaded_nets=physical_nets, evidence_sha256=evidence), stream, sort_keys=True)
            stream.write("\n")
    return dict(state="corrected_booth_pin_only_load_lower_bounds_screened",
                cold_netlist_sha256=physical["cold_netlist_sha256"],
                slow_corner="ssg0p9v125c", minimum_direct_sinks=MINIMUM_SINKS, workers=workers,
                reachable_module_definitions=len(reachable), physical_leaf_instances=leaf_count,
                checked_physical_nets=known_nets,
                over_limit_physical_nets=violated, over_limit_by_module=grouping, worst_local_nets=worst,
                scope="Fully resolved local single-driver standard-cell nets with at least 64 direct sinks. The sum uses the smallest modeled input capacitance across listed transitions. Wire load, cross-hierarchy nets, and path delays require separate analysis.",
                evidence_sha256=evidence)


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    available_cores = int(subprocess.check_output(["nproc"], text=True))
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=available_cores)
    parser.add_argument("--endpoint-inventory", type=Path)
    options = parser.parse_args()
    assert 1 <= options.workers <= available_cores
    if options.endpoint_inventory:
        assert options.endpoint_inventory.resolve().is_relative_to(ROOT / ".cache")
    print(json.dumps(verify(options.workers, options.endpoint_inventory), indent=2, sort_keys=True))
