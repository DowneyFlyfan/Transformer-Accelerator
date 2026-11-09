"""Inline exact one-gate library wrappers for zero-delay Icarus simulation.

This changes only simulation hierarchy. Native buf/not primitives, their drive
strengths, every connection and every state-holding cell remain unchanged.
It cannot be used for delay annotation: module timing paths are intentionally
absent, just as with Icarus's default (no -gspecify) gate simulation.
"""
import argparse
import collections
import hashlib
import json
from pathlib import Path
import re


IDENT = r"(?:\\[^\s]+|[A-Za-z_][A-Za-z_0-9$]*)"
COMMENT = r"/\*.*?\*/|//[^\n]*"
MODULE = re.compile(r"\bmodule\s+\w+\s*\([^;]*\);(.*?)\bendmodule\b", re.S)


def simple_cell_models(library):
    """Accept only scalar, two-port wrappers containing exactly buf or not."""
    library = re.sub(COMMENT, " ", library, flags=re.S)
    models = {}
    for match in re.finditer(r"\bmodule\s+(\w+)\s*\(([^;]*)\);(.*?)\bendmodule\b", library, re.S):
        name, ports, body = match.groups()
        # Specify blocks are inactive in the supported no-gspecify simulation.
        body = re.sub(r"\bspecify\b.*?\bendspecify\b", " ", body, flags=re.S)
        gate = re.fullmatch(
            r"\s*input\s+(\w+)\s*;\s*output\s+(\w+)\s*;"
            r"\s*(buf|not)\s*\(\s*(\w+)\s*,\s*(\w+)\s*\)\s*;\s*", body)
        if not gate:
            continue
        source, destination, primitive, gate_output, gate_input = gate.groups()
        if (gate_input != source or gate_output != destination
                or [p.strip() for p in ports.split(",")] != [source, destination]
                or source == destination):
            continue
        models[name] = (primitive, source, destination)
    return models


def inline_netlist(netlist, models):
    """Rewrite only fully connected, statically scalar named instances."""
    counts = collections.Counter()
    if not models:
        return netlist, {}
    names = "|".join(re.escape(name) for name in sorted(models, key=len, reverse=True))
    instance = re.compile(
        rf"(?P<comment>{COMMENT})|(?P<cell>^[ \t]*(?P<model>{names})\s+"
        rf"(?P<instance>{IDENT})\s*\((?P<ports>[^;]{{1,1024}})\)\s*;)", re.S | re.M)
    connection = re.compile(
        rf"\s*\.(\w+)\s*\(\s*({IDENT}(?:\s*\[\s*\d+\s*\])?|1'[bB][01xXzZ])\s*\)\s*")

    def rewrite_module(module_match):
        body = module_match.group(1)
        declarations = re.sub(COMMENT, " ", body, flags=re.S)
        nets = {}
        for declaration in re.finditer(
                r"\b(?:input|output|wire)\s*(\[\s*\d+\s*:\s*\d+\s*\])?\s*([^;]+);", declarations):
            width, names = declaration.groups()
            bounds = [int(value) for value in re.findall(r"\d+", width)] if width else [0, 0]
            for name in names.split(","):
                name = name.strip()
                if re.fullmatch(IDENT, name):
                    nets[name] = bounds

        def scalar(expression, output=False):
            expression = expression.strip()
            if re.fullmatch(r"1'[bB][01xXzZ]", expression):
                return not output
            if expression in nets:
                return nets[expression][0] == nets[expression][1]
            selected = re.fullmatch(rf"({IDENT})\s*\[\s*(\d+)\s*\]", expression)
            if not selected or selected[1] not in nets:
                return False
            low, high = sorted(nets[selected[1]])
            return low <= int(selected[2]) <= high

        def rewrite_instance(match):
            if match.group("comment") is not None:
                return match[0]
            ports = match.group("ports")
            connections = {}
            position = 0
            while position < len(ports):
                port = connection.match(ports, position)
                if not port or port[1] in connections:
                    return match[0]
                connections[port[1]] = port[2].strip()
                position = port.end()
                if position < len(ports):
                    if ports[position] != ",":
                        return match[0]
                    position += 1
                    if not ports[position:].strip():
                        return match[0]
            primitive, source, destination = models[match.group("model")]
            if (set(connections) != {source, destination}
                    or not scalar(connections[source])
                    or not scalar(connections[destination], output=True)):
                return match[0]
            counts[match.group("model")] += 1
            return f"{primitive} {match.group('instance')}  ({connections[destination]} , {connections[source]} );"

        new_body = instance.sub(rewrite_instance, body)
        begin, end = module_match.span(1)
        return netlist[module_match.start():begin] + new_body + netlist[end:module_match.end()]

    result = MODULE.sub(rewrite_module, netlist)
    return result, dict(sorted(counts.items()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", required=True, type=Path)
    parser.add_argument("--netlist", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()
    paths = [args.library, args.netlist, args.output, args.manifest]
    if len({path.resolve() for path in paths}) != len(paths):
        parser.error("Library, source netlist, simulation netlist and manifest must be distinct.")
    if args.output.exists() or args.manifest.exists():
        parser.error("Refusing to overwrite an existing output or manifest.")
    library_bytes = args.library.read_bytes()
    source_bytes = args.netlist.read_bytes()
    library = library_bytes.decode()
    source = source_bytes.decode()
    result, counts = inline_netlist(source, simple_cell_models(library))
    if not counts:
        parser.error("No eligible scalar instances found; no output written.")
    def sha(data):
        return hashlib.sha256(data).hexdigest()
    manifest = {
        "scope": "Exact buf/not wrapper inlining for zero-delay functional simulation only; no delay annotation",
        "source_netlist": str(args.netlist), "source_sha256": sha(source_bytes),
        "source_library": str(args.library), "library_sha256": sha(library_bytes),
        "simulation_netlist": str(args.output), "simulation_sha256": sha(result.encode()),
        "transformer_sha256": sha(Path(__file__).read_bytes()),
        "inlined_instances": sum(counts.values()), "inlined_cell_counts": counts,
        "state_holding_cells_modified": 0,
    }
    # Exclusive creation also prevents a racing producer from being overwritten.
    with args.output.open("x") as output:
        output.write(result)
    with args.manifest.open("x") as output:
        output.write(json.dumps(manifest, indent=2) + "\n")
    print(f"Inlined {sum(counts.values())} exact buf/not wrappers; all other source text retained.")


if __name__ == "__main__":
    main()
