"""Check the physical and timing views for every leaf in a mapped cluster."""

import argparse
from collections import Counter
from decimal import Decimal
import json
from pathlib import Path
import re

from prepare_tri_oracle_wac_outlier_layer import ROOT, read, sha, verify
from prepare_mapped_cluster_fixture import STAGE, module_text
from check_macro_physical_views import lef_pins

CELL = re.compile(r'^\s*cell\s*\(\s*"?(\w+)"?\s*\)')
INSTANCE = re.compile(r"(?m)^[ \t]+(\w+)\s+(?:\\\S+|\w+)\s*\(")
MACRO = re.compile(r"^\s*MACRO\s+(\w+)\s*$")
SIZE = re.compile(r"^\s*SIZE\s+(\d+(?:\.\d+)?)\s+BY\s+(\d+(?:\.\d+)?)\s*;")
CORNERS = ("ssg0p9v125c", "tt1v25c", "ffg1p05vm40c")
PHYSICAL = ROOT / ".cache/physical"


def leaf_counts(netlist, top):
    modules = module_text(netlist.read_text())
    assert top in modules
    children = {name: Counter(INSTANCE.findall(module[0])) for name, module in modules.items()}
    visited = {}

    def expand(module, parents):
        assert module not in parents, (module, parents)
        if module not in visited:
            leaves = Counter()
            for master, instances in children[module].items():
                if master in modules:
                    for leaf, count in expand(master, parents | {module}).items():
                        leaves[leaf] += count * instances
                else:
                    leaves[master] += instances
            visited[module] = leaves
        return visited[module]

    return expand(top, set())


def library_masters(path):
    with path.open() as stream:
        return {match[1] for line in stream if (match := CELL.match(line))}


def abstract_areas(path):
    areas = {}
    name = None
    with path.open() as stream:
        for line in stream:
            if match := MACRO.match(line):
                assert name is None and match[1] not in areas
                name = match[1]
            elif name is not None and (match := SIZE.match(line)):
                width, height = map(Decimal, match.groups())
                assert width > 0 and height > 0
                areas[name] = width * height
                name = None
    assert name is None and areas
    return areas


def audit(mapping):
    receipt_path = mapping / "receipt.json"
    result = read(receipt_path)
    assert result["state"] == "cluster_mapped_around_four_verified_cores"
    assert result["native"]["native_exit_status"] == 0
    assert result["native"]["log_sha256"] == sha(mapping / "console.log")
    pins = result["input_sha256"].copy()
    for name, digest in result["output_sha256"].items():
        path = str(mapping / name)
        assert pins.get(path, digest) == digest
        pins[path] = digest
    verify(pins)

    top = result["top"]
    masters = leaf_counts(mapping / "netlist.v", top)
    assert all(count > 0 for count in masters.values())
    memory = {name: count for name, count in masters.items() if name.startswith(("TS5N28", "TS6N28"))}
    assert memory == result["compiled_memories"]
    area_report = (mapping / "area.rpt").read_text()
    area_line = re.search(rf"(?m)^{re.escape(top)}\s+NA\s+(\d+)\s+(\d+(?:\.\d+)?)", area_report)
    assert area_line and sum(masters.values()) == int(area_line[1]), (sum(masters.values()), area_line)

    corner_path = STAGE / "paper_operating_view_inventory.json"
    view_path = STAGE / "memory_physical_view_interfaces.json"
    assert all(pins[str(path)] == sha(path) for path in (corner_path, view_path))
    corners = read(corner_path)["common_corners"]
    views = read(view_path)["macros"]
    physical_inputs = [Path(__file__), receipt_path, mapping / "console.log"]
    standard = PHYSICAL / "library/tcbn28hpcplusbwp12t40p140.lef"
    areas = abstract_areas(standard)
    physical_inputs.append(standard)
    for corner in CORNERS:
        libs = [Path(path) for path in corners[corner]["files"]]
        assert len(libs) == 7
        cells = library_masters(libs[0])
        physical_inputs.extend(libs)
        seen_memory = set()
        for lib in libs[1:]:
            master, = library_masters(lib)
            assert master not in seen_memory and sha(lib) == views[master]["timing_sha256"][corner]
            seen_memory.add(master)
            cells.add(master)
            if corner == CORNERS[0] and master in memory:
                compiler = lib.parent.parent
                lef = compiler / "LEF" / f"{compiler.name}.lef"
                assert sha(lef) == views[master]["abstract_sha256"]
                assert len(lef_pins(lef, master)) == views[master]["functional_pin_bits"]
                geometry = abstract_areas(lef)
                assert geometry.keys() == {master} and master not in areas
                areas.update(geometry)
                physical_inputs.append(lef)
        assert set(masters) <= cells, (corner, sorted(masters.keys() - cells))
    assert set(masters) <= areas.keys(), sorted(masters.keys() - areas.keys())
    area = sum(areas[master] * count for master, count in masters.items())
    for path in physical_inputs:
        digest = sha(path)
        assert pins.get(str(path), digest) == digest, path
        pins[str(path)] = digest
    verify(pins)
    return dict(state="mapped_cluster_physical_and_timing_views_verified", bank=result["bank"], top=top,
        leaf_instances=sum(masters.values()), distinct_masters=len(masters), compiled_memories=memory,
        summed_abstract_area_square_micrometers=float(area), genus_cell_area_square_micrometers=float(area_line[2]),
        timing_view_corners=list(CORNERS), input_sha256=pins,
        scope="Native netlist leaf coverage and installed cell dimensions. This check precedes placement and extracted timing.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("mapping", "output"):
        parser.add_argument(name, type=lambda value: Path(value).resolve())
    args = parser.parse_args()
    result = audit(args.mapping)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(result["state"], result["leaf_instances"], result["distinct_masters"],
          result["summed_abstract_area_square_micrometers"], flush=True)
