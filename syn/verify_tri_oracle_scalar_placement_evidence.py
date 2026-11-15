"""Verify the cold scalar placement's compute topology and compiled memory."""
import json
import math
from pathlib import Path
import re

from audit_tri_oracle_mapped_redundancy import audit
from audit_tri_oracle_shared_prediction_roles import measure
from check_tri_oracle_paper300_gate import dimensions, VIEWS
from tri_oracle_artifact_fingerprint import artifact_fingerprint
from verify_tri_oracle_buffered_topology import PAPER_SHA256, verify_compute_arrays
from verify_tri_oracle_pad_restored_models import library_contents, observations
from verify_tri_oracle_repeater_placement_evidence import (
    PARENT_MEMORY, RECORDS, ROOT, compiled_memory_inventory, exact_match,
    verify_compiled_memory, read, sha,
)

LAYOUT = (ROOT / ".cache/placement_coordinate_reuse/trained_layer11_boundary"
          / "placed_residual_bank_taps/structural_writeback_control/scalar")


def verify(*, guarded=False):
    assert __debug__ and Path("/.dockerenv").is_file()
    evidence = {}

    def pin(path, expected=None):
        name = str(path.relative_to(ROOT))
        if name not in evidence:
            evidence[name] = sha(path)
        assert expected is None or evidence[name] == expected, name
        return path

    original = read(pin(RECORDS / "tri_oracle_scalar_whole_chip_cold_reload.json"))
    library_record = read(pin(RECORDS / "tri_oracle_scalar_native_timing_inputs.json"))
    paper = read(pin(RECORDS / "paper_result_targets.json"))
    pin(ROOT / paper["source"], PAPER_SHA256)
    stage = LAYOUT / "placement_seed"
    candidate = LAYOUT / "chip.v"
    cold = original
    if guarded:
        cold = read(pin(RECORDS / "tri_oracle_guarded_scalar_whole_chip_cold_reload.json"))
        assert cold["state"] == "guarded_scalar_native_placement_and_fresh_reload_verified"
        variant = stage / "bank_ownership_cut/guard"
        stage = variant / "placement_explicit"
        candidate = variant / "guarded_chip_explicit.v"
        link_file = variant / "link_explicit.json"
        link = read(pin(link_file, cold["evidence_sha256"][str(link_file.relative_to(ROOT))]))
        assert link["parent_candidate_sha256"] == original["candidate_sha256"]
        assert link["inserted_guard_instances"] == 4
        assert link["evidence_sha256"][str(candidate.relative_to(ROOT))] == cold["candidate_sha256"]
    identity = cold["candidate_sha256"]
    assert library_record["scalar_candidate_sha256"] == original["candidate_sha256"]
    pin(candidate, identity)

    reload = stage / "cold"
    db = stage / "native/placed.db"

    def cold_file(name):
        path = reload / name
        return pin(path, cold["evidence_sha256"][str(path.relative_to(ROOT))])

    receipt = read(cold_file("cold_receipt.json"))
    assert receipt["state"] == "whole_chip_placement_cold_reload_and_coordinate_comparison_passed"
    fingerprint = artifact_fingerprint(db)
    assert fingerprint == receipt["database_fingerprint"], db
    coordinate_record = read(pin(reload / "independent_coordinates.json",
                                 receipt["coordinate_verification_sha256"]))
    assert coordinate_record["candidate_sha256"] == identity
    assert coordinate_record["exact_reachable_connectivity"] == cold["exact_reachable_connectivity"]
    assert cold["cold_native"]["exit_status"] == 0

    design, netlist = cold_file("cold.def"), cold_file("cold.v")
    die_mm = list(dimensions(design))
    silicon = paper["silicon"]
    assert die_mm == silicon["die_dimensions_mm"], die_mm
    placement = cold_file("placement.rpt").read_text()
    placed, fixed = map(int, exact_match(r"^\*info: Placed = (\d+)\s+\(Fixed = (\d+)\)", placement))
    unplaced = int(exact_match(r"^\*info: Unplaced = (\d+)", placement))
    assert unplaced == 0 and fixed == cold["fixed_memories"]
    assert placed == cold["exact_reachable_connectivity"]["physical_leaf_instances"]
    assert placed == cold["standard_cells"] + fixed

    clock_period = 1000 / paper["peak"]["clock_megahertz"]
    periods = {}
    for view in sorted(VIEWS):
        constraint = cold_file(f"{view}.sdc").read_text()
        assert exact_match(r"^set_units -time (\S+) ", constraint) == "1ns"
        period = float(exact_match(r"^create_clock \[get_ports \{clk\}\]  -name core -period (\S+) ", constraint))
        assert math.isclose(period, clock_period, rel_tol=0, abs_tol=1e-5), view
        periods[view] = period

    library_dir = db / "libs"
    libraries = library_contents(library_dir)
    expected_models = {}
    for name, digest in library_record["library_manifest_sha256"].items():
        path = ROOT / name
        if path.is_relative_to(ROOT / ".cache/physical"):
            assert path.suffix in {".lef", ".tlef"}, name
            destination = f"lef/{path.name}"
        else:
            destination = name.split("/candidate.db/libs/", 1)[1]
        assert destination not in expected_models, destination
        expected_models[destination] = digest
        pin(path, digest)
    model_inputs = libraries.copy()
    del model_inputs["mmmc/candidate.sdc"]
    assert len(expected_models) == 32 and model_inputs == expected_models
    for name, digest in libraries.items():
        assert fingerprint["files"][f"libs/{name}"]["sha256"] == digest, name
    console = cold_file("console.log").read_text()
    success, = re.findall(r"(?m)^SCALAR_COLD_CHIP_PLACEMENT_VERIFIED (\d+) (\d+) [\d.]+$", console)
    assert tuple(map(int, success)) == (placed, cold["physical_boundary_pins"])
    observations(console, library_dir, libraries)

    graph, macros = compiled_memory_inventory(netlist, design)
    assert len(macros) == fixed
    topology = audit(graph)
    assert len(topology["clusters"]) == silicon["clusters"]
    assert all(cluster["cores"] == silicon["cores_per_cluster"] for cluster in topology["clusters"])
    arrays = verify_compute_arrays(netlist, graph, paper)
    shared = measure(netlist)

    historical = read(pin(PARENT_MEMORY))
    prior = read(pin(ROOT / historical["evidence_file"], historical["local_receipt_sha256"]))
    memory = verify_compiled_memory(macros, db, prior, evidence)
    assert memory["paper_label_kb"] == silicon["sram_published_KB"]
    for method in (dimensions, artifact_fingerprint, audit, measure, verify_compute_arrays,
                   observations, compiled_memory_inventory):
        pin(Path(method.__code__.co_filename).resolve())
    pin(Path(__file__).resolve())
    return {
        "state": "scalar_cold_placement_compute_geometry_and_compiled_memory_verified",
        "candidate_sha256": identity,
        "paper_sha256": PAPER_SHA256,
        "die_mm": die_mm,
        "die_area_mm2": round(math.prod(die_mm), 8),
        "placed_instances": placed,
        "unplaced_instances": unplaced,
        "constraint_period_by_view_ns": periods,
        "loaded_model_count": len(model_inputs),
        "clusters": topology["clusters"],
        "compute": arrays,
        "shared_prediction_roles": shared,
        "compiled_memory": memory,
        "scope": (
            "Cold placement structure and memory capacity. The paper's SRAM label is matched "
            "after binary rounding; peak operations assume the paper clock. Trained end-to-end "
            "execution, extracted timing, and accuracy require separate evidence."
        ),
        "evidence_sha256": evidence,
    }


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2, sort_keys=True))
