"""Verify mapped connectivity across the Booth chip placement reload."""

import argparse
import json
from pathlib import Path
import re
import sys

from prepare_tri_oracle_booth_chip_native import NATIVE
from verify_tri_oracle_booth_chip_link import TOP, WORK
from verify_tri_oracle_gated_compute_array import ROOT, digest, read

INPUTS = Path("records/tri_oracle_booth_chip_native_inputs.json")
REFERENCE_TOOLS = (
    Path(".cache/physical/wac_budgeted_parent_boundary"),
    Path(".cache/physical/shared437/aggregator_local_merge/cluster_native"),
    Path(".cache/residual_bank_command_binding/physical/buffered_grant"),
)

HEADER = re.compile(rb"\s*module\s+[\w$]+\s*\(")
DIRECTION = re.compile(rb"\b(?:input|output)\s+wire\b")
PORT = re.compile(rb"(input|output)\s+wire\s+(\[\d+:\d+\]\s+)?([A-Za-z_$][\w$]*)")
NET_INITIALIZER = re.compile(
    rb"(?m)^([ \t]*wire[ \t]+(?:\[\d+:\d+\][ \t]+)?)([A-Za-z_$][\w$]*)"
    rb"[ \t]*=[ \t]*([^;]+);"
)


def normalize_module(source):
    """Make wire initializers explicit assignments and ANSI ports declarations."""
    header, delimiter, body = source.partition(b");")
    assert delimiter
    if DIRECTION.search(header):
        opening = HEADER.match(header)
        assert opening is not None
        ports, declarations = [], []
        for item in header[opening.end() :].split(b","):
            match = PORT.fullmatch(item.strip())
            assert match is not None, item
            direction, size, name = match.groups()
            ports.append(name)
            declarations.append(b"  " + direction + b" " + (size or b"") + name + b";")
        assert len(ports) == len(set(ports))
        header = header[: opening.end()] + b", ".join(ports)
        body = b"\n" + b"\n".join(declarations) + b"\n" + body
    body = NET_INITIALIZER.sub(
        lambda m: m[1] + m[2] + b";\n  assign " + m[2] + b" = " + m[3] + b";",
        body,
    )
    return header + delimiter + body


def compare_netlists(source, exported, top, scratch):
    """Use the existing exact pin and reachable-hierarchy comparison."""
    for root in REFERENCE_TOOLS:
        assert root.is_dir(), root
        sys.path.append(str(root))
    import verify_tri_oracle_placement_connectivity as checker
    from verify_reachable import compare

    read_module = checker.read_module
    checker.read_module = lambda raw: read_module(normalize_module(raw))
    try:
        return compare(source, exported, top, scratch)
    finally:
        checker.read_module = read_module


def verify(self_check=False):
    source = WORK / "linked.v"
    inputs = read(INPUTS)
    published_hash = inputs["evidence_sha256"][str(source)]
    assert digest(source) == published_hash
    exported = NATIVE / "cold/cold.v"
    if self_check:
        exported = source
        scope = "Self-comparison of the exact linked top exercises every reachable module before the native export is available."
    else:
        stage = NATIVE / "cold"
        status = read(stage / "status.json")
        assert status["exit_status"] == 0 and status["stop_reason"] is None
        assert re.search(
            r"(?m)^TRI_ORACLE_EXACT_SEED_NATIVE_PASS cold ",
            (stage / "console.log").read_text(),
        )
        scope = "Exact module ports, instance masters, named pin connections, and assignment bits match the cold Innovus logical export."
    result = compare_netlists(source, exported, TOP, NATIVE)
    assert result["physical_leaf_instances"] == inputs["physical_components"]
    files = (INPUTS, source, exported, Path(__file__).resolve().relative_to(ROOT))
    return {
        "state": "linked_netlist_comparator_self_check"
        if self_check
        else "cold_native_logical_connectivity_verified",
        **result,
        "scope": scope,
        "evidence_sha256": {str(path): digest(path) for path in files},
    }


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-check", action="store_true")
    print(json.dumps(verify(parser.parse_args().self_check), indent=2, sort_keys=True))
