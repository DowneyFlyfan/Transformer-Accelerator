"""Plan five load-checked reset buffer trees from the cold placed database."""

import argparse
from collections import Counter
import csv
from decimal import Decimal
from hashlib import file_digest
import json
from pathlib import Path
import re

from tri_oracle_controller255_tree import plan_buffers


DRIVER = ("INR2D0BWP12T40P140", "ZN")
LIBRARY = "tcbn28hpcplusbwp12t40p140"
CORNERS = ("ssg0p9v125c", "tt1v25c", "ffg1p05vm40c")
CAPACITY_FRACTION = Decimal("0.5")


def sha(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def read_library(path, masters):
    text = path.read_text()
    assert re.search(r"capacitive_load_unit\s*\(\s*1\s*,\s*pf\s*\)", text, re.I)
    entries = re.split(r"(?m)^cell\s*\(([^)]+)\)\s*\{", text)
    result = {}
    for cell, body in zip(entries[1::2], entries[2::2], strict=True):
        if cell not in masters:
            continue
        fragments = re.split(r"(?m)^\s+pin\s*\(([^)]+)\)\s*\{", body)
        for pin, fragment in zip(fragments[1::2], fragments[2::2], strict=True):
            depth, properties = 1, {}
            for line in fragment.splitlines():
                if depth == 1:
                    match = re.match(r"\s*(direction|function|(?:max_|rise_|fall_)?capacitance)\s*:\s*([^;]+);", line)
                    if match:
                        properties[match[1]] = match[2].strip(' "')
                depth += line.count("{") - line.count("}")
                if depth == 0:
                    break
            result.setdefault((cell, pin), properties)
    return result


def check_loads(nodes, sinks, libraries):
    seen = set()
    parents = Counter(child for node in nodes for child in node["children"])
    assert parents == {node["id"]: 1 for node in nodes[:-1]}
    for node in nodes:
        pins = set(node["pins"])
        assert len(pins) == len(node["pins"]) and not pins & seen
        seen.update(pins)
    assert seen == sinks.keys()

    def input_cap(library, pin):
        attributes = library[pin]
        assert attributes["direction"] == "input"
        return max(Decimal(attributes[key]) for key in ("capacitance", "rise_capacitance", "fall_capacitance")
                   if key in attributes)

    fractions = {}
    for corner, library in libraries.items():
        output = library[DRIVER]
        assert output["direction"] == "output"
        root_load = input_cap(library, (nodes[-1]["master"], "I"))
        maximum = root_load / Decimal(output["max_capacitance"])
        for node in nodes:
            buffer = library[node["master"], "Z"]
            assert buffer["direction"] == "output" and buffer["function"] == "I"
            terminals = [sinks[pin] for pin in node["pins"]]
            terminals.extend((nodes[child]["master"], "I") for child in node["children"])
            assert terminals
            load = sum(input_cap(library, terminal) for terminal in terminals)
            maximum = max(maximum, load / Decimal(buffer["max_capacitance"]))
        fractions[corner] = maximum
    return fractions


def run(placement, inventory, output):
    assert __debug__ and Path("/.dockerenv").is_file()
    assert output.resolve().is_relative_to(Path(".cache").resolve())
    receipt = placement / "receipt.json"
    proof = json.loads(receipt.read_text())
    assert proof["state"] == "concurrent_chip_placed_and_cold_verified"
    source = placement / "place/placed.v"
    digest = sha(source)
    assert digest == proof["input_sha256"][str(source.resolve())]
    console = inventory.with_name("console.log")
    lines = console.read_text().splitlines()
    assert not any("**ERROR" in line or "Started Early Global Route" in line for line in lines)
    with inventory.open() as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    assert len(rows) == 5 * 18484
    masters = {row["master"] for row in rows} | {DRIVER[0]}
    masters.update(f"BUFFD{power}BWP12T40P140" for power in (4, 8, 16))
    paths = {corner: placement / f"place/placed.db/libs/mmmc/{LIBRARY}{corner}.lib" for corner in CORNERS}
    for path in paths.values():
        identity = proof["placed_database"]["files"][f"libs/mmmc/{path.name}"]
        assert sha(path) == identity["sha256"]
    libraries = {corner: read_library(path, masters) for corner, path in paths.items()}
    output.mkdir()
    summaries = {}
    plans = []
    for group in range(5):
        local = [row for row in rows if row["group"] == str(group)]
        assert len(local) == 18484 and lines.count(f"TRI_ORACLE_GROUPED_RESET_INVENTORY {group} 18484") == 1
        sinks = {row["pin"]: (row["master"], row["terminal"]) for row in local}
        assert len(sinks) == len(local) and all(pin.startswith(f"grouped_{group}/") for pin in sinks)
        points = [(row["pin"], row["x_um"], row["y_um"]) for row in local]
        for leaf_capacity in (32, 24, 16, 8):
            nodes = plan_buffers(points, leaf_loads=leaf_capacity, branch_fanout=4)
            fractions = check_loads(nodes, sinks, libraries)
            if max(fractions.values()) <= CAPACITY_FRACTION:
                break
        else:
            raise ValueError(f"No pin-load margin for group {group}: {fractions}")
        path = output / f"grouped_{group}.tsv"
        with path.open("x") as stream:
            stream.write("id\tmaster\tx_um\ty_um\tchildren\tpins\n")
            for node in nodes:
                fields = (node["id"], node["master"], f"{node['x']:.6f}", f"{node['y']:.6f}",
                          " ".join(map(str, node["children"])), " ".join(node["pins"]))
                stream.write("\t".join(map(str, fields)) + "\n")
        plans.append(path)
        summaries[str(group)] = dict(sinks=len(sinks), buffers=len(nodes), depth=nodes[-1]["level"] + 1,
                                     leaf_capacity=leaf_capacity,
                                     maximum_pin_load_fraction={corner: float(value) for corner, value in fractions.items()})
    evidence = {str(path): sha(path) for path in (source, receipt, inventory, console, *paths.values(), *plans,
                                                 Path(__file__).relative_to(Path.cwd()),
                                                 Path("syn/tri_oracle_controller255_tree.py"),
                                                 Path("syn/tri_oracle_grouped_reset_inventory.tcl"))}
    print(json.dumps(dict(state="placed_grouped_reset_trees_planned_and_pin_loads_checked", placed_netlist_sha256=digest,
                          groups=summaries, evidence_sha256=evidence,
                          scope="All original reset loads from the placed checkpoint. Buffer polarity and Liberty pin capacitance "
                                "checked across three corners. Wire capacitance, incremental placement and reset timing are pending."),
                     indent=2, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("placement", "inventory", "output"):
        parser.add_argument(name, type=Path)
    run(**vars(parser.parse_args()))
