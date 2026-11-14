"""Reconcile the buffered placement's memory against the paper and native models."""

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re

from audit_tri_oracle_memory355_accounting import capacity_bytes, sha
from audit_tri_oracle_pad_ring_clearance import POSE


ROOT = Path(__file__).resolve().parents[1]
PREFIXES = ("TS5N28", "TS6N28")
IMPORT = Path(".cache/model_reference/lossless_weight_burst_probe/streaming_probe/aligned/"
              "partial_retention/indexed_down/group_value_budget/grouped_command/"
              "concurrent_cluster_chip/physical_parent_replay/innovus_import_rebound")
TIMING_READ = re.compile(r"(?m)^Reading ls_\w+ timing library '?([^'\s]+\.lib)'?(?:\s+\.\.\.|\.)?$")
CENSUS_PREFIX = "TRI_ORACLE_MAPPED_CENSUS "
CENSUS_TOP = "tri_oracle_native_grouped_command_tb.dut."
CENSUS_SUFFIX = ".mapped_hierarchy_probe"
PAPER_SHA256 = "6d6b998c459ade605e082d723374462e1d14b53d6a6b13063ca0f8d1180b1d9f"


def replay_memory(lines):
    macros = {}
    for line in lines:
        if not line.startswith(tuple(CENSUS_PREFIX + prefix for prefix in PREFIXES)):
            continue
        _, master, hierarchy = line.split(maxsplit=2)
        path = re.sub(r"[\\\s]", "", hierarchy)
        assert path.startswith(CENSUS_TOP) and path.endswith(CENSUS_SUFFIX), path
        name = path.removeprefix(CENSUS_TOP).removesuffix(CENSUS_SUFFIX)
        assert name and name not in macros, name
        macros[name] = master
    return macros


def placed_memory(stream):
    for line in stream:
        if re.fullmatch(r"COMPONENTS \d+ ;\n", line):
            break
    else:
        raise ValueError("Missing placement component section")
    result = {}
    for line in stream:
        if line == "END COMPONENTS\n":
            return result
        if not line.startswith("- "):
            continue
        _, name, master, *_ = line.split(maxsplit=3)
        if not master.startswith(PREFIXES):
            continue
        match = POSE.match(line)
        assert match and match[3] == "FIXED", name
        name = name.replace("\\", "").replace("/", ".")
        assert name not in result, name
        result[name] = master
    raise ValueError("Unterminated placement component section")


def verify(work):
    assert __debug__ and Path("/.dockerenv").is_file()
    evidence = {}

    def pin(path, expected=None):
        if path not in evidence:
            evidence[path] = sha(path)
        assert expected is None or evidence[path] == expected, path
        return path

    def record(name):
        return json.loads(pin(ROOT / "records" / name).read_bytes())

    placement = record("tri_oracle_grouped_active_placement.json")
    graph = record("tri_oracle_grouped_active_graph.json")
    replay = record("tri_oracle_grouped_reset_replay.json")
    imported = record("tri_oracle_concurrent_imported_chip_trained_replay.json")
    capacity = json.loads(pin(ROOT / IMPORT / "memory_capacity_receipt.json",
                              imported["evidence_sha256"]["compiled_memory_audit"]).read_bytes())
    candidate = placement["candidate_netlist_sha256"]
    assert candidate == graph["candidate_netlist_sha256"]
    assert placement["parent_netlist_sha256"] == graph["parent_netlist_sha256"] == replay["buffered_netlist_sha256"]
    assert replay["reference_netlist_sha256"] == capacity["candidate_sha256"] == imported["netlist_sha256"]
    assert replay["native"]["xcelium_exit_status"] == 0
    pin(work / "apply/active.v", candidate)
    exported = pin(work / "apply/active.def", placement["placed_design_exchange_sha256"])
    with exported.open() as source:
        macros = placed_memory(source)
    source_path = ROOT / IMPORT / "macros.tsv"
    reference = [line.replace("/", ".").split("\t") for line in
                 pin(source_path, capacity["input_sha256"][str(source_path)]).read_text().splitlines()]
    assert len(reference) == len(macros) and macros == dict(reference)
    assert len(macros) == placement["preserved_fixed_memory_instances"] == replay["memory_macros"] == 631

    log = ROOT / ".cache/placement_coordinate_reuse/grouped_reset_xcelium_serial/xrun.log"
    with pin(log, replay["evidence_sha256"][str(log.relative_to(ROOT))]).open() as lines:
        assert replay_memory(lines) == macros

    cold = work / "cold_exact/console.log"
    cold_text = pin(cold, placement["evidence_sha256"][str(cold.relative_to(ROOT))]).read_text()
    assert cold_text.splitlines().count("GROUPED_ACTIVE_cold_PASS") == 1
    compiler_files = {Path(path): checksum for path, checksum in capacity["input_sha256"].items()
                      if Path(path).parent.name in {"LEF", "NLDM", "VERILOG"}}
    database = work / "apply/active.db"
    native_timing = {Path(path).name: Path(path) for path in TIMING_READ.findall(cold_text)
                     if Path(path).name.upper().startswith(PREFIXES)}
    expected_timing = {path.name for path in compiler_files if path.suffix == ".lib"}
    assert set(native_timing) == expected_timing and len(expected_timing) == 18
    for path, checksum in compiler_files.items():
        pin(path, checksum)
        if path.suffix == ".lef":
            physical = pin(database / "libs/lef" / path.name, checksum)
            assert f"Loading LEF file {physical} ..." in cold_text.splitlines()
        if path.suffix == ".lib":
            pin(native_timing[path.name], checksum)
            pin(database / "libs/mmmc" / path.name, checksum)

    counts = Counter(macros.values())
    per_instance = {}
    for model in (path for path in compiler_files if path.suffix == ".v"):
        source = model.read_text()
        master, = set(re.findall(r"\bmodule\s+(TS[56]N28\w+)\b", source)) & counts.keys()
        assert master not in per_instance
        per_instance[master] = capacity_bytes(source, master)
    assert per_instance.keys() == counts.keys() and per_instance == capacity["capacity_bytes_by_master"]
    total = sum(per_instance[master] * count for master, count in counts.items())
    assert counts == capacity["count_by_master"] and total == capacity["capacity_bytes"]
    targets = record("paper_result_targets.json")
    pin(ROOT / targets["source"], PAPER_SHA256)
    label = targets["silicon"]["sram_published_KB"]
    assert (total + 512) // 1024 == label == capacity["paper_capacity_label_kb"]
    pin(Path(__file__).resolve())
    pin(ROOT / "syn/audit_tri_oracle_memory355_accounting.py")
    pin(ROOT / "syn/audit_tri_oracle_pad_ring_clearance.py")
    assert all(sha(path) == expected for path, expected in evidence.items())
    manifest = {str(path.relative_to(ROOT)): digest for path, digest in evidence.items()}
    return dict(
        state="buffered_placement_memory_capacity_independently_reconciled",
        candidate_netlist_sha256=candidate,
        placement_definition_sha256=evidence[exported],
        compiled_memory_instances=len(macros), compiled_memory_bytes=total,
        paper_capacity_label_kb=label,
        exact_paper_capacity_in_bytes_published=False,
        compiler_timing_views=len(expected_timing),
        evidence_file_count=len(evidence),
        evidence_manifest_sha256=sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest(),
        scope="Exact instance paths compared against the reset-buffered Xcelium replay and "
              "the grouped-active placement export. Capacity uses compiler geometry and cold-loaded "
              "physical and timing views. The paper's 405 KB label agrees at rounded binary precision.",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work", type=lambda path: Path(path).resolve())
    print(json.dumps(verify(parser.parse_args().work), indent=2, sort_keys=True))
