"""Measure linked logic and memory footprints against the selected die outline."""

import argparse
from collections import Counter
from contextlib import ExitStack
from decimal import Decimal
from functools import lru_cache
import json
from pathlib import Path
import re

from link_tri_oracle_parallel_chip import INSTANCE, catalog
from prepare_tri_oracle_joined_macro_outline import VIEWS
from prepare_tri_oracle_parallel_chip_synthesis import pin, read, verify
from run_tri_oracle_parallel_chip_synthesis import GIB, memory, wait_for_receipt
from verify_tri_oracle_packed_down_weights import ROOT


MACRO = re.compile(r"(?ms)^MACRO (\w+)\n(.*?)^END \1\s*$")
SIZE = re.compile(r"(?m)^\s*SIZE (\S+) BY (\S+)\s*;")
CELL_AREA = re.compile(r"(?m)^cell\s*\(\s*(\w+)\s*\)\s*\{\s*area\s*:\s*(\S+)\s*;")
MM2 = Decimal(10**6)


def areas(lef):
    footprints = {}
    for match in MACRO.finditer(lef):
        name, text = match.groups()
        width, height = map(Decimal, SIZE.search(text).groups())
        assert name not in footprints and width > 0 and height > 0
        footprints[name] = width * height
    assert footprints
    return footprints


def leaf_counts(modules, known, top):
    active = set()

    @lru_cache(maxsize=None)
    def visit(name):
        assert name not in active, name
        active.add(name)
        counts = Counter()
        source, start, end = modules[name]
        local = Counter(match[1].decode() for match in INSTANCE.finditer(source, start, end))
        for master, instances in local.items():
            if master in modules:
                for leaf, count in visit(master).items():
                    counts[leaf] += count * instances
            else:
                assert master in known, (name, master)
                counts[master] += instances
        active.remove(name)
        return counts

    return visit(top)


def run(linked, outline, output, link_worker=None):
    assert Path("/.dockerenv").is_file()
    receipt = linked / "receipt.json"
    link = read(receipt) if link_worker is None else wait_for_receipt(receipt, link_worker, "link_tri_oracle_joined_chip.py")
    available, anonymous = memory()
    assert available >= 15 * GIB and anonymous <= 6 * GIB, (available, anonymous)
    assert link["state"] in {"parallel_chip_parent_linked_with_verified_mapped_imports",
                              "joined_chip_parent_linked_with_verified_mapped_imports"}
    plan = read(outline)
    assert plan["state"] in {"parallel_chip_macro_outline_preflight", "joined_predictor_macro_outline_geometry_verified"}
    geometry = plan.get("updated_outline", plan)
    macro_area = Decimal(geometry["macro_area_mm2"])
    unoccupied = Decimal(geometry["core_area_outside_macro_halos_mm2"])
    pins = {}
    for path in (receipt, outline, VIEWS, Path(__file__).resolve()):
        pin(pins, path)
    netlist = linked / "chip.v"
    pin(pins, netlist, link["chip_sha256"])
    views = read(VIEWS)
    _, standard, *memories = views["physical_abstracts"]
    for name in (standard, *memories):
        pin(pins, ROOT / name, views["evidence_sha256"][name])
    logic = areas((ROOT / standard).read_text())
    memory_area = {}
    for name in memories:
        area = areas((ROOT / name).read_text())
        assert len(area) == 1 and not (memory_area.keys() & area.keys())
        memory_area.update(area)
    assert not logic.keys() & memory_area.keys()
    inventory, = (name for name in views["evidence_sha256"] if name.endswith("liberty_corner_inventory.json"))
    pin(pins, ROOT / inventory, views["evidence_sha256"][inventory])
    slow = read(ROOT / inventory)["timing_views"]["ssg0p9v125c"]["library_sha256"]
    library, = (name for name in slow if Path(name).parent.name == "library")
    pin(pins, ROOT / library, slow[library])
    liberty = {name: Decimal(area) for name, area in CELL_AREA.findall((ROOT / library).read_text())}
    with ExitStack() as stack:
        counts = leaf_counts(catalog(stack, netlist), logic.keys() | memory_area.keys(), link["top"])
    actual_memories = {name: count for name, count in counts.items() if name in memory_area}
    assert actual_memories == link["compiled_memories"]
    assert sum(memory_area[name] * count for name, count in actual_memories.items()) / MM2 == macro_area
    logic_counts = {name: count for name, count in counts.items() if name in logic}
    assert logic_counts and all(logic[name] == liberty[name] for name in logic_counts)
    logic_area = sum(logic[name] * count for name, count in logic_counts.items()) / MM2
    verify(pins)
    result = {"state": "linked_chip_floorplan_area_measured", "candidate_sha256": link["chip_sha256"],
              "die_um": plan["die_um"], "compiled_memories": sum(actual_memories.values()),
              "logic_cells": sum(logic_counts.values()), "used_logic_masters": len(logic_counts),
              "logic_cell_area_mm2": str(logic_area), "macro_area_mm2": str(macro_area),
              "core_area_outside_macro_halos_mm2": str(unoccupied),
              "raw_logic_fraction_of_core_outside_halos": float(logic_area / unoccupied),
              "scope": "Linked instance footprints before placement, clock distribution, power grid, or routing.",
              "input_sha256": pins}
    with output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(result["state"], result["logic_cells"], logic_area, macro_area, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("linked", "outline", "output"):
        parser.add_argument(name, type=lambda value: Path(value).resolve())
    parser.add_argument("--link-worker", type=int)
    run(**vars(parser.parse_args()))
