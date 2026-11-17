"""Bind the clock and clocked compute hierarchy to the exact placed netlist."""

from collections import Counter
from functools import cache
import json
import mmap
from pathlib import Path
import re

from audit_tri_oracle_mapped_redundancy import CORE, audit, hierarchy
from check_tri_oracle_paper300_gate import PAPER_RELATIVE, PAPER_SHA256
from link_tri_oracle_indexed_whole_chip import module_at, signature, spans
from verify_tri_oracle_booth_chip_link import named_bindings
from verify_tri_oracle_corrected_booth_roundtrip import ROOT, TOP, constraints, digest


PLACEMENT = Path("records/tri_oracle_corrected_booth_buffered_placement_roundtrip.json")
REDUNDANCY = Path("records/tri_oracle_corrected_booth_redundancy_topology.json")
TOP_PORTS = {"clk": (b"input", b""), "rst_n": (b"input", b""), "memory_tx_clock": (b"output", b"")}


def clock_endpoints(graph, clusters, source):
    modules = spans(source)

    @cache
    def ports(master):
        return signature(module_at(source, modules, master))

    @cache
    def edge(master, instance):
        child = graph[master][instance]
        pattern = (rb"(?m)^[ \t]+" + re.escape(child.encode()) + rb"\s+" +
                   re.escape(instance.encode()) + rb"\s*\(([^;]*)\);")
        start, end = modules[master]
        match, = re.compile(pattern).finditer(source, start, end)
        return named_bindings(match[1])

    def follow_clock(master, instance):
        child = graph[master][instance]
        assert ports(master)["clk"] == ports(child)["clk"] == TOP_PORTS["clk"]
        assert edge(master, instance)["clk"] == b"clk", (master, instance)
        return child

    def walk_cluster(path):
        assert path.startswith(TOP + ".")
        master, cursor = TOP, path.removeprefix(TOP + ".")
        depth = 0
        while cursor:
            candidates = [
                name for name in graph[master]
                if cursor == name.lstrip("\\") or cursor.startswith(name.lstrip("\\") + ".")
            ]
            child = max(candidates, key=len)
            master = follow_clock(master, child)
            cursor = cursor[len(child.lstrip("\\")):].removeprefix(".")
            depth += 1
        return master, depth

    assert {name: ports(TOP)[name] for name in TOP_PORTS} == TOP_PORTS
    assert set(graph[TOP]) == {"chip", "serial_pads", "request_link"}
    for instance in graph[TOP]:
        follow_clock(TOP, instance)
    assert edge(TOP, "request_link")["pad_clock"] == b"memory_tx_clock"
    assert graph[TOP]["request_link"] == "tri_oracle_memory_tx_credit"
    results = {}
    for cluster in clusters:
        master, depth = walk_cluster(cluster["instance"])
        cores = []
        for instance, cell in graph[master].items():
            if CORE.fullmatch(cell):
                core = follow_clock(master, instance)
                memory_compute = follow_clock(core, "compute")
                array = follow_clock(memory_compute, "compute")
                assert array.startswith("tri_oracle_pe_array_verified_bank")
                cores.append(instance.removeprefix("\\"))
        assert len(cores) == cluster["cores"] == 4
        results[cluster["bank"]] = {"clock_edges_to_cluster": depth, "directly_clocked_cores": sorted(cores),
                                    "directly_clocked_arrays": len(cores)}
    assert set(results) == set(range(5))
    return results


def clock_definitions(path):
    statements = constraints(path)
    clock, = [line for line in statements if line.startswith("create_clock ")]
    match = re.fullmatch(
        r"create_clock \[get_ports \{clk\}\] -name core_clock -period ([\d.]+) -waveform \{[\d.]+ [\d.]+\}", clock,
    )
    assert match, clock
    generated, = [line for line in statements if line.startswith("create_generated_clock ")]
    assert generated == ("create_generated_clock -name pad_sample_clock -source [get_ports {clk}] "
                         "-edges {2 3 4} [get_ports {memory_tx_clock}]")
    return {"core_clock_period_ns": float(match[1]), "pad_clock_edges": [2, 3, 4]}


def verify():
    evidence = {}

    def pin(path, expected=None):
        value = digest(path)
        assert expected is None or expected == value, path
        evidence[str(path)] = value
        return path

    pin(Path(PAPER_RELATIVE), PAPER_SHA256)
    placed = json.loads(pin(PLACEMENT).read_text())
    topology = json.loads(pin(REDUNDANCY).read_text())
    stage = Path(placed["database"]).parents[1] / "cold"
    netlist = stage / "cold.v"
    pin(netlist, placed["evidence_sha256"][str(netlist)])
    graph = hierarchy(netlist)
    actual = audit(graph, TOP)
    assert actual["clusters"] == topology["clusters"]
    with netlist.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as source:
        endpoints = clock_endpoints(graph, actual["clusters"], source)
    clocks = {}
    for view in placed["views"]:
        target = stage / f"{view}.sdc"
        pin(target, placed["evidence_sha256"][str(target)])
        clocks[view] = clock_definitions(target)
    assert len(clocks) == 3 and all(value == clocks["setup_slow"] for value in clocks.values())
    assert clocks["setup_slow"]["core_clock_period_ns"] == 1.72414
    counts = Counter(data["directly_clocked_arrays"] for data in endpoints.values())
    assert counts == {4: 5}
    pin(Path(__file__).resolve().relative_to(ROOT))
    return {
        "state": "repaired_booth_external_clock_boundary_verified",
        "cold_netlist_sha256": evidence[str(netlist)],
        "database_fingerprint_sha256": placed["database_fingerprint_sha256"],
        "external_core_clock_port": "clk",
        "forwarded_pad_clock_port": "memory_tx_clock",
        "compute_clusters": endpoints,
        "directly_clocked_arrays": 20,
        "clock_constraints_by_view": clocks,
        "paper_clock_generator": "On-chip all-digital phase-locked loop",
        "paper_clock_generator_equivalence_verified": False,
        "scope": "Direct clock connections from the external port through every cluster and core to its compute array. "
                 "The external pad sample clock is derived from that port. This verifies connectivity and constraints "
                 "before clock-tree synthesis and routing.",
        "evidence_sha256": evidence,
    }


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").is_file()
    print(json.dumps(verify(), indent=2, sort_keys=True))
