"""Resolve each candidate driver pin and every endpoint on its incident nets."""

from collections import defaultdict
from contextlib import ExitStack
import json
from pathlib import Path
import re

from audit_tri_oracle_booth_operand_spans import (
    CELL,
    LINK,
    PAD,
    TIMING,
    bits,
    lef_ports,
)
from build_tri_oracle_booth_chip_seed import hierarchy
from link_tri_oracle_indexed_whole_chip import signature
from verify_tri_oracle_booth_chip_link import TOP, WORK, named_bindings
from verify_tri_oracle_gated_compute_array import ROOT, digest, read
from verify_tri_oracle_serialized_placement_transfer import catalog

SPANS = Path("records/tri_oracle_booth_operand_spans.json")
OUT = WORK / "operand_geometry"
TOKEN = re.compile(rb"(?<![\w$])[A-Za-z_$][\w$]*(?:\[\d+(?::\d+)?\])?")
ASSIGN = re.compile(rb"(?m)^\s*assign\s+([^;]*);")


def by_context(all_targets):
    parents = defaultdict(list)
    for detail in all_targets:
        root, _, child = detail["driver"].rpartition("/")
        parents[root].append((child, detail))
    return parents


def irrelevant(value, signals):
    return not any(token.split(b"[")[0] in signals for token in TOKEN.findall(value))


def connect_or_mark(value, port, master, pins, signals, selected_bases):
    if irrelevant(value, selected_bases):
        return []
    if value in signals and port in pins:
        return [(value, port, pins[port][0])]
    group_pins = [key for key in pins if key.startswith(port + "[")]
    if group_pins:
        entry = bits(value, len(group_pins))
        return [
            (signal, name, pins[name][0])
            for i, signal in enumerate(reversed(entry))
            if signal in signals
            for name in (f"{port}[{i}]",)
        ]
    tokens = TOKEN.findall(value)
    selected = any(
        token in signals or (b"[" not in token and token in selected_bases)
        for token in tokens
    )
    if selected:
        raise ValueError((master, port, value, "No physical pin shape"))
    return []


def trace(root, text, candidates, library, array_edges):
    instances = {
        match[2].decode().removeprefix("\\"): (
            match[1].decode(),
            named_bindings(match[3]),
        )
        for match in CELL.finditer(text)
    }
    signals = {
        value
        for name, _ in candidates
        for pin, value in instances[name][1].items()
        if pin in library[instances[name][0]]
    }
    bases = {signal.split(b"[")[0] for signal in signals}
    connected = defaultdict(list)
    unresolved = set()
    public = {name.encode() for name in signature(text)}
    unresolved.update(base for base in bases if base in public)
    for assign in ASSIGN.findall(text):
        unresolved.update(
            token.split(b"[")[0]
            for token in TOKEN.findall(assign)
            if token.split(b"[")[0] in bases
        )

    for name, (master, bindings) in instances.items():
        parent = root + "/" + name
        if name == "compute":
            assert master.startswith("tri_oracle_pe_array_verified_")
            for port, value in bindings.items():
                if irrelevant(value, bases):
                    continue
                if port in ("operand_a", "operand_b"):
                    atoms = bits(value, 2048)
                    for bit, signal in enumerate(reversed(atoms)):
                        if signal in signals:
                            graph_key = f"{port}[{bit}]"
                            assert graph_key in array_edges
                            connected[signal].extend(
                                (parent + "/" + cell, pin, "INPUT")
                                for cell, pin in array_edges[graph_key]
                            )
                else:
                    unresolved.update(
                        token.split(b"[")[0]
                        for token in TOKEN.findall(value)
                        if token.split(b"[")[0] in bases
                    )
            continue
        if master not in library:
            for value in bindings.values():
                unresolved.update(
                    token.split(b"[")[0]
                    for token in TOKEN.findall(value)
                    if token.split(b"[")[0] in bases
                )
            continue
        for port, value in bindings.items():
            for signal, pin, direction in connect_or_mark(
                value, port, master, library[master], signals, bases
            ):
                connected[signal].append((parent, pin, direction))

    ready, unresolved_candidates = [], {}
    for name, detail in candidates:
        master, bindings = instances[name]
        graph = {}
        touched = {value.split(b"[")[0] for value in bindings.values()}
        if needed := (touched & unresolved):
            unresolved_candidates[detail["driver"]] = [
                net.decode() for net in sorted(needed)
            ]
            continue
        for pin, net in bindings.items():
            if pin not in library[master]:
                continue
            ends = connected[net]
            assert len(set(ends)) == len(ends), (name, pin, net)
            assert (detail["driver"], pin, library[master][pin][0]) in ends
            assert sum(out == "OUTPUT" for _, _, out in ends) == 1, (
                name,
                pin,
                net,
                ends[:8],
            )
            graph[pin] = dict(net=net.decode(), endpoints=ends)
        assert (
            detail["driver_pin"] in graph
            and len(graph[detail["driver_pin"]]["endpoints"]) >= 2
        )
        assert any(
            end[0].endswith("/compute/" + detail["load"].rsplit("/", 1)[0])
            and end[1] == detail["load"].rsplit("/", 1)[1]
            for end in graph[detail["driver_pin"]]["endpoints"]
        )
        ready.append(
            dict(
                driver=detail["driver"],
                output_pin=detail["driver_pin"],
                region=detail["region"],
                master=master,
                incident=graph,
            )
        )
    return ready, unresolved_candidates


def report():
    audit, placement, timing = map(read, (SPANS, LINK, TIMING))
    pad = read(PAD)
    design = WORK / "linked.v"
    assert digest(design) == placement["evidence_sha256"][str(design)]
    assert digest(design) == audit["evidence_sha256"][str(design)]
    lefs = [Path(name) for name in pad["evidence_sha256"] if name.endswith(".lef")]
    assert all(digest(path) == pad["evidence_sha256"][str(path)] for path in lefs)
    library = lef_ports(lefs)
    (edges,) = (
        Path(name)
        for name in timing["evidence_sha256"]
        if name.endswith("/timing_swaps/edges.tsv")
    )
    assert digest(edges) == timing["evidence_sha256"][str(edges)]
    array_edges = defaultdict(list)
    for line in edges.read_text().splitlines():
        source, target, _ = line.split("\t")
        if source.startswith(("operand_a[", "operand_b[")):
            cell, pin = target.rsplit("/", 1)
            array_edges[source].append((cell, pin))
    assert len(array_edges) == 4096
    ready, problems = [], {}
    with ExitStack() as stack:
        modules = catalog(stack, [design])
        children, _ = hierarchy(modules)
        for root, candidates in by_context(
            audit["longest_twelve_unique_drivers"]
        ).items():
            module = TOP.encode()
            for piece in root.encode().split(b"/"):
                module = children(module)[piece]
            source, start, end = modules[module.decode()]
            complete, unresolved = trace(
                root, source[start:end], candidates, library, array_edges
            )
            ready.extend(complete)
            problems.update(unresolved)
    assert len(ready) + len(problems) == 12
    return dict(
        state="driver_pin_neighborhoods_traced",
        candidates=ready,
        unresolved_parents=problems,
        evidence_sha256={
            str(path): digest(path)
            for path in (
                SPANS,
                LINK,
                TIMING,
                PAD,
                edges,
                design,
                *lefs,
                Path(__file__).resolve().relative_to(ROOT),
            )
        },
    )


if __name__ == "__main__":
    print(json.dumps(report(), indent=2, sort_keys=True))
