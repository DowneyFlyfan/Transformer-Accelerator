"""Check all reset drivers and plan the next overloaded distribution tree."""
from collections import Counter
import csv
from decimal import Decimal
import json
from pathlib import Path
import sys

root = Path.cwd()
from audit_tri_oracle_placed_fanout import sha
from plan_tri_oracle_grouped_reset import CORNERS, LIBRARY, read_library
from tri_oracle_controller255_tree import plan_buffers

if len(sys.argv) != 2:
    raise SystemExit("Usage: qualify_tri_oracle_grouped_reset_pin_loads.py MEASUREMENT_DIRECTORY")
work = Path(sys.argv[1]).resolve()
assert work.is_relative_to(root / ".cache")
native = json.loads((work / "native.json").read_text())
recipe = root / "syn/tri_oracle_measure_grouped_reset_loads.tcl"
assert native["recipe_sha256"] == sha(recipe)
table = work / "loads.tsv"
assert native["table_sha256"] == sha(table) and native["log_sha256"] == sha(work / "console.log")
assert native["exit_status"] == 0
graph = root / "records/tri_oracle_grouped_reset_graph.json"
assert json.loads(graph.read_text())["buffered_netlist_sha256"] == native["candidate_sha256"]
plan_directory = work.parent / "grouped_reset_plan"
plan_receipt = json.loads(plan_directory.with_suffix(".json").read_text())
expected = {}
for group in range(5):
    owner = f"grouped_{group}"
    expected[f"{owner}/root"] = (f"{owner}/g83737/ZN", 1)
    path = plan_directory / f"grouped_{group}.tsv"
    assert sha(path) == plan_receipt["evidence_sha256"][str(path.relative_to(root))]
    with path.open() as source:
        for row in csv.DictReader(source, delimiter="\t"):
            name = f"{owner}/TRI_GROUPED_RESET_{group}_{row['id']}"
            count = len((row["children"] or row["pins"]).split())
            assert name not in expected and count in range(1, 33)
            expected[name] = (f"{name}/Z", count)
assert len(expected) == 3875
expected["grouped_active"] = ("batch/g166179/Z", 17013)

reports = {}
views = ("setup_slow", "setup_typ", "hold_fast")
with table.open() as source:
    rows = list(csv.DictReader(source, delimiter="\t"))
assert len(rows) == len(expected) * len(views)
for view in views:
    pending = expected.copy()
    ratios = {}
    measurements = {}
    for row in rows:
        if row["view"] != view:
            continue
        path = row["path"]
        assert pending.pop(path) == (row["driver"], int(row["sinks"]))
        load, limit = Decimal(row["pin_load_pf"]), Decimal(row["limit_pf"])
        assert load.is_finite() and limit.is_finite() and load > 0 and limit > 0
        ratios[path] = load / limit
        measurements[path] = (load, limit)
    assert not pending
    active_ratio = ratios.pop("grouped_active")
    active_load, active_limit = measurements["grouped_active"]
    worst_path = max(ratios, key=ratios.__getitem__)
    assert ratios[worst_path] < 1 < active_ratio
    reports[view] = dict(reset_drivers=len(ratios), worst_reset_driver=worst_path,
                         maximum_reset_pin_load_ratio=float(ratios[worst_path]),
                         grouped_active=dict(sinks=17013, load_pf=float(active_load),
                                             limit_pf=float(active_limit), multiple=float(active_ratio)))
inventory = work / "grouped_active_sinks.tsv"
with inventory.open() as source:
    sinks = {row["pin"]: row for row in csv.DictReader(source, delimiter="\t")}
assert len(sinks) == 17013
assert all(row["y_um"] is None and len(row["x_um"].split()) == 2 for row in sinks.values())
nodes = plan_buffers((pin, *row["x_um"].split()) for pin, row in sinks.items())
assert Counter(pin for node in nodes for pin in node["pins"]) == Counter(sinks.keys())
assert Counter(child for node in nodes for child in node["children"]) == Counter(range(len(nodes) - 1))
models = {(row["master"], row["terminal"]) for row in sinks.values()}
masters = {master for master, _ in models} | {node["master"] for node in nodes} | {"OR2D1BWP12T40P140"}

def cap(library, cell, pin):
    fields = library[cell, pin]
    assert fields["direction"] == "input"
    return max(Decimal(fields[key]) for key in ("capacitance", "rise_capacitance", "fall_capacitance")
               if key in fields)

maxima = {}
libs = []
for corner in CORNERS:
    path = work.parent / f"grouped_reset_eco_reload/apply/trial.db/libs/mmmc/{LIBRARY}{corner}.lib"
    libs.append(path)
    library = read_library(path, masters)
    root_limit = Decimal(library["OR2D1BWP12T40P140", "Z"]["max_capacitance"])
    ratios = [cap(library, nodes[-1]["master"], "I") / root_limit]
    for node in nodes:
        output = library[node["master"], "Z"]
        assert output["direction"] == "output" and output["function"] == "I"
        terminals = [(sinks[pin]["master"], sinks[pin]["terminal"]) for pin in node["pins"]]
        terminals.extend((nodes[child]["master"], "I") for child in node["children"])
        ratios.append(sum(cap(library, cell, pin) for cell, pin in terminals) / Decimal(output["max_capacitance"]))
    assert max(ratios) < Decimal("0.5")
    maxima[corner] = float(max(ratios))
plan = work / "grouped_active_tree_verified.tsv"
with plan.open("x") as out:
    out.write("id\tmaster\tx_um\ty_um\tchildren\tpins\n")
    for node in nodes:
        out.write("\t".join((str(node["id"]), node["master"], f"{node['x']:.6f}", f"{node['y']:.6f}",
                             " ".join(map(str, node["children"])), " ".join(node["pins"]))) + "\n")
print(json.dumps(dict(
    state="buffered_reset_pin_loads_verified_and_grouped_active_tree_planned",
    buffered_netlist_sha256=native["candidate_sha256"], native=native,
    measured_views=reports,
    grouped_active_buffer_plan=dict(sinks=len(sinks), buffers=len(nodes), depth=nodes[-1]["level"]+1,
                                    max_pin_load_ratio=maxima),
    evidence_sha256={str(path.relative_to(root)): sha(path) for path in
                     (recipe, graph, table, inventory, plan, *libs, Path(__file__).resolve())},
    scope="Native library pin load measurements and a proposed tree for grouped_active. "
          "Wire extraction, reset slew and recovery/removal timing remain unmeasured. "
          "The grouped_active tree has not been applied.",
), sort_keys=True, indent=2))
