"""Bind pre-route evidence to the latest cold-reloaded repeater placement."""

import argparse
from hashlib import file_digest
import json
from pathlib import Path
import re

from audit_tri_oracle_mapped_redundancy import TOP, audit, hierarchy
from audit_tri_oracle_shared_prediction_roles import measure
from verify_tri_oracle_buffered_memory import PREFIXES, placed_memory, replay_memory
from verify_tri_oracle_buffered_topology import verify_compute_arrays
from verify_tri_oracle_pad_memory import compiler_sizes, memory_roles
from verify_tri_oracle_pad_restored_models import library_contents, observations

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


def compiled_memory_inventory(netlist, design, *, top=TOP):
    graph = hierarchy(netlist, include_memory=True)
    macros = {}

    def walk(master, prefix, ancestors):
        if master in ancestors:
            raise ValueError(f"Recursive module in memory inventory: {prefix}")
        for instance, child in graph[master].items():
            path = prefix + instance.removeprefix("\\")
            if child.startswith(PREFIXES):
                if path in macros:
                    raise ValueError(f"Ambiguous compiled memory path: {path}")
                macros[path] = child
            else:
                walk(child, path + ".", ancestors | {master})

    walk(top, "", set())
    with design.open() as stream:
        if macros != placed_memory(stream):
            raise ValueError("Compiled memory instances or masters differ between the netlist and placement")
    for children in graph.values():
        for instance in [name for name, child in children.items() if child.startswith(PREFIXES)]:
            del children[instance]
    return graph, macros


def verify_compiled_memory(macros, database, parent_census, paths):
    replay_name, = (name for name in parent_census["evidence_sha256"]
                    if name.endswith("/grouped_reset_xcelium_serial/xrun.log"))
    replay_log = ROOT / replay_name
    paths[replay_name] = parent_census["evidence_sha256"][replay_name]
    assert sha(replay_log) == paths[replay_name], replay_name
    with replay_log.open() as stream:
        assert replay_memory(stream) == macros, replay_name

    compiler_views = set()
    for name, expected in parent_census["evidence_sha256"].items():
        source = ROOT / name
        if source.parent.name in {"LEF", "NLDM", "VERILOG"}:
            assert sha(source) == expected, name
            compiler_views.add(source)
            paths[name] = expected
            if source.suffix in {".lef", ".lib"}:
                directory = "lef" if source.suffix == ".lef" else "mmmc"
                bound = database / "libs" / directory / source.name
                assert sha(bound) == expected, bound
                paths[str(bound.relative_to(ROOT))] = expected
    sizes = compiler_sizes(compiler_views, set(macros.values()))
    roles = memory_roles(macros, sizes)
    total = sum(sizes[master] for master in macros.values())
    for name, value in roles.items():
        assert json.dumps(value, sort_keys=True) == json.dumps(parent_census[name], sort_keys=True), name
    assert total == parent_census["compiled_bytes"]
    paper_label_kb = parent_census["paper_label_kb"]
    assert (total + 512) // 1024 == paper_label_kb
    return dict(compiled_macros=len(macros), compiled_bytes=total, paper_label_kb=paper_label_kb,
                difference_from_binary_label_bytes=total - paper_label_kb * 1024,
                difference_from_decimal_label_bytes=total - paper_label_kb * 1000,
                timing_views_checked=sum(path.suffix == ".lib" for path in compiler_views), **roles)


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

    netlist = source("/placed/candidate.v")
    assert paths[str(netlist.relative_to(ROOT))] == candidate
    comparison = read(source("/netlist_check.json"))
    assert comparison["candidate_netlist_sha256"] == candidate
    assert comparison["parent_netlist_sha256"] == record["parent_placement_netlist_sha256"]
    assert comparison["modules"] == record["independently_compared_exported_verilog_modules"]
    assert comparison["changed_modules_reversed"] == record["inserted_repeaters"]
    assert comparison["evidence_sha256"][str(source("/native/pad_ring.v").relative_to(ROOT))] == record["parent_placement_netlist_sha256"]

    design = source("/placed/candidate.def")
    database = netlist.with_suffix(".db")
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

    graph, macros = compiled_memory_inventory(netlist, design)
    topology = audit(graph)
    assert len(macros) == fixed
    compiled = verify_compiled_memory(macros, database, memory_census, paths)
    parent_result_path = ROOT / "records/tri_oracle_partial_pad_native_cold_result.json"
    parent_result = read(parent_result_path)
    parent_cold_path = source("/cold_native/receipt.json", parent_result)
    assert sha(parent_cold_path) == parent_result["evidence_sha256"][str(parent_cold_path.relative_to(ROOT))]
    parent_cold = read(parent_cold_path)
    assert parent_cold["candidate_sha256"] == parent
    parent_libraries = {name.removeprefix("libs/"): metadata["sha256"]
                        for name, metadata in parent_cold["checkpoint"]["files"].items()
                        if name.startswith("libs/")}
    library_dir = database / "libs"
    libraries = library_contents(library_dir)
    assert len(libraries) == 33 and libraries == parent_libraries
    console = source("/cold/console.log").read_text()
    assert console.splitlines().count("TRI_ORACLE_GROUPED_RESET_repeater_cold_PASS") == 1
    observations(console, library_dir, libraries)
    for name, checksum in libraries.items():
        paths[str((library_dir / name).relative_to(ROOT))] = checksum

    targets_path = RECORDS / "paper_result_targets.json"
    paper_targets = read(targets_path)
    targets = paper_targets["silicon"]
    assert len(topology["clusters"]) == targets["clusters"]
    assert all(cluster["cores"] == targets["cores_per_cluster"] for cluster in topology["clusters"])
    topology["compute_arrays"] = verify_compute_arrays(netlist, graph, paper_targets)
    topology["shared_prediction_roles"] = measure(netlist)
    assert compiled["paper_label_kb"] == targets["sram_published_KB"]
    assert sha(netlist) == candidate and sha(design) == paths[str(design.relative_to(ROOT))]

    for path in (REPEATER, PARENT_MEMORY, PARENT_TIMING, PARENT_FUNCTION, memory_path, targets_path,
                 parent_cold_path, Path(__file__).resolve(), *(Path(method.__code__.co_filename).resolve()
                    for method in (audit, measure, verify_compute_arrays, placed_memory, compiler_sizes, observations))):
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
        "candidate_topology": topology,
        "candidate_compiled_memory": compiled,
        "original_full_models_verified": True,
        "cold_loaded_library_and_constraint_files": len(libraries),
        "parent_completed_slow_timing_paths": timing["completed_timing_paths"],
        "parent_exact_feedforward_values": functional["exact_feedforward_outputs"],
        "scope": "The cold geometry, clock constraint, cluster hierarchy and compiled memory inventory belong to the repeater export. The timing attempt and trained replay refer to its mapped parent.",
        "evidence_sha256": paths,
    }
    if gate_path is not None:
        gate = read(gate_path)
        assert not gate["advance_to_clock_distribution_or_routing_allowed"] and not gate["verification_errors"]
        assert gate["observed_facts"]["candidate_sha256"] == candidate
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
