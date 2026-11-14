"""Bind pre-route evidence to the latest cold-reloaded repeater placement."""

import argparse
from hashlib import file_digest
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
RECORDS = ROOT / "records"
REPEATER = RECORDS / "tri_oracle_partial_pad_repeater_placement.json"
PARENT_MEMORY = RECORDS / "tri_oracle_partial_pad_memory_roles.json"
PARENT_TIMING = RECORDS / "tri_oracle_partial_pad_slow_timing_memory_limit.json"
PARENT_FUNCTION = RECORDS / "tri_oracle_grouped_active_trained_feedforward.json"


def sha(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def read(path):
    return json.loads(path.read_text())


def exact_match(pattern, text):
    value, = re.findall(pattern, text, re.M)
    return value


def verify(gate_path=None):
    record = read(REPEATER)
    memory, timing, functional = map(read, (PARENT_MEMORY, PARENT_TIMING, PARENT_FUNCTION))
    parent = record["parent_mapped_netlist_sha256"]
    candidate = record["candidate_placement_netlist_sha256"]
    assert memory["candidate_netlist_sha256"] == timing["candidate_sha256"] == functional["candidate_netlist_sha256"] == parent
    assert candidate != parent and memory["compiled_macros"] == record["fixed_memory_macros"]

    paths = {}
    for item in (record, timing, functional):
        for name, digest in item["evidence_sha256"].items():
            assert paths.setdefault(name, digest) == digest, name
    for name, digest in paths.items():
        path = ROOT / name
        assert sha(path) == digest, name

    def source(suffix, item=record):
        name, = (name for name in item["evidence_sha256"] if name.endswith(suffix))
        return ROOT / name

    assert sha(source("/placed/candidate.v")) == candidate
    comparison = read(source("/netlist_check.json"))
    assert comparison["candidate_netlist_sha256"] == candidate
    assert comparison["parent_netlist_sha256"] == record["parent_placement_netlist_sha256"]
    assert comparison["modules"] == record["independently_compared_exported_verilog_modules"]
    assert comparison["changed_modules_reversed"] == record["inserted_repeaters"]
    assert comparison["evidence_sha256"][str(source("/native/pad_ring.v").relative_to(ROOT))] == record["parent_placement_netlist_sha256"]

    design = source("/placed/candidate.def")
    units = box = count = None
    with design.open() as stream:
        for line in stream:
            if match := re.fullmatch(r"UNITS DISTANCE MICRONS (\d+) ;\n", line):
                units = int(match[1])
            if match := re.fullmatch(r"DIEAREA \( (-?\d+) (-?\d+) \) \( (-?\d+) (-?\d+) \) ;\n", line):
                box = tuple(map(int, match.groups()))
            if match := re.fullmatch(r"COMPONENTS (\d+) ;\n", line):
                count = int(match[1])
                break
    assert units and box and count
    dimensions = [(box[axis + 2] - box[axis]) / units / 1000 for axis in (0, 1)]
    constraints = source("/candidate.sdc").read_text()
    assert exact_match(r"^set_units -time (\d+ps)$", constraints) == "1000ps"
    period = float(exact_match(r'^create_clock -name "core_clock" -period (\S+) ', constraints))
    placement = source("/cold/placement.rpt").read_text()
    placed, fixed = map(int, exact_match(r"^\*info: Placed = (\d+)\s+\(Fixed = (\d+)\)", placement))
    unplaced = int(exact_match(r"^\*info: Unplaced = (\d+)", placement))
    assert placed == count == record["unchanged_prior_instances"] + record["inserted_repeaters"]
    assert fixed == record["fixed_memory_macros"] and unplaced == 0
    assert read(source("/setup_slow/native_status.json", timing)) == timing["native"]
    native_function = read(source("/grouped_active_feedforward/receipt.json", functional))
    assert native_function["candidate_netlist_sha256"] == parent and native_function["native"]["exit_status"] == 0
    assert native_function["exact_feedforward_outputs"] == functional["exact_feedforward_outputs"]
    memory_path = ROOT / memory["evidence_file"]
    assert sha(memory_path) == memory["local_receipt_sha256"]
    memory_census = read(memory_path)
    for field in ("candidate_netlist_sha256", "compiled_bytes", "compiled_macros"):
        assert memory_census[field] == memory[field]

    for path in (REPEATER, PARENT_MEMORY, PARENT_TIMING, PARENT_FUNCTION, Path(__file__).resolve()):
        paths[str(path.relative_to(ROOT))] = sha(path)
    result = {
        "state": "cold_reloaded_repeater_placement_verified_against_candidate_exports",
        "candidate_placement_netlist_sha256": candidate,
        "parent_mapped_netlist_sha256": parent,
        "die_mm": dimensions,
        "core_clock_constraint_ns": period,
        "placed_instances": placed,
        "fixed_memory_macros": fixed,
        "unplaced_instances": unplaced,
        "netlist_modules_compared": comparison["modules"],
        "parent_compiled_memory_bytes": memory["compiled_bytes"],
        "parent_completed_slow_timing_paths": timing["completed_timing_paths"],
        "parent_exact_feedforward_values": functional["exact_feedforward_outputs"],
        "scope": "The cold placement geometry and clock constraint belong to the repeater export. The memory capacity, timing attempt and trained replay refer to its mapped parent.",
        "evidence_sha256": paths,
    }
    if gate_path is not None:
        gate = read(gate_path)
        assert not gate["advance_to_clock_distribution_or_routing_allowed"] and not gate["verification_errors"]
        result["paper_gate_candidate_sha256"] = gate["observed_facts"]["candidate_sha256"]
        paths[str(gate_path.relative_to(ROOT))] = sha(gate_path)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gate_report", type=Path, nargs="?")
    args = parser.parse_args()
    if not __debug__:
        raise RuntimeError("Run with Python assertions enabled")
    print(json.dumps(verify(args.gate_report.resolve() if args.gate_report else None), indent=2, sort_keys=True))
