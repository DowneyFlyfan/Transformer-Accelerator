"""Check the timing and protection constraints against the linked chip netlist."""

import argparse
from collections import Counter
from contextlib import ExitStack
from functools import lru_cache
import json
from pathlib import Path
import resource

from link_tri_oracle_parallel_chip import catalog, definition
from prepare_physical_inputs import INDEX, PROTECT
from prepare_tri_oracle_parallel_chip_synthesis import BASE, TOP, pin, read, verify
from prepare_tri_oracle_parallel_pin_constraints import pin_constraints, source_ports
from run_tri_oracle_parallel_chip_synthesis import wait_for_receipt
from verify_linked_placed_topology import parse_module
from verify_tri_oracle_packed_down_weights import ROOT


def audit_targets(modules, top, constraints, expected_ports):
    @lru_cache(maxsize=None)
    def view(master):
        text = definition(modules[master]).decode()
        _, ports, nets, children, _ = parse_module(text, (0, len(text)))
        return ports, nets, {name.removeprefix("\\"): cell[0] for name, cell in children.items()}

    @lru_cache(maxsize=None)
    def resolve_scope(path):
        if not path:
            return top
        parent = resolve_scope(path[:-1])
        return view(parent)[2].get(path[-1]) if parent in modules else None

    actual_ports = view(top)[0]
    differences = {name: {"source": expected_ports.get(name), "mapped": actual_ports.get(name)}
                   for name in sorted(expected_ports.keys() | actual_ports.keys())
                   if expected_ports.get(name) != actual_ports.get(name)}
    constrained_bits = {name: len(bits) for name, bits in pin_constraints(constraints, expected_ports).items()}
    resolved = Counter()
    missing = []
    seen = set()
    for line in constraints.splitlines():
        item = PROTECT.fullmatch(line)
        if item is None:
            assert not line.startswith("set_dont_touch"), line
            continue
        command, expression = item.groups()
        target = expression.strip("{}")
        assert (command, target) not in seen, (command, target)
        seen.add((command, target))
        *path, name = target.split("/")
        master = resolve_scope(tuple(path))
        if master not in modules:
            reason = "missing_scope"
        else:
            _, nets, cells = view(master)
            if command == "get_cells":
                reason = None if name in cells else "missing_cell"
            elif name in nets:
                reason = None
            else:
                match = INDEX.fullmatch(name)
                span = nets.get(match[1]) if match else None
                reason = (None if span is not None and min(span) <= int(match[2]) <= max(span)
                          else "missing_net_or_bit")
        if reason is None:
            resolved[command] += 1
        else:
            missing.append({"command": command, "target": target, "reason": reason})
    return {"constrained_port_bits": constrained_bits, "port_differences": differences,
            "resolved_protections": dict(resolved), "unresolved_protections": missing}


def bind_design(constraints, top):
    source = f"current_design {TOP}\n"
    assert constraints.count(source) == 1
    return constraints.replace(source, f"current_design {top}\n", 1)


def run(synthesis, output):
    linked = synthesis / "linked_chip/receipt.json"
    link = read(linked)
    assert link["state"] == "parallel_chip_parent_linked_with_verified_mapped_imports"
    pins = link["input_sha256"].copy()
    netlist = linked.with_name("chip.v")
    pin(pins, netlist, link["chip_sha256"])
    baseline = ROOT / "records/wac_parallel_chip_pin_constraint_preflight_result.json"
    baseline_record = read(baseline)
    assert baseline_record["state"] == "parallel_chip_source_pin_constraints_preflight"
    preflight = synthesis / "pin_constraint_preflight/receipt.json"
    candidate = synthesis / f"{TOP}.sv"
    sdc = preflight.with_name("candidate.sdc")
    for file in (preflight, candidate, sdc):
        key = str(file.relative_to(ROOT))
        pin(pins, file, baseline_record["evidence_sha256"][key])
    for file in (linked, baseline, Path(__file__).resolve(), Path(parse_module.__code__.co_filename).resolve()):
        pin(pins, file)
    verify(pins)

    constraints = sdc.read_text()
    top = link["top"]
    with ExitStack() as stack:
        diagnostics = audit_targets(catalog(stack, netlist), top, constraints, source_ports(candidate.read_text()))
    assert diagnostics["constrained_port_bits"] == baseline_record["external_constraint_counts"]
    total = sum(diagnostics["resolved_protections"].values()) + len(diagnostics["unresolved_protections"])
    assert total == sum(sum(baseline_record[key].values()) for key in
                        ("inherited_protections_under_preserved_cuts", "inherited_protections_outside_preserved_cuts"))
    passed = not diagnostics["port_differences"] and not diagnostics["unresolved_protections"]
    verify(pins)
    output.mkdir()
    report = {"state": "linked_chip_pin_constraints_bound" if passed else "linked_chip_pin_constraints_unresolved",
              "top": top, "candidate_sha256": link["chip_sha256"], **diagnostics, "input_sha256": pins,
              "scope": "Static constraint target resolution in the linked netlist."}
    if passed:
        bound = output / "candidate.sdc"
        bound.write_text(bind_design(constraints, top))
        report["output_sha256"] = {}
        pin(report["output_sha256"], bound)
    (output / "diagnostics.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(report["state"], "port differences", len(diagnostics["port_differences"]),
          "unresolved protections", len(diagnostics["unresolved_protections"]), flush=True)
    return passed


if __name__ == "__main__":
    resource.setrlimit(resource.RLIMIT_AS, (2**31, 2**31))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=lambda value: Path(value).resolve())
    parser.add_argument("--synthesis", type=lambda value: Path(value).resolve(), default=BASE / "parallel_synthesis")
    parser.add_argument("--link-worker", type=int)
    args = parser.parse_args()
    if args.link_worker is not None:
        wait_for_receipt(args.synthesis / "linked_chip/receipt.json", args.link_worker, "link_tri_oracle_parallel_chip.py")
    raise SystemExit(0 if run(args.synthesis, args.output) else 2)
