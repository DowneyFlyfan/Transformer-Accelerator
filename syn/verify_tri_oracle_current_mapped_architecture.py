"""Verify the latest mapped compute and memory against the paper and the cold floorplan."""

import json
from pathlib import Path

from audit_tri_oracle_mapped_redundancy import audit
from audit_tri_oracle_physical_io_budget import PLACED, PROBE_REDUCED
from audit_tri_oracle_shared_prediction_roles import measure
from check_tri_oracle_paper300_gate import dimensions
from verify_tri_oracle_buffered_memory import placed_memory
from verify_tri_oracle_buffered_topology import PAPER_SHA256, verify_compute_arrays
from verify_tri_oracle_repeater_placement_evidence import (
    PARENT_MEMORY, RECORDS, ROOT, compiled_memory_inventory, read, sha, verify_compiled_memory,
)


def verify():
    assert __debug__ and Path("/.dockerenv").is_file()
    evidence = {}

    def pin(path, expected=None):
        name = str(path.relative_to(ROOT))
        if name not in evidence:
            evidence[name] = sha(path)
        if expected is not None and evidence[name] != expected:
            raise ValueError(f"Changed evidence: {name}")
        return path

    def record(name):
        return read(pin(RECORDS / name))

    targets = record("paper_result_targets.json")
    pin(ROOT / targets["source"], PAPER_SHA256)
    silicon = targets["silicon"]
    probes = record("tri_oracle_internal_writeback_probes.json")
    repeaters = record("tri_oracle_descriptor_repeaters_seed.json")
    placed = record("tri_oracle_buffered_grant_whole_chip_cold_reload.json")
    assert probes["parent_candidate_sha256"] == repeaters["candidate_sha256"]
    candidate = pin(PROBE_REDUCED / "candidate.v", probes["candidate_sha256"])
    seed = pin(PROBE_REDUCED.parent / "seed.def", repeaters["seed_sha256"])
    cold = PLACED / "cold/cold.def"
    pin(cold, placed["evidence_sha256"][str(cold.relative_to(ROOT))])
    box = list(dimensions(cold))
    assert box == list(dimensions(seed)) == silicon["die_dimensions_mm"]

    graph, macros = compiled_memory_inventory(candidate, seed)
    with cold.open() as stream:
        assert macros == placed_memory(stream), "Mapped memory differs from the native cold floorplan"
    assert len(macros) == repeaters["unchanged_fixed_memories"] == placed["fixed_memories"]
    memory = read(pin(PARENT_MEMORY))
    prior = read(pin(ROOT / memory["evidence_file"], memory["local_receipt_sha256"]))
    compiled = verify_compiled_memory(macros, PLACED / "native/placed.db", prior, evidence)
    assert compiled["paper_label_kb"] == silicon["sram_published_KB"]

    topology = audit(graph)
    clusters = topology["clusters"]
    assert len(clusters) == silicon["clusters"]
    assert all(cluster["cores"] == silicon["cores_per_cluster"] for cluster in clusters)
    compute = verify_compute_arrays(candidate, graph, targets)
    shared = measure(candidate)
    for method in (verify, dimensions, compiled_memory_inventory, placed_memory,
                   verify_compiled_memory, audit, verify_compute_arrays, measure):
        pin(Path(method.__code__.co_filename).resolve())
    for path in (candidate, seed, cold):
        assert sha(path) == evidence[str(path.relative_to(ROOT))], path
    return {
        "state": "current_mapped_compute_and_compiled_memory_verified",
        "candidate_sha256": probes["candidate_sha256"],
        "placement_seed_sha256": repeaters["seed_sha256"],
        "cold_floorplan_candidate_sha256": placed["candidate_sha256"],
        "paper_sha256": PAPER_SHA256,
        "die_dimensions_mm": box,
        "clusters": clusters,
        "compute": compute,
        "compiled_memory": compiled,
        "shared_prediction_roles": shared,
        "scope": (
            "Reachable compute arrays and prediction units in the current mapped netlist. Every compiled "
            "memory instance and master agrees with the current seed, the preceding native cold floorplan "
            "and the independently replayed memory census. The compiled memory capacities are derived "
            "from the compiler views. Peak operations assume the paper's clock. The seed is proposed "
            "geometry for the current revision. Native placement, timing and full functional qualification "
            "have separate acceptance checks."
        ),
        "evidence_sha256": evidence,
    }


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2, sort_keys=True))
