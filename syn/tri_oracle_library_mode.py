"""Audit port-observable, zero-delay library equivalence after preprocessing.

Only scalar gate/primitive models are supported. Specify blocks are excluded
because the supported simulation does not enable specify timing or annotate
delays. Every state primitive and register declaration must remain unchanged;
only combinational observers outside every port/state cone may disappear.
"""
import collections
import hashlib
import json
import re


class ModeError(ValueError):
    """The source subset or equivalence obligation was not proven."""


IDENT = r"[A-Za-z_][A-Za-z_0-9$]*"
NATIVE = {"and", "nand", "or", "nor", "xor", "xnor", "buf", "not",
          "pullup", "pulldown", "bufif0", "bufif1", "notif0", "notif1"}


def _clean(source):
    return re.sub(r"/\*.*?\*/|//[^\n]*", " ", source, flags=re.S)


def _names(source):
    result = tuple(name.strip() for name in source.split(",")) if source.strip() else ()
    if any(not re.fullmatch(IDENT, name) for name in result) or len(set(result)) != len(result):
        raise ModeError("Only unique scalar identifiers are supported")
    return result


def _library(source):
    source = _clean(source)
    pattern = re.compile(rf"\bmodule\s+({IDENT})\s*(?:\(([^;]*)\))?\s*;(.*?)\bendmodule\b", re.S)
    models = {}
    for match in pattern.finditer(source):
        if match[1] in models:
            raise ModeError("Duplicate cell model")
        models[match[1]] = (_names(match[2] or ""), match[3])
    remaining = pattern.sub(" ", source)
    pattern = re.compile(rf"\bprimitive\s+({IDENT})\s*\(([^;]*)\);(.*?)\bendprimitive\b", re.S)
    primitives = {}
    for match in pattern.finditer(remaining):
        ports = _names(match[2])
        outputs = re.findall(rf"\boutput\s+({IDENT})\s*;", match[3])
        if not ports or outputs != [ports[0]] or match[1] in primitives:
            raise ModeError("Unsupported or duplicate user-defined primitive")
        sequential = bool(re.search(rf"\breg\s+{re.escape(ports[0])}\s*;", match[3]))
        primitives[match[1]] = (re.sub(r"\s+", " ", match[0]).strip(), len(ports), sequential)
    remaining = re.sub(r"\s+", " ", pattern.sub(" ", remaining)).strip()
    # Positions of context-sensitive directives must not be lost when model
    # bodies are extracted. This subset has no delays and permits only timing
    # units/cell-classification markers; net types, pull defaults and resets
    # of compilation context are deliberately unsupported.
    harmless_directive = (r"`(?:celldefine|endcelldefine)\b|"
                          r"`timescale\s+(?:1|10|100)(?:s|ms|us|ns|ps|fs)\s*/\s*"
                          r"(?:1|10|100)(?:s|ms|us|ns|ps|fs)\b")
    if re.sub(harmless_directive, " ", remaining).strip():
        raise ModeError("Unsupported global directive or statement")
    return models, primitives, remaining


def _graph(model, primitives):
    ports, body = model
    body = re.sub(r"\bspecify\b.*?\bendspecify\b", " ", body, flags=re.S)
    declarations = collections.defaultdict(set)
    components = []
    for statement in body.split(";"):
        statement = statement.strip()
        if not statement:
            continue
        declaration = re.fullmatch(r"(input|output|reg|wire)\s+(.+)", statement, re.S)
        if declaration:
            for name in _names(declaration[2]):
                declarations[name].add(declaration[1])
            continue
        gate = re.fullmatch(rf"({IDENT})(?:\s+({IDENT}))?\s*\(([^()]*)\)", statement, re.S)
        if not gate or gate[1] not in NATIVE | primitives.keys():
            raise ModeError("Unsupported functional-model statement: " + statement[:120])
        kind, instance, terminals = gate.groups()
        terminals = tuple(value.strip() for value in terminals.split(","))
        if any(not re.fullmatch(IDENT + r"|1'[bB][01xXzZ]", value) for value in terminals):
            raise ModeError("Only scalar primitive terminals are supported")
        if not terminals or not re.fullmatch(IDENT, terminals[0]):
            raise ModeError("A primitive must drive a scalar net")
        if kind in primitives:
            valid = len(terminals) == primitives[kind][1]
        elif kind in {"buf", "not"}:
            valid = len(terminals) == 2
        elif kind in {"pullup", "pulldown"}:
            valid = len(terminals) == 1
        elif kind in {"bufif0", "bufif1", "notif0", "notif1"}:
            valid = len(terminals) == 3
        else:
            valid = len(terminals) >= 3
        if not valid:
            raise ModeError("Unsupported primitive arity")
        components.append((kind, instance or "", terminals))
    interface = tuple((name, tuple(sorted(declarations[name]))) for name in ports)
    for name, types in interface:
        if ("input" in types) == ("output" in types):
            raise ModeError("Missing or ambiguous scalar port direction: " + name)
    if {name for name, types in declarations.items() if {"input", "output"} & types} != set(ports):
        raise ModeError("Port declarations differ from the header")
    registers = tuple(sorted(name for name, kinds in declarations.items() if "reg" in kinds))
    state = tuple(sorted(component for component in components if component[0] in primitives and primitives[component[0]][2]))
    combinational = collections.defaultdict(set)
    for component in components:
        if component not in state:
            combinational[component[2][0]].update(component[2][1:])
    # Even a port-unreachable combinational cycle can prevent simulation time
    # from advancing. Only acyclic observers can be safely discarded.
    indegree = {net: len(inputs & combinational.keys()) for net, inputs in combinational.items()}
    consumers = collections.defaultdict(set)
    for net, inputs in combinational.items():
        for dependency in inputs & combinational.keys():
            consumers[dependency].add(net)
    ready = [net for net, degree in indegree.items() if degree == 0]
    visited = 0
    while ready:
        net = ready.pop()
        visited += 1
        for consumer in consumers[net]:
            indegree[consumer] -= 1
            if indegree[consumer] == 0:
                ready.append(consumer)
    if visited != len(combinational):
        raise ModeError("Combinational feedback is outside the supported subset")
    drivers = collections.defaultdict(list)
    for index, component in enumerate(components):
        drivers[component[2][0]].append(index)
    # Net-type inputs may collapse into the caller's net. An internal driver
    # of an input is therefore observable too. Keep the complete boundary.
    pending = [name for name, _ in interface]
    # Preserve the behavior of every retained state primitive, including one
    # whose output is not connected to a port. Its input-driver cones matter.
    pending.extend(terminal for component in state for terminal in component[2])
    nets, reachable = set(), set()
    while pending:
        net = pending.pop()
        if net in nets:
            continue
        nets.add(net)
        for index in drivers[net]:
            reachable.add(index)
            pending.extend(components[index][2][1:])
    # Retain the relative declaration order as well as exact connectivity.
    cone = tuple(components[index] for index in sorted(reachable))
    relevant_declarations = tuple(sorted((name, tuple(sorted(declarations[name]))) for name in nets if name in declarations))
    return {"signature": (interface, registers, state, cone, relevant_declarations),
            "components": components, "state_count": len(state), "reachable_count": len(cone)}


def audit_library_modes(default_source, functional_source, instance_counts):
    if not instance_counts or any(not isinstance(count, int) or count <= 0 for count in instance_counts.values()):
        raise ModeError("A nonempty positive instance inventory is required")
    original, old_primitives, old_global = _library(default_source)
    candidate, new_primitives, new_global = _library(functional_source)
    if old_primitives != new_primitives or old_global != new_global:
        raise ModeError("User-defined state/logic tables or global directives changed")
    cells = {}
    for name, count in sorted(instance_counts.items()):
        if name not in original or name not in candidate:
            raise ModeError("Missing cell model: " + name)
        old = _graph(original[name], old_primitives)
        new = _graph(candidate[name], new_primitives)
        if old["signature"] != new["signature"]:
            raise ModeError("Functional output cone, interface, registers or state changed: " + name)
        if collections.Counter(new["components"]) - collections.Counter(old["components"]):
            raise ModeError("Functional mode added or changed a component: " + name)
        removed = len(old["components"]) - len(new["components"])
        cells[name] = {"instances": count, "removed_observers_per_instance": removed,
                       "state_components_per_instance": old["state_count"],
                       "port_or_state_cone_components_per_instance": old["reachable_count"],
                       "functional_graph_sha256": hashlib.sha256(json.dumps(old["signature"]).encode()).hexdigest()}
    return {
        "scope": "Structural port-observable equivalence for the supported scalar zero-delay subset; no timing-annotation or full-chip functionality claim",
        "audited_cell_types": len(cells), "audited_cell_instances": sum(instance_counts.values()),
        "primitive_definitions_identical": len(old_primitives),
        "removed_observer_components": sum(v["instances"] * v["removed_observers_per_instance"] for v in cells.values()),
        "state_components_preserved": sum(v["instances"] * v["state_components_per_instance"] for v in cells.values()),
        "cells": cells,
    }
