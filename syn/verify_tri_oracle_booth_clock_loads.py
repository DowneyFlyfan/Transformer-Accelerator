"""Measure library-identified clock loads on the exact cold-reloaded chip."""

from collections import Counter
from decimal import Decimal
from functools import cache
import json
import mmap
from pathlib import Path
import re

from link_tri_oracle_indexed_whole_chip import signature, spans
from verify_tri_oracle_booth_chip_link import named_bindings
from verify_tri_oracle_booth_clock_boundary import PLACEMENT
from verify_tri_oracle_corrected_booth_roundtrip import ROOT, TOP, digest
from verify_tri_oracle_serialized_placement_transfer import INSTANCE, MEMORIES


CLOCK_BOUNDARY = Path("records/tri_oracle_corrected_booth_clock_boundary.json")
MODELS = Path("records/tri_oracle_corrected_booth_buffered_models.json")
ARRAY = re.compile(rb"tri_oracle_pe_array_verified_bank[0-4](?:_[1-3])?")
CELL = re.compile(rb"(?m)^[ \t]*cell\s*\(\s*\"?([\w$]+)\"?\s*\)\s*\{")
PIN = re.compile(rb"(?m)^[ \t]*pin\s*\(\s*\"?([\w$]+)\"?\s*\)\s*\{")
CLOCK = re.compile(rb'(?m)^[ \t]*clock\s*:\s*"?true"?\s*;')
CAPACITANCE = re.compile(rb"(?m)^[ \t]*capacitance\s*:\s*([0-9.eE+-]+)\s*;")
DIRECTION = re.compile(rb"(?m)^[ \t]*direction\s*:\s*input\s*;")


def library_clocks(path):
    text = path.read_bytes()
    assert re.search(rb"capacitive_load_unit\s*\(\s*1\s*,\s*pf\s*\)", text)
    entries = {}
    cells = list(CELL.finditer(text))
    assert cells
    for index, cell in enumerate(cells):
        end = cells[index + 1].start() if index + 1 < len(cells) else len(text)
        ports = list(PIN.finditer(text, cell.end(), end))
        clock_pins = {}
        for position, port in enumerate(ports):
            limit = ports[position + 1].start() if position + 1 < len(ports) else end
            if CLOCK.search(text, port.end(), limit) is None:
                continue
            assert DIRECTION.search(text, port.end(), limit), (path, cell[1], port[1])
            match, = CAPACITANCE.finditer(text, port.end(), limit)
            assert port[1] not in clock_pins
            clock_pins[port[1]] = (1, Decimal(match[1].decode()))
        assert cell[1] not in entries
        entries[cell[1]] = clock_pins
    return entries


def clock_inventory(source, library):
    modules = {name.encode(): bounds for name, bounds in spans(source).items()}
    arrays = set()

    @cache
    def scan(master):
        first, last = modules[master]
        input_loads = {}
        named_loads = {}
        totals = Counter()
        header = source.find(b");", first, last)
        assert header != -1, master
        # The names of input pins are needed only on modules with clock loads.
        for instance in INSTANCE.finditer(source, header + 2, last):
            child = instance[1]
            if child in library:
                standardized = "memory_macros" if child.startswith(MEMORIES) else "standard_cells"
                totals[standardized] += 1
                clock_pins = library[child]
                totals["clock_pins"] += len(clock_pins)
            else:
                child_totals, clock_pins = scan(child)
                totals.update(child_totals)
            if not clock_pins:
                continue
            start = source.find(b"(", instance.start(), instance.end()) + 1
            end = source.find(b");", instance.end(), last)
            assert 0 < start < end, (master, instance[2])
            assigned = named_bindings(source[start:end])
            for pin, (count, cap) in clock_pins.items():
                wire = assigned[pin.decode()]
                assert wire, (master, instance[2], pin)
                old_count, old_cap = named_loads.get(wire, (0, Decimal(0)))
                named_loads[wire] = (old_count + count, old_cap + cap)
        if named_loads:
            ports = signature(source[first:last])
            input_loads = {
                name.encode(): named_loads[name.encode()]
                for name, (direction, width) in ports.items()
                if direction == b"input" and not width and name.encode() in named_loads
            }
        if ARRAY.fullmatch(master):
            arrays.add(master)
        return totals, input_loads

    totals, top = scan(TOP.encode())
    assert len(arrays) == 20
    loads = {}
    for array in sorted(arrays):
        array_totals, inputs = scan(array)
        count, cap = inputs[b"clk"]
        loads[array.decode()] = {
            "direct_clk_clock_pins": count,
            "direct_clk_typical_liberty_capacitance_pf": str(cap),
            "all_clock_pins_in_array": array_totals["clock_pins"],
        }
    return totals, top[b"clk"], loads


def verify():
    placement, models, boundary = (json.loads(path.read_text()) for path in (PLACEMENT, MODELS, CLOCK_BOUNDARY))
    checksum = placement["database_fingerprint_sha256"]
    assert checksum == models["database_fingerprint_sha256"] == boundary["database_fingerprint_sha256"]
    database = Path(placement["database"])
    netlist = database.parents[1] / "cold/cold.v"
    evidence = {}

    def pin(path, expected=None):
        actual = digest(path)
        assert expected is None or actual == expected, path
        evidence[str(path)] = actual

    pin(netlist, boundary["cold_netlist_sha256"])
    assert evidence[str(netlist)] == placement["evidence_sha256"][str(netlist)]
    library = {}
    libraries = sorted((database / "libs/mmmc").glob("*tt1v25c.lib"))
    assert len(libraries) == 7
    for path in libraries:
        pin(path, models["evidence_sha256"][str(path)])
        cells = library_clocks(path)
        assert not library.keys() & cells.keys()
        library.update(cells)
    with netlist.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as source:
        totals, (root_count, root_cap), arrays = clock_inventory(source, library)
    assert totals["standard_cells"] == placement["geometry"]["standard_cells"]
    assert totals["memory_macros"] == placement["geometry"]["fixed_memory_macros"]
    assert 0 < sum(row["direct_clk_clock_pins"] for row in arrays.values()) <= root_count <= totals["clock_pins"]
    for path in (PLACEMENT, MODELS, CLOCK_BOUNDARY, Path(__file__).resolve().relative_to(ROOT)):
        pin(path)
    return {
        "state": "repaired_booth_placed_clock_pin_inventory_verified",
        "database_fingerprint_sha256": checksum,
        "cold_netlist_sha256": evidence[str(netlist)],
        "total_clock_pins": totals["clock_pins"],
        "direct_external_clk_clock_pins": root_count,
        "direct_external_clk_typical_liberty_capacitance_pf": str(root_cap),
        "arrays": arrays,
        "scope": "Clock inputs come from the placed candidate's typical-corner Liberty timing models. "
                 "Direct counts follow the same named net through scalar input ports. Capacitance is the "
                 "sum of nominal terminal capacitances, prior to clock-tree synthesis and wire extraction.",
        "evidence_sha256": evidence,
    }


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").is_file()
    print(json.dumps(verify(), indent=2, sort_keys=True))
