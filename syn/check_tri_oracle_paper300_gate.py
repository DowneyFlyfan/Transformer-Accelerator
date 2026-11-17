"""Fail closed before advancing the current placement candidate to clocks/routing.

Figures31.6.2,31.6.6 and31.6.7 supply the scale, frequency and die targets.
The paper labels memory405KB without fixing the decimal/binary convention here;
a separately qualified complete memory accounting must reconcile that label.
Core counts, analytic arithmetic tests and a template die alone do not qualify
the complete architecture, trained mapped execution or matching model accuracy.

Restoration, cold reload and timing diagnostics belong to verification of the
current placement step. Corrective work remains permitted when this gate fails.
This version remains hold-only while architecture, full trained mapped
execution, and matching accuracy lack independent candidate-bound proof.
The registered-write memory check verifies its local evidence against the
recorded candidate and original paper.
Physical subchecks are reported, but this version never authorizes advancement.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys

PAPER_RELATIVE = 'Paper/Tri-Oracle - A 17.78μJ per Token Vision-Language Model Accelerator with Token-Attention-Weight Redundancy Prediction.pdf'
PAPER_SHA256 = "6d6b998c459ade605e082d723374462e1d14b53d6a6b13063ca0f8d1180b1d9f"
VIEWS = frozenset(["setup_slow", "setup_typ", "hold_fast"])
LEGACY_QUALIFICATION = Path("records/placement296_qualification.json")
UNIMPLEMENTED_VERIFIERS = (
    "complete_paper_architecture_verified", "trained_mapped_layer_verified",
    "paper_accuracy_protocol_verified")
REGISTERED_WRITE = Path(".cache/model_reference/lossless_weight_burst_probe/streaming_probe/aligned/partial_retention/indexed_down/wide_values/fused_request/score_packet/partition/registered_load")
MAPPED_PIPELINE = REGISTERED_WRITE / "token_merge_pipeline"
CONCURRENT_GROUP = Path(".cache/model_reference/lossless_weight_burst_probe/streaming_probe/aligned/partial_retention/indexed_down/group_value_budget/grouped_command")
CONCURRENT_IMPORT = CONCURRENT_GROUP / "concurrent_cluster_chip/physical_parent_replay/innovus_import_rebound"
REPEATER_PLACEMENT = Path("records/tri_oracle_partial_pad_repeater_placement.json")
SCALAR_PLACEMENT = Path("records/tri_oracle_scalar_whole_chip_cold_reload.json")
GUARDED_SCALAR_PLACEMENT = Path("records/tri_oracle_guarded_scalar_whole_chip_cold_reload.json")
BUFFERED_GRANT_PLACEMENT = Path("records/tri_oracle_buffered_grant_whole_chip_cold_reload.json")
REDUCED_PORT_PLACEMENT = Path("records/tri_oracle_reduced_port_placement_and_reload.json")
TOKEN_TREE_PLACEMENT = Path("records/tri_oracle_full_native_token_tree_placement.json")
BOUNDED_MAPPED_STRUCTURE = Path("records/tri_oracle_bounded_decoder_mapped_paper_structure.json")
BOUNDED_RAW_REPLAY = Path("records/tri_oracle_bounded_decoder_native_raw_replay.json")
BOUNDED_INDEXED_REPLAY = Path("records/tri_oracle_bounded_decoder_native_indexed_replay.json")
BOUNDED_NATIVE_PLACEMENT = Path("records/tri_oracle_bounded_decoder_native_placement.json")
BOUNDED_RESET_PLACEMENT = Path("records/tri_oracle_bounded_decoder_reset_native_placement.json")
BOUNDED_PROBABILITY_PLACEMENT = Path("records/tri_oracle_bounded_decoder_probability_native_placement.json")
BOUNDED_PROBABILITY_SEED = Path("records/tri_oracle_bounded_decoder_probability_buffer_seed.json")
BOUNDED_TOKEN_MAP_PLACEMENT = Path("records/tri_oracle_bounded_decoder_token_map_native_placement.json")
BOUNDED_RESIZED_PLACEMENT = Path("records/tri_oracle_whole_chip_value_register_placement.json")
BOOTH_PLACEMENT = Path("records/tri_oracle_corrected_booth_placement_roundtrip.json")
BOOTH_BUFFERED_PLACEMENT = Path("records/tri_oracle_corrected_booth_buffered_placement_roundtrip.json")
BOOTH_COMPUTE = Path("records/tri_oracle_booth_chip_compute_geometry.json")
BOOTH_MEMORY = Path("records/tri_oracle_booth_compiled_memory.json")
BOOTH_REDUNDANCY = Path("records/tri_oracle_corrected_booth_redundancy_topology.json")
BOOTH_MODELS = Path("records/tri_oracle_corrected_booth_physical_models.json")
BOOTH_BUFFERED_MODELS = Path("records/tri_oracle_corrected_booth_buffered_models.json")
BOOTH_BUFFER_REPAIR = Path("records/tri_oracle_corrected_booth_pin_load_repair.json")
BOOTH_STREAMING = Path("records/tri_oracle_corrected_booth_streaming_packet.json")
BOOTH_FEEDFORWARD = Path("records/tri_oracle_corrected_booth_feedforward_replay.json")
BOOTH_CLOCK_BOUNDARY = Path("records/tri_oracle_corrected_booth_clock_boundary.json")
BOUNDED_STAGE = Path(".cache/indexed_whole_chip/dual_group_probe/bounded_decoder")
REPAIRED_NATIVE_RESOURCES = Path("records/tri_oracle_repaired_native_compute_and_memory.json")
REDUCED_PORT_STAGE = Path(".cache/residual_command_request/descriptor_fields/physical/command_repeaters/internal_probes")
SCALAR_PLACEMENT_STAGES = {
    BUFFERED_GRANT_PLACEMENT: "cold Innovus buffered grant placement",
    GUARDED_SCALAR_PLACEMENT: "cold Innovus guarded scalar placement",
    SCALAR_PLACEMENT: "cold Innovus scalar placement",
}


def qualification_source(root, requested, *previous):
    if requested is not None:
        return requested.resolve()
    for candidate in (BOOTH_BUFFERED_PLACEMENT, BOOTH_PLACEMENT, BOUNDED_RESIZED_PLACEMENT,
                      BOUNDED_TOKEN_MAP_PLACEMENT, BOUNDED_PROBABILITY_PLACEMENT,
                      BOUNDED_RESET_PLACEMENT, BOUNDED_MAPPED_STRUCTURE,
                      TOKEN_TREE_PLACEMENT, REDUCED_PORT_PLACEMENT,
                      *SCALAR_PLACEMENT_STAGES, REPEATER_PLACEMENT):
        placement = root / candidate
        if placement.is_file():
            return placement
    concurrent = root / CONCURRENT_IMPORT
    if concurrent.is_dir():
        return concurrent / "receipt.json"
    return next((path for path in previous if path.is_file()), root / LEGACY_QUALIFICATION)



def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def placement_checks(facts):
    required = [
        "candidate_cold_qualified", "native_workers_terminal", "original_full_models_verified",
        "high_fanout_substitution_disabled"]
    checks = {key: facts.get(key) is True for key in required}
    # There is no verified positive path for these requirements in this version.
    # Ignore caller/receipt Boolean claims until real candidate-bound verifiers
    # are implemented and independently reviewed.
    checks.update(dict.fromkeys(UNIMPLEMENTED_VERIFIERS, False))
    checks["memory_capacity_reconciled"] = False
    checks["paper_five_clusters_twenty_cores"] = facts.get("clusters") == 5 and facts.get("cores") == 20
    checks["paper_compute_array_geometry"] = (facts.get("array_instances") == 20
                                               and facts.get("array_geometry") == [32, 8]
                                               and facts.get("operand_bits") == 8)
    checks["paper_3_6_millimeter_die"] = all(
        finite(facts.get(key)) and math.isclose(facts[key], 3.6, rel_tol=0, abs_tol=1e-6)
        for key in ["die_width_mm", "die_height_mm"])
    period = facts.get("clock_period_ns")
    checks["paper_580_megahertz_period"] = finite(period) and math.isclose(
        period, 1000/580, rel_tol=0, abs_tol=1e-5)
    slacks = facts.get("corner_slack_ns")
    checks["all_three_original_corner_slacks_nonnegative"] = (
        isinstance(slacks, dict) and set(slacks) == VIEWS
        and all(finite(value) and value >= 0 for value in slacks.values())
        and not any(facts.get("detailed_analysis_skipped_nets", {}).values()))
    return checks


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def dimensions(path):
    units = die = None
    with Path(path).open() as stream:
        for line in stream:
            match = re.match(r"UNITS DISTANCE MICRONS (\d+) ;", line)
            if match:
                units = int(match[1])
            match = re.match(r"DIEAREA \( (-?\d+) (-?\d+) \) \( (-?\d+) (-?\d+) \) ;", line)
            if match:
                die = tuple(map(int, match.groups()))
                break
    if not units or not die or die[2] <= die[0] or die[3] <= die[1]:
        raise ValueError("Missing or invalid native die dimensions")
    return ((die[2]-die[0])/units/1000, (die[3]-die[1])/units/1000)


def pin_booth(root, identities, name, expected=None):
    path = root / name
    key = str(path)
    if key not in identities:
        identities[key] = sha(path)
    assert expected is None or identities[key] == expected, f"Changed Booth evidence: {path}"
    return path


def booth_record(root, identities, path, state):
    evidence = json.loads(pin_booth(root, identities, path).read_text())
    assert evidence["state"] == state
    for name, checksum in evidence["evidence_sha256"].items():
        pin_booth(root, identities, name, checksum)
    return evidence


def corrected_booth_facts(root, facts, identities):
    """Bind the cold placement and structural checks to the same Booth candidate."""
    from tri_oracle_artifact_fingerprint import artifact_fingerprint

    def pin(name, expected=None):
        return pin_booth(root, identities, name, expected)

    def checked_record(path, state):
        return booth_record(root, identities, path, state)

    placed = checked_record(BOOTH_PLACEMENT, "corrected_booth_placement_reload_and_connectivity_verified")
    compute = checked_record(BOOTH_COMPUTE, "corrected_full_chip_compute_geometry_bound_to_mapped_replay")
    memory = checked_record(BOOTH_MEMORY, "booth_candidate_compiled_memory_bound_to_netlist_and_seed")
    redundancy = checked_record(BOOTH_REDUNDANCY, "corrected_linked_chip_redundancy_ownership_verified")
    database = Path(placed["database"])
    assert database.name == "placed.db" and database.parent.name == "import"
    stage = database.parents[1]
    seed_name, linked_name, cold_name = (
        str(stage / name) for name in ("seed.def", "linked.v", "cold/cold.v")
    )
    proofs = placed["evidence_sha256"]
    candidate = proofs[linked_name]
    for record in (compute, memory):
        assert record["evidence_sha256"][linked_name] == candidate
        assert record["evidence_sha256"][seed_name] == proofs[seed_name]
    assert redundancy["candidate_sha256"] == candidate
    assert redundancy["logical_top"] == placed["top"]
    fingerprint = artifact_fingerprint(root / database)
    encoded = json.dumps(fingerprint, sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(encoded).hexdigest() == placed["database_fingerprint_sha256"]
    if (root / BOOTH_MODELS).is_file():
        models = checked_record(BOOTH_MODELS, "corrected_booth_full_models_loaded_from_pinned_sources")
        assert models["database_fingerprint_sha256"] == placed["database_fingerprint_sha256"]
        assert models["linked_netlist_sha256"] == candidate and models["cold_netlist_sha256"] == proofs[cold_name]
        assert models["compiled_memory_instances"] == placed["geometry"]["fixed_memory_macros"]
        facts["original_full_models_verified"] = True

    width, height = dimensions(root / stage / "cold/layout.def")
    assert [width, height] == placed["die_dimensions_mm"] == compute["die_dimensions_mm"]
    assert set(placed["views"]) == VIEWS
    periods = set()
    for corner in VIEWS:
        constraint = str(stage / "cold" / (corner + ".sdc"))
        text = pin(constraint, proofs[constraint]).read_text()
        (period,) = re.findall(r"(?m)^create_clock .* -name core_clock -period ([\d.]+)\b", text)
        periods.add(float(period))
    (period,) = periods
    for phase in ("import", "cold"):
        status = str(stage / phase / "status.json")
        native = json.loads(pin(status, proofs[status]).read_text())
        assert native["exit_status"] == 0 and native["stop_reason"] is None
        assert native["wall_seconds"] == placed["native_stages"][phase]["wall_seconds"]
    geometry = placed["geometry"]
    cores = compute["clusters"] * compute["arrays_per_cluster"]
    assert cores == geometry["regions"] == geometry["groups"]
    assert placed["connectivity"]["physical_leaf_instances"] == (
        geometry["fixed_memory_macros"] + geometry["standard_cells"]
    )
    installed_bytes = 0
    compiled_macros = 0
    for chip_memory in memory["by_master"].values():
        bits = chip_memory["words"] * chip_memory["bits_per_word"] * chip_memory["macros"]
        assert bits > 0 and bits % 8 == 0 and bits // 8 == chip_memory["bytes"]
        installed_bytes += bits // 8
        compiled_macros += chip_memory["macros"]
    assert compiled_macros == geometry["fixed_memory_macros"] == memory["macro_count"]
    assert installed_bytes == memory["installed_bytes"]
    targets = json.loads(pin("records/paper_result_targets.json").read_text())
    label = targets["silicon"]["sram_published_KB"]
    assert label == memory["published_label_kb"]

    facts.update(
        evidence_stage="corrected Booth placement imported and cold-reloaded in Innovus",
        candidate_cold_qualified=True,
        native_workers_terminal=True,
        candidate_sha256=candidate,
        cold_netlist_sha256=proofs[cold_name],
        die_width_mm=width,
        die_height_mm=height,
        clock_period_ns=period,
        clock_period_scope="Placed design constraint. Achievable frequency requires timing evidence.",
        clusters=compute["clusters"],
        cores=cores,
        array_instances=geometry["regions"],
        array_geometry=compute["processing_element_geometry"],
        operand_bits=compute["signed_operand_bits"],
        fixed_memory_macros=compiled_macros,
        local_token_mergers=sum(bank["local_token_mergers"] for bank in redundancy["clusters"]),
        local_head_predictors=sum(bank["local_head_predictors"] for bank in redundancy["clusters"]),
        local_strip_predictors=sum(bank["local_strip_predictors"] for bank in redundancy["clusters"]),
    )
    if round(installed_bytes / 1024) == label:
        return dict(compiled_macros=compiled_macros, compiled_bytes=installed_bytes,
                    paper_label_kb=label, reconciliation="rounded binary kilobytes")
    return None


def buffered_booth_timing_facts(root, facts, identities, stage, database_hash):
    """Attach verified timing from the same placement, including unfinished views."""
    from verify_tri_oracle_booth_placement_timing import verify

    if not (root / stage / "timing_three_views/prepared_timing.json").is_file():
        return
    result = verify(root, allow_incomplete=True)
    assert result["database_fingerprint_sha256"] == database_hash
    for name, checksum in result["evidence_sha256"].items():
        pin_booth(root, identities, name, checksum)
    corners = result["corners"]
    facts.update(
        placement_timing={
            "database_fingerprint_sha256": database_hash,
            "verified_views": sorted(corners),
            "pending_views": result["pending_views"],
            "failed_views": result["failed_views"],
        },
        high_fanout_substitution_disabled=corners.keys() == VIEWS,
        corner_slack_ns={view: corner["worst_slack_ns"] for view, corner in corners.items()},
        detailed_analysis_skipped_nets={
            view: corner["detailed_analysis_skipped_nets"] for view, corner in corners.items()
        },
    )


def buffered_booth_facts(root, facts, identities):
    """Bind the prior architecture inventory to the native buffer-only revision."""
    from tri_oracle_artifact_fingerprint import artifact_fingerprint

    prior = {}
    memory = corrected_booth_facts(root, prior, identities)
    placed = booth_record(root, identities, BOOTH_BUFFERED_PLACEMENT,
                          "corrected_buffer_repair_placement_and_cold_reload_verified")
    repair = booth_record(root, identities, BOOTH_BUFFER_REPAIR,
                          "corrected_booth_overload_repair_staged_and_reproduced")
    models = booth_record(root, identities, BOOTH_BUFFERED_MODELS,
                          "booth_buffered_candidate_models_and_memory_verified")
    database = Path(placed["database"])
    assert database.name == "placed.db" and database.parent.name == "import"
    stage = database.parents[1]
    fingerprint = artifact_fingerprint(root / database)
    encoded = json.dumps(fingerprint, sort_keys=True, separators=(",", ":")).encode()
    database_hash = hashlib.sha256(encoded).hexdigest()
    assert database_hash == placed["database_fingerprint_sha256"] == models["database_fingerprint_sha256"]

    proofs = placed["evidence_sha256"]
    candidate, seed, cold = (str(path) for path in (
        stage.parent / "buffered.v", stage.parent / "layout.def", stage / "cold/cold.v"))
    change = repair["check_after_insertion"]
    assert repair["baseline_netlist_sha256"] == prior["cold_netlist_sha256"]
    assert proofs[candidate] == models["linked_netlist_sha256"] == change["netlist_sha256"]
    assert proofs[seed] == models["seed_sha256"] == change["layout_sha256"]
    assert proofs[cold] == models["cold_netlist_sha256"]
    assert memory is not None
    assert models["memory_instances"] == memory["compiled_macros"] == prior["fixed_memory_macros"]
    assert models["memory_bytes"] == memory["compiled_bytes"]

    geometry = placed["geometry"]
    assert geometry["fixed_memory_macros"] == models["memory_instances"]
    leaves = geometry["standard_cells"] + geometry["fixed_memory_macros"]
    assert leaves == placed["connectivity"]["physical_leaf_instances"]
    assert leaves == repair["preserved_existing_placed_components"] + repair["added_buffers"]
    assert prior["cores"] == geometry["regions"] == geometry["groups"]
    layout = stage / "cold/layout.def"
    width, height = dimensions(pin_booth(root, identities, layout, proofs[str(layout)]))
    assert placed["die_dimensions_mm"] == [width, height] == [prior["die_width_mm"], prior["die_height_mm"]]
    assert set(placed["views"]) == VIEWS
    for phase in ("import", "cold"):
        receipt = stage / phase / "status.json"
        status = json.loads(pin_booth(root, identities, receipt, proofs[str(receipt)]).read_text())
        assert status["exit_status"] == 0 and status["stop_reason"] is None
        assert status["wall_seconds"] == placed["native_stages"][phase]["wall_seconds"]
        for corner in VIEWS:
            constraints = stage / phase / f"{corner}.sdc"
            text = pin_booth(root, identities, constraints, proofs[str(constraints)]).read_text()
            (period,) = re.findall(r"(?m)^create_clock .* -name core_clock -period ([\d.]+)\b", text)
            assert float(period) == prior["clock_period_ns"]

    if (root / BOOTH_STREAMING).is_file():
        streaming = booth_record(root, identities, BOOTH_STREAMING,
                                 "repaired_booth_trained_streaming_rows_verified_through_physical_ports")
        assert streaming["cold_netlist_sha256"] == proofs[cold]
        assert streaming["native"]["exit_status"] == 0 and streaming["native"]["stop_reason"] is None
        assert streaming["prediction"]["streaming"] is True
        assert streaming["external_value_requests"] == sum(row["selected_keys"] for row in streaming["output_rows"])
        prior["streaming_attention_replay"] = {
            key: streaming[key] for key in (
                "layer", "head", "token_merge_maps", "external_value_requests", "exact_output_values", "scope")
        }

    if (root / BOOTH_FEEDFORWARD).is_file():
        feedforward = booth_record(root, identities, BOOTH_FEEDFORWARD,
                                   "repaired_booth_trained_feedforward_replayed_through_physical_ports")
        assert feedforward["cold_netlist_sha256"] == proofs[cold]
        assert feedforward["native"]["exit_status"] == 0 and feedforward["native"]["stop_reason"] is None
        assert feedforward["positions"] == [607, 608]
        assert feedforward["physical_writeback_packets"] == 512 and feedforward["exact_writeback_values"] == 4096
        prior["feedforward_replay"] = {
            key: feedforward[key] for key in (
                "positions", "physical_writeback_packets", "exact_writeback_values", "cycles", "scope")
        }

    if (root / BOOTH_CLOCK_BOUNDARY).is_file():
        clock = booth_record(root, identities, BOOTH_CLOCK_BOUNDARY, "repaired_booth_external_clock_boundary_verified")
        assert clock["cold_netlist_sha256"] == proofs[cold]
        assert clock["database_fingerprint_sha256"] == database_hash
        assert clock["directly_clocked_arrays"] == prior["array_instances"]
        assert clock["paper_clock_generator_equivalence_verified"] is False
        prior["clock_boundary"] = {
            key: clock[key] for key in ("external_core_clock_port", "forwarded_pad_clock_port",
                                        "directly_clocked_arrays", "clock_constraints_by_view",
                                        "paper_clock_generator", "paper_clock_generator_equivalence_verified")
        }

    facts.update(prior, candidate_sha256=proofs[candidate], cold_netlist_sha256=proofs[cold],
                 evidence_stage="buffer-repaired Booth placement imported and cold-reloaded in Innovus",
                 original_full_models_verified=True, added_buffers=repair["added_buffers"],
                 pin_only_load_violations=change["pin_only_slow_corner_violations_after"])
    buffered_booth_timing_facts(root, facts, identities, stage, database_hash)
    return memory


def bounded_structure_facts(root, facts, identities):
    """Recheck the candidate's mapped evidence and any same-candidate native placement."""
    from collections import Counter
    from audit_tri_oracle_mapped_redundancy import audit
    from tri_oracle_process_guard import _processes
    from verify_tri_oracle_buffered_memory import placed_memory
    from verify_tri_oracle_buffered_topology import verify_compute_arrays
    from verify_tri_oracle_joined_placed_constraints import parse_sdc
    from verify_tri_oracle_pad_memory import compiler_sizes, memory_roles
    from verify_tri_oracle_repeater_placement_evidence import compiled_memory_inventory
    from verify_tri_oracle_shared_memory import check_native_census

    def pin(path, expected=None):
        absolute = root / path
        name = str(absolute.relative_to(root))
        if name not in identities:
            identities[name] = sha(absolute)
        assert expected is None or identities[name] == expected, absolute
        return absolute

    report = json.loads(pin(BOUNDED_MAPPED_STRUCTURE).read_text())
    assert report["state"] == "bounded_decoder_mapped_compute_and_compiler_memory_verified"
    assert report["paper_sha256"] == PAPER_SHA256
    published = report["evidence_sha256"]
    candidate = pin(BOUNDED_STAGE / "whole_chip.v", report["candidate_sha256"])
    seed = pin(BOUNDED_STAGE / "localized_seed/localized_seed.def", report["coordinate_seed_sha256"])
    targets_path = Path("records/paper_result_targets.json")
    targets = json.loads(pin(targets_path, published[str(targets_path)]).read_text())
    silicon = targets["silicon"]
    assert list(dimensions(seed)) == report["die_mm"] == silicon["die_dimensions_mm"]
    graph, macros = compiled_memory_inventory(candidate, seed)
    topology = audit(graph)
    assert topology["clusters"] == report["clusters"]
    arrays = verify_compute_arrays(candidate, graph, targets)
    assert arrays == report["compute"]

    files = {pin(Path(name), checksum) for name, checksum in published.items()
             if Path(name).parent.name in {"LEF", "NLDM", "VERILOG"}}
    sizes = compiler_sizes(files, set(macros.values()))
    memory = report["memory"]
    assert sizes == memory["bytes_per_macro_master"] and len(macros) == memory["compiled_macros"]
    roles = memory_roles(macros, sizes)
    assert json.dumps(roles, sort_keys=True) == json.dumps({key: memory[key] for key in roles}, sort_keys=True)
    total = sum(sizes[master] for master in macros.values())
    assert total == memory["compiled_bytes"]
    assert (total + 512) // 1024 == memory["rounded_binary_kb"] == silicon["sram_published_KB"]

    package_path = BOUNDED_STAGE / "native_placement/prepared.json"
    package = json.loads(pin(package_path, published[str(package_path)]).read_text())
    assert package["candidate_sha256"] == report["candidate_sha256"]
    definitions = {}
    for name, checksum in package["evidence_sha256"].items():
        path = Path(name)
        if path.suffix == ".sdc" and path.stem in VIEWS:
            text = pin(path, checksum).read_text().replace("-name core ", "-name core_clock ")
            parsed = parse_sdc(text.replace("[get_clocks {core}]", "[get_clocks {core_clock}]"))
            assert parsed[0]["current_design"] == "tri_oracle_chip_command_layer_parallel_chip"
            assert len(parsed[1]) == package["constraint_entries_by_view"][path.stem]
            definitions[path.stem] = parsed[0]["create_clock"]
    assert definitions.keys() == VIEWS and len({tuple(value) for value in definitions.values()}) == 1
    clock = float(definitions["setup_slow"][1])

    exact_output_values = None
    if (root / BOUNDED_RAW_REPLAY).is_file():
        raw = json.loads(pin(BOUNDED_RAW_REPLAY).read_text())
        assert raw["state"] == "widened_native_raw_replay_matches_reference"
        assert raw["candidate_sha256"] == report["candidate_sha256"] and raw["exit_status"] == 0
        for name, checksum in raw["evidence_sha256"].items():
            pin(Path(name), checksum)
        assert raw["functional_checkpoints"] == 90 and raw["compiled_memory_paths"] == len(macros)
        assert raw["exact_feedforward_values"] == raw["exact_writeback_values"] == 4096
        exact_output_values = raw["exact_feedforward_values"]

    facts.update(
        evidence_stage="bounded mapped netlist and coordinate seed",
        candidate_sha256=report["candidate_sha256"],
        die_width_mm=report["die_mm"][0],
        die_height_mm=report["die_mm"][1],
        clusters=len(topology["clusters"]),
        cores=sum(cluster["cores"] for cluster in topology["clusters"]),
        array_instances=arrays["array_instances"],
        array_geometry=[arrays["array_rows"], arrays["array_lanes"]],
        operand_bits=arrays["operand_bits"],
        clock_period_ns=clock,
        clock_period_scope="Constraint for the proposed placement. Achievable frequency is unmeasured.",
        mapped_compiled_memory_bytes=total,
        fixed_memory_macros_in_seed=len(macros),
        raw_replay_exact_output_values=exact_output_values,
    )

    if (root / BOUNDED_NATIVE_PLACEMENT).is_file():
        placement = json.loads(pin(BOUNDED_NATIVE_PLACEMENT).read_text())
        assert placement["state"] == "bounded_decoder_exact_seed_import_and_cold_reload_verified"
        assert placement["candidate_sha256"] == report["candidate_sha256"]
        assert placement["constraint_period_ns"] == clock
        paths = {Path(name): pin(Path(name), checksum)
                 for name, checksum in placement["evidence_sha256"].items()}
        stage = BOUNDED_STAGE / "native_placement"
        proof = json.loads(paths[stage / "verified.json"].read_text())
        assert proof["candidate_sha256"] == placement["candidate_sha256"]
        assert proof["state"] == "exact_seed_native_import_and_cold_reload_verified"
        assert proof["exact_connectivity"] == placement["exact_connectivity"]
        assert proof["exact_connectivity"]["physical_leaf_instances"] == package["components"]
        for step in ("import", "cold"):
            status = json.loads(paths[stage / step / "status.json"].read_text())
            assert status == proof["native"][step] and status["exit_status"] == 0 and status["stop_reason"] is None
            measured = placement["native"][step]
            assert list(dimensions(paths[stage / step / "layout.def"])) == measured["die_mm"] == report["die_mm"]
            assert measured["placed_components"] == package["components"] and measured["fixed_memories"] == len(macros)
            assert measured["timing_libraries_loaded"] == package["timing_libraries"]
            assert measured["extraction_models_loaded"] == package["extraction_models"]
            assert measured["constraint_entries_by_view"] == package["constraint_entries_by_view"]
            native_report = paths[stage / step / "placement.rpt"].read_text()
            assert re.findall(r"(?m)^\*info: Unplaced = (\d+)\s*$", native_report) == ["0"]
        prefix = os.fsencode(root / stage) + b"/"
        workers = [pid for pid, (_, _, arguments) in _processes().items()
                   if any(arg == b"-log" and arguments[i + 1].startswith(prefix)
                          for i, arg in enumerate(arguments[:-1]))]
        facts.update(
            evidence_stage="bounded decoder native Innovus placement and cold reload",
            candidate_cold_qualified=True,
            original_full_models_verified=True,
            native_workers_terminal=not workers,
            active_candidate_native_workers=sorted(workers),
            unplaced_instances=0,
            placement_density_percent=placement["native"]["cold"]["placement_density_percent"],
            clock_period_scope="Placed design constraint. Achievable frequency requires timing evidence.",
        )
        if exact_output_values is not None and (root / BOUNDED_INDEXED_REPLAY).is_file():
            for step in ("import", "cold"):
                with paths[stage / step / "layout.def"].open() as stream:
                    assert placed_memory(stream) == macros
            assert Counter(macros.values()) == memory["compiled_macro_count_by_master"]
            assert total == sum(roles[key] for key in ("core_memory_bytes", "aggregator_io_bytes", "support_memory_bytes"))
            indexed = json.loads(pin(BOUNDED_INDEXED_REPLAY).read_text())
            assert indexed["state"] == "native_indexed_trained_feedforward_and_writeback_verified"
            assert indexed["candidate_sha256"] == report["candidate_sha256"]
            assert indexed["native"]["exit_status"] == 0 and indexed["compiled_memory_paths"] == len(macros)
            models = {path for path in files if path.parent.name == "VERILOG"}
            for mode, replay in (("raw", raw), ("indexed", indexed)):
                folder = BOUNDED_STAGE / "native_replay" / mode
                manifest_path = folder / "inputs.json"
                manifest = json.loads(pin(manifest_path, replay["evidence_sha256"][str(manifest_path)]).read_text())
                assert manifest["candidate_sha256"] == report["candidate_sha256"] == manifest["inputs"][str(candidate)]
                replay_models = {Path(name) for name in manifest["inputs"] if Path(name).parent.name == "VERILOG"}
                assert replay_models == models
                for model in models:
                    pin(model, manifest["inputs"][str(model)])
                transcript = folder / "xrun.log"
                with pin(transcript, replay["evidence_sha256"][str(transcript)]).open() as stream:
                    check_native_census(stream, "tri_oracle_batched406_learned_tb.dut.", macros)
            label = silicon["sram_published_KB"]
            assert (total + 500) // 1000 != label
            return dict(candidate_sha256=report["candidate_sha256"], macros=len(macros), bytes=total,
                        label=label, binary_kibibytes=total / 1024, bytes_over_binary_label=total - label * 1024,
                        exact_paper_capacity_in_bytes_published=False, **roles)
    return None


def bounded_reset_facts(root, facts, identities, baseline_memory):
    """Bind the physical checks to the repaired design and its cold export."""
    from tri_oracle_process_guard import _processes
    from verify_tri_oracle_buffered_memory import placed_memory
    from verify_tri_oracle_joined_placed_constraints import parse_sdc
    from verify_tri_oracle_repeater_placement_evidence import compiled_memory_inventory

    def pin(path, expected=None):
        absolute = root / path
        name = str(absolute.relative_to(root))
        if name not in identities:
            identities[name] = sha(absolute)
        assert expected is None or identities[name] == expected, absolute
        return absolute

    stage = BOUNDED_STAGE / "native_reset_eco_relinked_native"
    baseline_stage = BOUNDED_STAGE / "native_placement"
    replay_stage = BOUNDED_STAGE / "native_reset_eco_relinked_replays"
    placed = json.loads(pin(BOUNDED_RESET_PLACEMENT).read_text())
    assert placed["state"] == "reset_repaired_whole_chip_native_import_cold_reload_and_geometry_verified"
    assert placed["original_candidate_sha256"] == facts["candidate_sha256"] == baseline_memory["candidate_sha256"]
    published = placed["evidence_sha256"]
    native = json.loads(pin(stage / "native_receipt.json", published[str(stage / "native_receipt.json")]).read_text())
    audit = json.loads(pin(stage / "verified.json", published[str(stage / "verified.json")]).read_text())
    assert native["state"] == "reset_relinked_native_placement_and_cold_reload_passed"
    assert audit["state"] == "relinked_reset_native_coordinates_and_connectivity_verified"
    assert audit["native_receipt_sha256"] == placed["native_receipt_sha256"] == identities[str(stage / "native_receipt.json")]
    for key in ("original_candidate_sha256", "reset_repaired_netlist_sha256", "exported_cold_netlist_sha256"):
        assert placed[key] == audit[key] == native[key], key
    assert native["components"] == placed["checked_component_count"] == audit["exact_connectivity"]["physical_leaf_instances"]
    assert native["components"] == 3865789 + placed["added_reset_buffers"] == 3867343
    assert placed["exact_connectivity"] == audit["exact_connectivity"]
    paths = {Path(name): pin(Path(name), checksum) for name, checksum in native["evidence_sha256"].items()}
    cold_netlist = paths[stage / "cold/cold.v"]
    assert identities[str(stage / "cold/cold.v")] == placed["exported_cold_netlist_sha256"]

    def constraint_set(path):
        text = path.read_text().replace("-name core ", "-name core_clock ")
        return parse_sdc(text.replace("[get_clocks {core}]", "[get_clocks {core_clock}]"))

    def loaded_models(log):
        text = log.read_text()
        libraries = re.findall(r"(?m)^Reading ls_(slow|typ|fast) timing library (.+\.lib)\.$", text)
        extraction = re.findall(r"(?m)^    RC-Corner Technology file: '([^']+)'\s*$", text)
        assert len(libraries) == 21 and len(extraction) == 3
        for _, name in libraries:
            pin(Path(name))
        for name in extraction:
            pin(Path(name))
        return ({(corner, Path(name).name, identities[str(Path(name).relative_to(root))])
                 for corner, name in libraries},
                {(Path(name).name, identities[str(Path(name).relative_to(root))]) for name in extraction})

    for step in ("import", "cold"):
        folder = stage / step
        status = json.loads(paths[folder / "status.json"].read_text())
        assert status == placed["native_status"][f"{step}_stage"] == native["native_status"][f"{step}_stage"]
        assert status["exit_status"] == 0 and status["stop_reason"] is None
        assert list(dimensions(paths[folder / "layout.def"])) == placed["die_dimensions_mm"] == [3.6, 3.6]
        report = paths[folder / "placement.rpt"].read_text()
        assert re.findall(r"(?m)^\*info: Unplaced = (\d+)\s*$", report) == ["0"]
        assert re.findall(r"(?m)^Placement Density:([\d.]+)%", report) == [str(placed["place_density_percent"])]
        assert loaded_models(paths[folder / "console.log"]) == loaded_models(pin(baseline_stage / step / "console.log"))
        for view in VIEWS:
            before = constraint_set(pin(baseline_stage / "cold" / f"{view}.sdc"))
            after = constraint_set(paths[folder / f"{view}.sdc"])
            assert before == after
            assert float(after[0]["create_clock"][1]) == placed["clocks_target_period_ns"]

    with pin(baseline_stage / "cold/layout.def").open() as stream:
        baseline_macros = placed_memory(stream)
    _, macros = compiled_memory_inventory(cold_netlist, paths[stage / "cold/layout.def"])
    assert macros == baseline_macros
    assert len(macros) == native["memories"] == placed["fixed_macros"] == baseline_memory["macros"]
    prefixes = tuple(os.fsencode(root / directory) + b"/" for directory in (stage, replay_stage))
    workers = [pid for pid, (_, _, args) in _processes().items()
               if any(arg == b"-log" and args[i+1].startswith(prefixes) for i, arg in enumerate(args[:-1]))]
    baseline_replay = facts.pop("raw_replay_exact_output_values", None)
    facts.update(
        evidence_stage="native Innovus reset repair with independently verified cold reload",
        candidate_sha256=placed["reset_repaired_netlist_sha256"],
        exported_cold_netlist_sha256=placed["exported_cold_netlist_sha256"],
        baseline_raw_replay_exact_output_values=baseline_replay,
        clock_period_ns=placed["clocks_target_period_ns"],
        candidate_cold_qualified=True,
        original_full_models_verified=True,
        native_workers_terminal=not workers,
        active_candidate_native_workers=sorted(workers),
        placement_density_percent=placed["place_density_percent"],
    )
    return dict(baseline_memory, candidate_sha256=facts["candidate_sha256"],
                exported_cold_netlist_sha256=facts["exported_cold_netlist_sha256"])


def bounded_buffered_facts(root, facts, identities, predecessor_memory, *, token_map=False):
    """Check a placed buffering change against its verified predecessor."""
    from tri_oracle_process_guard import _processes
    from verify_tri_oracle_buffered_memory import placed_memory
    from verify_tri_oracle_buffered_timing_inputs import canonical_sdc
    from verify_tri_oracle_repeater_placement_evidence import compiled_memory_inventory

    def pin(path, expected=None):
        absolute = root / path
        name = str(absolute.relative_to(root))
        if name not in identities:
            identities[name] = sha(absolute)
        assert expected is None or identities[name] == expected, absolute
        return absolute

    if token_map:
        stage = BOUNDED_STAGE / "native_token_map_buffer_candidate"
        predecessor = BOUNDED_STAGE / "native_probability_buffer_candidate"
        record, seed_path = BOUNDED_TOKEN_MAP_PLACEMENT, stage / "prepared.json"
        placed_state = "token_map_buffered_whole_chip_native_placement_verified"
        native_state = "token_map_native_import_cold_coordinates_and_connectivity_verified"
        native_source_key, seed_source_key = "source_cold_sha256", "original_cold_sha256"
        predecessor_components_key, buffer_field = "original_components", "added_token_map_buffers"
        predecessor_components, new_buffers = 3868623, 35
    else:
        stage = BOUNDED_STAGE / "native_probability_buffer_candidate"
        predecessor = BOUNDED_STAGE / "native_reset_eco_relinked_native"
        record, seed_path = BOUNDED_PROBABILITY_PLACEMENT, BOUNDED_PROBABILITY_SEED
        placed_state = "probability_buffered_whole_chip_native_placement_verified"
        native_state = "probability_buffer_native_import_cold_coordinates_and_connectivity_verified"
        native_source_key = seed_source_key = "source_cold_netlist_sha256"
        predecessor_components_key, buffer_field = "old_components_unchanged", "added_probability_buffers"
        predecessor_components, new_buffers = 3867343, 1280
    placed = json.loads(pin(record).read_text())
    assert placed["state"] == placed_state
    for name, checksum in placed["evidence_sha256"].items():
        pin(Path(name), checksum)
    seed = json.loads(pin(seed_path, placed["evidence_sha256"][str(seed_path)]).read_text())
    receipt = stage / "native_receipt.json"
    native = json.loads(pin(receipt, placed["evidence_sha256"][str(receipt)]).read_text())
    assert native["state"] == native_state
    assert native[native_source_key] == seed[seed_source_key] == facts["exported_cold_netlist_sha256"]
    assert native["seed_netlist_sha256"] == seed["buffered_netlist_sha256"] == placed["seed_netlist_sha256"]
    assert native["cold_netlist_sha256"] == placed["cold_netlist_sha256"]
    assert native["inserted_buffers"] == seed["inserted_buffers"] == new_buffers
    assert seed[predecessor_components_key] == predecessor_components
    assert native["components"] == seed["physical_components"] == predecessor_components + new_buffers
    assert native["exact_connectivity"]["physical_leaf_instances"] == native["components"]
    paths = {Path(name): pin(Path(name), checksum) for name, checksum in native["evidence_sha256"].items()}
    cold = stage / "cold"
    assert identities[str(cold / "cold.v")] == native["cold_netlist_sha256"]
    for step in ("import", "cold"):
        folder = stage / step
        status = json.loads(paths[folder / "status.json"].read_text())
        assert status == native["native_status"][step] and status["exit_status"] == 0 and status["stop_reason"] is None
        assert dimensions(paths[folder / "layout.def"]) == (3.6, 3.6)
        report = paths[folder / "placement.rpt"].read_text()
        assert re.findall(r"(?m)^\*info: Unplaced = (\d+)\s*$", report) == ["0"]
        assert re.findall(r"(?m)^Placement Density:([\d.]+)%", report) == [str(native["density_percent"])]
        for view in VIEWS:
            before = canonical_sdc(pin(predecessor / "cold" / f"{view}.sdc"))
            after = canonical_sdc(paths[folder / f"{view}.sdc"])
            assert before == after and float(after[0]["create_clock"][1]) == facts["clock_period_ns"]
    with pin(predecessor / "cold/layout.def").open() as stream:
        predecessor_macros = placed_memory(stream)
    _, macros = compiled_memory_inventory(paths[cold / "cold.v"], paths[cold / "layout.def"])
    assert macros == predecessor_macros and len(macros) == predecessor_memory["macros"] == native["fixed_memories"] == 631
    prefix = os.fsencode(root / stage) + b"/"
    executables = {b"innovus", b"xrun", b"xmelab", b"xmsim"}
    workers = [pid for pid, (_, _, args) in _processes().items()
               if args and os.path.basename(args[0]) in executables
               and any(arg.startswith(prefix) for arg in args[1:])]
    kind = "token-map-buffered" if token_map else "probability-buffered"
    facts.update(
        evidence_stage=f"native Innovus {kind} placement with independently verified cold reload",
        candidate_sha256=seed["buffered_netlist_sha256"],
        exported_cold_netlist_sha256=native["cold_netlist_sha256"],
        native_workers_terminal=not workers,
        active_candidate_native_workers=sorted(workers),
        placement_density_percent=native["density_percent"],
    )
    facts[buffer_field] = native["inserted_buffers"]
    return dict(predecessor_memory, candidate_sha256=facts["candidate_sha256"],
                exported_cold_netlist_sha256=facts["exported_cold_netlist_sha256"])


def bounded_resized_facts(root, facts, identities, predecessor_memory):
    """Bind the current cold placement, mapped resources and scoped replay."""
    from audit_tri_oracle_mapped_redundancy import PE_ARRAY, TOP
    from tri_oracle_process_guard import _processes
    from verify_tri_oracle_buffered_memory import placed_memory
    from verify_tri_oracle_buffered_timing_inputs import canonical_sdc
    from verify_tri_oracle_buffered_topology import verify_compute_arrays
    from verify_tri_oracle_repeater_placement_evidence import compiled_memory_inventory

    def pin(path, expected=None):
        name = str(path)
        if name not in identities:
            identities[name] = sha(root / path)
        assert expected is None or identities[name] == expected, path
        return root / path

    def read_evidence(path, expected=None):
        evidence = json.loads(pin(path, expected).read_text())
        for name, checksum in evidence["evidence_sha256"].items():
            pin(Path(name), checksum)
        return evidence

    previous = BOUNDED_STAGE / "native_token_map_buffer_candidate"
    stage = previous / "value_register_drive_check/native_proxy_relinked"
    placed = read_evidence(BOUNDED_RESIZED_PLACEMENT)
    assert placed["state"] == "full_chip_linked_placement_cold_verified_after_value_register_resize"
    assert placed["source_cold_netlist_sha256"] == facts["exported_cold_netlist_sha256"]
    witness_path = stage / "native_receipt.json"
    witness = read_evidence(witness_path, placed["evidence_sha256"][str(witness_path)])
    assert witness["state"] == "whole_chip_resize_proxy_relinked_native_placement_verified"
    netlist_path = stage / "cold/cold.v"
    cold_hash = witness["reloaded_cold_sha256"]
    netlist = pin(netlist_path, witness["evidence_sha256"][str(netlist_path)])
    assert cold_hash == placed["cold_netlist_sha256"] == identities[str(netlist_path)]
    count = placed["placed_instances"]
    assert witness["components"] == witness["native_connectivity"]["physical_leaf_instances"] == count == 3868658
    assert placed["coordinate_inventory_sha256"] == witness["matched_native_coordinates_sha256"]
    for step, key in (("import", "linked_import"), ("cold", "cold_reload")):
        folder = stage / step
        status = json.loads(pin(folder / "status.json").read_text())
        assert status == placed["runtime"][key] and status["exit_status"] == 0 and status["stop_reason"] is None
        assert dimensions(pin(folder / "layout.def")) == (3.6, 3.6)
        report = pin(folder / "placement.rpt").read_text()
        assert re.findall(r"(?m)^\*info: Placed = (\d+)\s+\(Fixed = (\d+)\)\s*$", report) == [(str(count), "631")]
        assert re.findall(r"(?m)^\*info: Unplaced = (\d+)\s*$", report) == ["0"]
        assert not re.search(r"(?i)overlap|orientation violation|out of core area", report)
        assert re.findall(r"(?m)^Placement Density:([\d.]+)%", report) == [str(witness["density_percent"])]
        for view in VIEWS:
            before = canonical_sdc(pin(previous / "cold" / f"{view}.sdc"))
            after = canonical_sdc(pin(folder / f"{view}.sdc"))
            assert before == after and float(after[0]["create_clock"][1]) == facts["clock_period_ns"]

    for directory, suffixes in (("lef", {".lef", ".tlef"}), ("mmmc", {".lib"})):
        original = previous / "import/placed.db/libs" / directory
        replacement = stage / "import/placed.db/libs" / directory
        names = {path.name for path in (root / original).iterdir() if path.suffix in suffixes}
        assert names and names == {path.name for path in (root / replacement).iterdir() if path.suffix in suffixes}
        for name in sorted(names):
            pin(original / name)
            pin(replacement / name, identities[str(original / name)])

    graph, macros = compiled_memory_inventory(netlist, pin(stage / "cold/layout.def"))
    with pin(previous / "cold/layout.def").open() as stream:
        assert placed_memory(stream) == macros
    assert len(macros) == predecessor_memory["macros"] == witness["movement"]["fixed_memories"] == 631
    # Innovus renames some intermediate masters on export. Check the reachable
    # array instance paths against the independently checked cluster hierarchy.
    def array_paths(master, path):
        if master.startswith(PE_ARRAY):
            yield path
            return
        for child, child_master in graph[master].items():
            instance = child.removeprefix("\\")
            yield from array_paths(child_master, f"{path}.{instance}")

    clusters = json.loads(pin(BOUNDED_MAPPED_STRUCTURE).read_text())["clusters"]
    expected = {f"{cluster['instance']}.cores[{core}].compute.compute"
                for cluster in clusters for core in range(cluster["cores"])}
    paths = list(array_paths(TOP, TOP))
    assert len(paths) == len(expected) and set(paths) == expected
    targets = json.loads(pin(Path("records/paper_result_targets.json")).read_text())
    arrays = verify_compute_arrays(netlist, graph, targets)

    replay = read_evidence(Path("records/tri_oracle_resized_chip_native_attention.json"))
    assert replay["state"] == "value_register_resize_native_attention_replay_verified"
    assert replay["cold_netlist_sha256"] == cold_hash and replay["native"]["exit_status"] == 0
    assert (replay["matched_attention_rows"], replay["matched_attention_accumulator_words"],
            replay["matched_grouped_cluster_outputs"]) == (10, 640, 704)

    prefix = os.fsencode(root / stage) + b"/"
    workers = sorted(pid for pid, (_, _, args) in _processes().items()
                     if args and os.path.basename(args[0]) in {b"innovus", b"xrun", b"xmelab", b"xmsim", b"genus"}
                     and any(arg.startswith(prefix) for arg in args[1:]))
    prepared = json.loads(pin(stage / "prepared.json").read_text())
    mapped_path = previous / "value_register_drive_check/native_local_legalization/resized.v"
    candidate = prepared["evidence_sha256"][str(mapped_path)]
    pin(mapped_path, candidate)
    facts.update(candidate_sha256=candidate, exported_cold_netlist_sha256=cold_hash,
                 evidence_stage="native Innovus value-register resize placement with verified cold reload",
                 clusters=len(clusters), cores=sum(cluster["cores"] for cluster in clusters),
                 array_instances=arrays["array_instances"], array_geometry=[arrays["array_rows"], arrays["array_lanes"]],
                 operand_bits=arrays["operand_bits"], placement_density_percent=witness["density_percent"],
                 matched_scoped_attention_rows=replay["matched_attention_rows"],
                 active_candidate_native_workers=workers, native_workers_terminal=not workers)
    return dict(predecessor_memory, candidate_sha256=candidate, exported_cold_netlist_sha256=cold_hash)


def reduced_port_placement_facts(root, facts, identities, *, repaired=False):
    from tri_oracle_artifact_fingerprint import artifact_fingerprint
    from tri_oracle_process_guard import _processes
    from verify_tri_oracle_current_mapped_architecture import verify
    from verify_tri_oracle_joined_placed_constraints import parse_sdc

    def pin(name, expected=None):
        path = root / name
        key = str(path)
        if key not in identities:
            identities[key] = sha(path)
        if expected is not None and identities[key] != expected:
            raise ValueError(f"Changed evidence: {path}")
        return path

    def constraints(name):
        text = pin(name).read_text().replace("-name core ", "-name core_clock ")
        return parse_sdc(text.replace("[get_clocks {core}]", "[get_clocks {core_clock}]"))

    record = json.loads(pin(REDUCED_PORT_PLACEMENT).read_bytes())
    assert record["state"] == "reduced_port_whole_chip_placement_and_reload_independently_verified"
    for name, expected in record["evidence_sha256"].items():
        pin(name, expected)
    stage = REDUCED_PORT_STAGE
    receipt = json.loads(pin(stage / "cold/cold_receipt.json").read_bytes())
    assert receipt["state"] == "current_chip_placement_and_cold_reload_verified"
    coords = json.loads(pin(stage / "cold/independent_coordinates.json",
                            receipt["coordinate_verification_sha256"]).read_bytes())
    simulation = json.loads(pin(stage / "whole_chip/verified.json",
                                receipt["prerequisite_xcelium_replay_sha256"]).read_bytes())
    candidate = record["candidate_sha256"]
    pin(stage / "candidate.v", candidate)
    assert coords["candidate_sha256"] == simulation["candidate_sha256"] == candidate
    assert artifact_fingerprint(root / stage / "native/placed.db") == receipt["database_fingerprint"]
    arch = verify()
    archived_arch = json.loads(pin("records/tri_oracle_current_mapped_architecture.json").read_bytes())
    # The architecture verifier uses dimensions() from this module. Keep its
    # archived digest intact and compare the other evidence and all observations.
    this_module = str(Path(__file__).resolve().relative_to(root))
    current_sources = arch.pop("evidence_sha256")
    archived_sources = archived_arch.pop("evidence_sha256")
    assert current_sources.pop(this_module) == sha(root / this_module)
    archived_sources.pop(this_module)
    assert current_sources == archived_sources and json.loads(json.dumps(arch)) == archived_arch
    assert arch["candidate_sha256"] == candidate

    placed_layout = pin(stage / "cold/cold.def")
    width, height = dimensions(placed_layout)
    assert [width, height] == record["native_die_mm"]
    counts = {}
    clocks = set()
    for view in sorted(VIEWS):
        parsed = constraints(stage / f"cold/{view}.sdc")
        definitions, ports, _ = parsed
        assert definitions["current_design"] == "tri_oracle_chip_command_layer_parallel_chip"
        if repaired:
            actual = constraints(stage / f"token_tree_native_full_reloads/structure/{view}.sdc")
            assert actual == parsed, f"Repaired placement changed constraints in {view}"
        clocks.add(definitions["create_clock"][1])
        counts[view] = len(ports)
    assert counts == coords["constraint_entries_by_view"] and len(clocks) == 1
    unplaced, = re.findall(r"(?m)^\*info: Unplaced = (\d+)\s*$",
                           pin(stage / "cold/placement.rpt").read_text())
    assert int(unplaced) == 0
    memory = arch["compiled_memory"]
    assert memory["compiled_macros"] == coords["fixed_memories"] == simulation["compiled_memory_paths"]
    assert memory["compiled_bytes"] == record["compiled_memory_bytes"]
    assert (2 * memory["compiled_bytes"] + 1024) // 2048 == memory["paper_label_kb"] == 405
    prefix = os.fsencode(root / stage) + b"/"
    workers = any(argument == b"-log" and arguments[index + 1].startswith(prefix)
                  for _, _, arguments in _processes().values()
                  for index, argument in enumerate(arguments[:-1]))
    clusters, arrays = arch["clusters"], arch["compute"]
    facts.update(
        candidate_sha256=candidate, evidence_stage="cold Innovus reduced-port placement",
        candidate_cold_qualified=True, original_full_models_verified=True,
        native_workers_terminal=not workers,
        die_width_mm=width, die_height_mm=height, clock_period_ns=float(clocks.pop()),
        clusters=len(clusters), cores=sum(cluster["cores"] for cluster in clusters),
        array_instances=arrays["array_instances"], array_geometry=[arrays["array_rows"], arrays["array_lanes"]],
        operand_bits=arrays["operand_bits"], fixed_memory_macros=memory["compiled_macros"],
        unplaced_instances=int(unplaced), constraint_entries_by_view=counts,
    )
    if repaired:
        return repaired_placement_facts(root, facts, pin, memory)
    return memory


def repaired_placement_facts(root, facts, pin, baseline_memory):
    from tri_oracle_artifact_fingerprint import artifact_fingerprint

    report = json.loads(pin(TOKEN_TREE_PLACEMENT).read_bytes())
    stage = REDUCED_PORT_STAGE
    reloads = stage / "token_tree_native_full_reloads"
    for name, expected in report["evidence_sha256"].items():
        pin(name, expected)
    native = json.loads(pin(reloads / "receipt.json").read_bytes())
    assert {
        name: value for name, value in report.items()
        if name not in {"checkpoint_fingerprint_sha256", "evidence_sha256"}
    } == {
        name: value for name, value in native.items()
        if name not in {"placement_fingerprint", "evidence_sha256"}
    }
    assert native["state"] == "native_token_count_tree_placed_cold_connected_and_pin_loads_verified"
    assert native["baseline_candidate_sha256"] == facts["candidate_sha256"]
    assert all(item["exit_status"] == 0 and item["stop_reason"] is None for item in native["native"].values())
    checkpoint = root / stage / "token_tree_native_full_split_flow/apply/placed.db"
    fingerprint = artifact_fingerprint(checkpoint)
    assert fingerprint == native["placement_fingerprint"]
    assert hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode()).hexdigest() == report["checkpoint_fingerprint_sha256"]
    repaired_netlist = native["repaired_netlist_sha256"]
    pin(reloads / "legality/cold.v", repaired_netlist)
    assert dimensions(pin(reloads / "legality/cold.def")) == (facts["die_width_mm"], facts["die_height_mm"])
    assert native["constraint_entries_by_view"] == facts["constraint_entries_by_view"]
    assert native["fixed_memory_macros"] == facts["fixed_memory_macros"]
    assert native["unplaced_instances"] == facts["unplaced_instances"] == 0
    assert native["native_branch_pin_checks"] == 3 * (native["added_buffers"] + 10)
    assert 0 < native["worst_native_branch_pin_load_ratio"] < 1
    resources = json.loads(pin(REPAIRED_NATIVE_RESOURCES).read_bytes())
    for name, expected in resources["evidence_sha256"].items():
        pin(name, expected)
    assert resources["state"] == "exact_repaired_native_compute_and_memory_inventory_verified"
    assert resources["repaired_netlist_sha256"] == repaired_netlist
    assert resources["baseline_candidate_sha256"] == native["baseline_candidate_sha256"]
    assert resources["checkpoint_fingerprint_sha256"] == report["checkpoint_fingerprint_sha256"]
    assert resources["verified_loaded_compiler_timing_views_per_reload"] == 18
    assert resources["verified_loaded_compiler_physical_abstracts_per_reload"] == 6
    memory = resources["compiled_memory"]
    assert memory == json.loads(json.dumps(baseline_memory))
    assert memory["compiled_macros"] == native["fixed_memory_macros"]
    arrays = resources["compute"]
    assert arrays["array_instances"] == facts["array_instances"]
    assert [arrays["array_rows"], arrays["array_lanes"]] == facts["array_geometry"]
    assert arrays["operand_bits"] == facts["operand_bits"]
    assert len(resources["clusters"]) == facts["clusters"]
    assert sum(cluster["cores"] for cluster in resources["clusters"]) == facts["cores"]
    facts.update(
        candidate_sha256=repaired_netlist,
        baseline_candidate_sha256=native["baseline_candidate_sha256"],
        evidence_stage="cold Innovus repaired token-count placement",
        memory_accounting_candidate_sha256=resources["repaired_netlist_sha256"],
        endpoint_count=native["endpoint_count"],
        added_buffers=native["added_buffers"],
        worst_native_branch_pin_load_ratio=native["worst_native_branch_pin_load_ratio"],
    )
    return memory


def registered_memory(root, identities):
    from collections import Counter, defaultdict
    from tri_oracle_artifact_fingerprint import artifact_fingerprint
    from verify_tri_oracle_shared_memory import CORNERS, check_native_census, memory_shape

    work = root / REGISTERED_WRITE
    placement = work / "placement"
    replay = work / "whole_chip_replay"

    def load(path, expected=None):
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if expected is not None and digest != expected:
            raise ValueError(f"Changed evidence: {path}")
        assert identities.setdefault(str(path), digest) == digest, path
        return json.loads(raw)

    summary = load(root / "records/tri_oracle_registered_write_timing_and_memory_result.json")
    record = load(root / "records/tri_oracle_registered_write_placement_result.json")
    native = load(placement / "receipt.json", record["local_evidence_sha256"]["placed_database_and_cold_reload"])
    memory = load(work / "paper_memory_review/placed_memory_receipt.json",
                  summary["local_evidence_sha256"]["compiled_memory_by_role"])
    assert native["state"] == "registered_write_placement_and_cold_reload_verified"
    assert memory["state"] == "candidate_memory_matches_labeled_roles_and_rounded_binary_total"
    candidate, placed = summary["mapped_candidate_sha256"], summary["placed_netlist_sha256"]
    assert candidate == native["candidate_sha256"] == memory["candidate_sha256"] == record["mapped_candidate_sha256"]
    assert placed == native["exported_netlist_sha256"] == memory["placed_netlist_sha256"] == record["placed_netlist_sha256"]
    proof_path = placement / "independent_memory_receipt.json"
    proof = load(proof_path, memory["input_sha256"][str(proof_path.relative_to(root))])
    assert proof["state"] == "corrected_registered_chip_placed_memory_independently_verified"
    assert proof["candidate_sha256"] == candidate and proof["exported_netlist_sha256"] == placed
    checkpoint = placement / "place/placed.db"
    assert artifact_fingerprint(checkpoint) == native["placed_database"] == proof["placed_database"]

    native_inputs = native["input_sha256"]
    memory_inputs = memory["input_sha256"]
    for group in (native_inputs, memory_inputs, proof["input_sha256"]):
        for name, expected in group.items():
            path = root / name
            if str(path) not in identities:
                identities[str(path)] = sha(path)
            assert identities[str(path)] == expected, path
    assert identities[str(work / "capture_graft/chip.v")] == candidate
    assert identities[str(placement / "place/placed.v")] == placed

    cold_path = placement / "cold/native_status.json"
    cold = load(cold_path, identities[str(cold_path)])
    assert cold == native["native"]["cold"]
    assert cold["native_exit_status"] == 0 and cold["stop_reason"] is None
    console = (placement / "cold/console.log").read_text()
    assert console.splitlines().count("TRI_ORACLE_JOINED_PLACEMENT_COLD_PASS") == 1
    poses = (placement / "cold/placed_macros.tsv").read_text().splitlines()
    inventory = {}
    for line in poses:
        name, master, _, _, _ = line.split("\t")
        assert name not in inventory, name
        inventory[name] = master
    counts = Counter(inventory.values())
    assert counts == memory["counts_by_macro"] == proof["counts_by_master"]
    assert len(inventory) == native["macros"] == memory["memory_instances"] == proof["memory_instances"] == 631
    compiler_models = {root / name for name in memory_inputs if Path(name).parent.name == "VERILOG"}
    modes = (("attention", "tri_oracle_attention430_tb"), ("trained", "tri_oracle_batched406_learned_tb"))
    for mode, top in modes:
        result_path = replay / f"{mode}_receipt.json"
        result = load(result_path, identities[str(result_path)])
        assert result["state"] == f"registered_write_whole_chip_{mode}_verified"
        assert result["chip_sha256"] == candidate and result["native"]["native_exit_status"] == 0
        assert result["compiled_memories"] == len(inventory)
        bundle_path = replay / f"{mode}_bundle.sv"
        bundle = bundle_path.read_text()
        includes = set(re.findall(r'(?m)^`include "([^"]+)"$', bundle))
        assert str(work / "capture_graft/chip.v") in includes
        assert compiler_models == {Path(name) for name in includes if Path(name).parent.name == "VERILOG"}
        for path in (*compiler_models, bundle_path):
            name = str(path.relative_to(root))
            assert result["input_sha256"][name] == memory_inputs[name], path
        log_path = replay / mode / "xrun.log"
        assert result["native"]["log_sha256"] == identities[str(log_path)]
        with log_path.open() as stream:
            check_native_census(stream, top + ".dut.", inventory)

    sizes = {}
    for model in sorted(compiler_models):
        compiler = model.parent.parent
        master = compiler.name.removesuffix("_130a").upper()
        assert master in counts and master not in sizes
        abstract = compiler / "LEF" / f"{compiler.name}.lef"
        name = str(abstract.relative_to(root))
        assert native_inputs[name] == memory_inputs[name]
        assert re.findall(r"(?m)^\s*MACRO\s+(\w+)\s*$", abstract.read_text()) == [master]
        model_text = model.read_text()
        shapes = set()
        for corner in CORNERS:
            library = compiler / "NLDM" / f"{compiler.name}_{corner}.lib"
            name = str(library.relative_to(root))
            assert native_inputs[name] == memory_inputs[name]
            shapes.add(memory_shape(model_text, library.read_text(), master))
        (depth, width), = shapes
        sizes[master] = depth * width // 8
    assert sizes.keys() == counts.keys() and sizes == memory["bytes_by_macro"]
    total = sum(sizes[master] * count for master, count in counts.items())
    roles = memory["bytes_by_role"]
    labels = memory["figure_31_6_2_labeled_bytes"]
    cluster = re.compile(
        r"layer\.layer\.feedforward\.compute\.compute\.tensor\.fabric\.clusters\[([0-4])\]"
        r"\.unit\.selected_bank\1\.block_instance\.source_cluster\.implementation\.")
    core = re.compile(r"cores\[([0-3])\]\.compute\.(inputs|weights|outputs|masks)\[\d+\]")
    role_names = {"inputs": "input", "weights": "weight", "outputs": "output", "masks": "skip_mask"}
    core_bytes = {"input": 8 * 1024, "weight": 8 * 1024, "output": 2 * 1024, "skip_mask": 1024}
    cores = defaultdict(Counter)
    aggregators = Counter()
    for path, master in inventory.items():
        owner = cluster.match(path)
        if owner:
            member = path[owner.end():]
            if unit := core.fullmatch(member):
                cores[owner[1], unit[1]][role_names[unit[2]]] += sizes[master]
            elif re.fullmatch(r"aggregate_memory\[\d+\]", member):
                aggregators[owner[1]] += sizes[master]
    assert set(cores) == {(str(c), str(i)) for c in range(5) for i in range(4)}
    assert all(amount == core_bytes for amount in cores.values())
    assert aggregators == {str(c): 2 * 1024 for c in range(5)}
    assert labels == {role: size * len(cores) for role, size in core_bytes.items()} | {
        "aggregator_input_output": sum(aggregators.values())}
    assert all(roles[role] == size for role, size in labels.items())
    assert sum(roles.values()) == total == proof["compiled_bytes"] == memory["compiled_bytes"]
    assert total == summary["compiled_memory"]["bytes"]
    label = memory["figure_31_6_7_capacity_label_kb"]
    targets = root / "records/paper_result_targets.json"
    assert label == load(targets, identities[str(targets)])["silicon"]["sram_published_KB"] == 405
    assert (2 * total + 1024) // 2048 == label
    assert (2 * total + 1000) // 2000 != label
    return dict(candidate_sha256=candidate, placed_netlist_sha256=placed, macros=len(inventory),
                bytes=total, label=label, binary_kibibytes=total / 1024,
                exact_paper_capacity_in_bytes_published=False,
                die_dimensions_mm=dimensions(placement / "place/placed.def"))


def registered_placement_facts(root, facts, identities, memory):
    from tri_oracle_process_guard import _processes
    from verify_tri_oracle_joined_placed_constraints import parse_sdc

    work = root / REGISTERED_WRITE
    placement = work / "placement"

    def read_bound(path, expected=None):
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if expected is None:
            expected = identities[str(path)]
        assert digest == expected and identities.setdefault(str(path), digest) == digest, path
        return json.loads(raw)

    record = read_bound(root / "records/tri_oracle_registered_write_placement_result.json")
    native = read_bound(placement / "receipt.json")
    replay_path = work / "whole_chip_replay/trained_independent_receipt.json"
    replay = read_bound(replay_path, record["local_evidence_sha256"]["independent_gate_replay"])
    candidate = memory["candidate_sha256"]
    assert replay["candidate_sha256"] == candidate
    assert replay["state"] == "corrected_registered_chip_trained_replay_independently_verified"
    assert replay["memory_instances"] == memory["macros"]
    for name, expected in replay["input_sha256"].items():
        path = root / name
        if str(path) not in identities:
            identities[str(path)] = sha(path)
        assert identities[str(path)] == expected, path
    compute = read_bound(work / "corrected_candidate_inventory.json")
    assert compute["state"] == "corrected_registered_chip_compute_and_memory_inventory_verified"
    assert compute["candidate_sha256"] == candidate and compute["array_rows_and_lanes"] == [32, 8]
    assert compute["memory_instances"] == memory["macros"] and compute["compiled_bytes"] == memory["bytes"]
    facts.update(clusters=compute["clusters"], cores=compute["cores"],
                 processing_element_array=compute["array_rows_and_lanes"])
    facts["external_clock_direct_to_dispatch_and_decoder"] = compute["external_clock_direct_to_dispatch_and_decoder"]
    observed = replay["observed"]
    published = record["xcelium_gate_replay"]
    assert observed["attention"] == {
        "checked_maps": published["attention_map_entries"],
        "checked_rows": published["attention_rows"],
        "value_requests": published["attention_value_requests"],
    }
    assert observed["trained"]["exact_values"] == published["trained_feed_forward_exact_outputs"]
    assert observed["trained"]["output_tiles"] == published["trained_feed_forward_output_tiles"]
    facts["mapped_fixture_replay"] = observed

    sdc, = (root / name for name in native["input_sha256"] if name.endswith("/timing_inputs/candidate.sdc"))
    timing_reference = read_bound(sdc.with_name("receipt.json"))
    raw_sdc = sdc.read_bytes()
    assert hashlib.sha256(raw_sdc).hexdigest() == identities[str(sdc)]
    entries, _, _ = parse_sdc(raw_sdc.decode())
    assert entries["current_design"] == timing_reference["top"]
    assert entries["create_clock"][0] == "clk"
    assert float(entries["create_clock"][1]) == timing_reference["clock_period_ns"]
    facts["clock_period_ns"] = float(entries["create_clock"][1])
    facts["clock_period_scope"] = "Placed design constraint. Achievable frequency requires timing evidence."

    native_folders = (placement / "place", placement / "cold", placement / "timing",
                      work / "split_timing", work / "full_fanout_timing",
                      work / "probability_repair_placement")
    prefixes = tuple(str(path).encode() + b"/" for path in native_folders)
    workers = [pid for pid, (_, _, argv) in _processes().items()
               if any(arg == b"-log" and argv[index + 1].startswith(prefixes)
                      for index, arg in enumerate(argv[:-1]))]
    facts["native_workers_terminal"] = not workers
    facts["active_candidate_native_workers"] = sorted(workers)


def registered_timing_facts(root, facts, identities, memory):
    from verify_tri_oracle_joined_placed_constraints import verify_constraints

    work = root / REGISTERED_WRITE
    output = work / "full_fanout_timing"
    receipt_path = output / "receipt.json"
    if not receipt_path.is_file():
        return
    raw = receipt_path.read_bytes()
    identities[str(receipt_path)] = hashlib.sha256(raw).hexdigest()
    timing = json.loads(raw)
    assert timing["state"] == "registered_chip_full_fanout_pre_route_timing_measured"
    assert timing["candidate_sha256"] == memory["candidate_sha256"]
    placement = work / "placement"
    database = (placement / "receipt.json").read_bytes()
    assert hashlib.sha256(database).hexdigest() == identities[str(placement / "receipt.json")]
    assert timing["placed_database"] == json.loads(database)["placed_database"]
    assert timing["clock_period_ns"] == facts["clock_period_ns"]
    assert timing["input_sha256"][str((placement / "place/placed.v").relative_to(root))] == memory["placed_netlist_sha256"]
    source_sdc, = (root / name for name in timing["input_sha256"] if name.endswith("/timing_inputs/candidate.sdc"))
    assert timing["input_sha256"][str(source_sdc.relative_to(root))] == identities[str(source_sdc)]
    source = source_sdc.read_text()
    reference = json.loads(source_sdc.with_name("receipt.json").read_bytes())

    def evidence(path):
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        assert digest == timing["input_sha256"][str(path.relative_to(root))], path
        assert identities.setdefault(str(path), digest) == digest, path
        return raw.decode()

    recipe = evidence(output / "run.tcl")
    manifest = evidence(output / "inputs.tcl")
    assert recipe.splitlines().count("    set_db delaycal_enable_high_fanout false") == 1
    assert str(placement / "place/placed.db") in manifest
    corners = timing["corners"]
    assert corners.keys() and corners.keys() <= VIEWS
    assert timing["all_required_views_measured"] == (corners.keys() == VIEWS)
    slacks, skipped_nets = {}, {}
    for view, corner in corners.items():
        folder = output / view
        native = json.loads(evidence(folder / "native_status.json"))
        assert native == corner["native"] and native["native_exit_status"] == 0 and native["stop_reason"] is None
        console = evidence(folder / "console.log")
        markers = (f"TRI_ORACLE_JOINED_COLD_PLACED_TIMING_PASS {view}",
                   "FULL_FANOUT_SETTINGS before false", "FULL_FANOUT_SETTINGS after false")
        assert all(console.splitlines().count(marker) == 1 for marker in markers)
        assert "PreRoute RC Extraction DONE" in console and "End delay calculation (fullDC)" in console
        assert not re.search(r"(?m)^\*\*?ERROR:", console)
        skipped_nets[view] = sorted(set(re.findall(
            r"(?m)^\*\*WARN: \(IMPESI-5043\):\s*Net (\S+) is a highRC net.*detailed analysis will be skipped",
            console)))
        for name in ("before.sdc", "after.sdc"):
            counts = verify_constraints(source, evidence(folder / name), top=reference["top"])
            assert counts == reference["external_constraint_counts"]
        report = evidence(folder / "timing.rpt")
        paths = re.findall(r"(?m)^Path (\d+): (MET|VIOLATED) \((-?\d+\.\d+) ns\) (.+)$", report)
        assert [int(rank) for rank, _, _, _ in paths] == list(range(1, 16))
        assert re.findall(r"(?m)^\s*View:\s+(\w+)\s*$", report) == [view] * len(paths)
        values = [float(path[2]) for path in paths]
        assert values == sorted(values) and all(finite(value) for value in values)
        assert all((value < 0) == (path[1] == "VIOLATED") for path, value in zip(paths, values, strict=True))
        assert corner["pre_route_extraction_completed"] is True and corner["high_fanout_substitution"] is False
        assert corner["worst_slack_ns"] == values[0] and corner["endpoint"] == paths[0][3]
        assert corner["reported_violations"] == sum(value < 0 for value in values)
        slacks[view] = values[0]
    facts["high_fanout_substitution_disabled"] = True
    facts["corner_slack_ns"] = slacks
    facts["detailed_analysis_skipped_nets"] = skipped_nets


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qualification", type=Path)
    args = parser.parse_args()
    current_placement = root / REGISTERED_WRITE / "placement/receipt.json"
    pipeline_placement = root / MAPPED_PIPELINE / "mapped_placement/receipt.json"
    latest_placement = pipeline_placement.parent / "relay_site_repair/receipt.json"
    concurrent_import = root / CONCURRENT_IMPORT / "receipt.json"
    qualification_path = qualification_source(root, args.qualification, latest_placement,
                                              pipeline_placement, current_placement)
    identities = {}
    facts = {}
    errors = []
    memory = None
    try:
        if not __debug__:
            raise RuntimeError("Run the verifier with Python assertions enabled")
        assert sha(root/PAPER_RELATIVE) == PAPER_SHA256, "Paper edition changed"
        identities[str(root/PAPER_RELATIVE)] = PAPER_SHA256
        relative_qualification = qualification_path.relative_to(root) if qualification_path.is_relative_to(root) else None
        if relative_qualification == BOOTH_BUFFERED_PLACEMENT:
            memory = buffered_booth_facts(root, facts, identities)
        elif relative_qualification == BOOTH_PLACEMENT:
            memory = corrected_booth_facts(root, facts, identities)
        elif relative_qualification in {BOUNDED_RESIZED_PLACEMENT, BOUNDED_TOKEN_MAP_PLACEMENT,
                                       BOUNDED_PROBABILITY_PLACEMENT, BOUNDED_RESET_PLACEMENT}:
            reset_facts = {}
            baseline_memory = bounded_structure_facts(root, reset_facts, identities)
            assert baseline_memory is not None, "Missing verified baseline memory inventory"
            candidate_memory = bounded_reset_facts(root, reset_facts, identities, baseline_memory)
            if relative_qualification != BOUNDED_RESET_PLACEMENT:
                candidate_memory = bounded_buffered_facts(root, reset_facts, identities, candidate_memory)
            if relative_qualification in {BOUNDED_RESIZED_PLACEMENT, BOUNDED_TOKEN_MAP_PLACEMENT}:
                candidate_memory = bounded_buffered_facts(root, reset_facts, identities, candidate_memory, token_map=True)
            if relative_qualification == BOUNDED_RESIZED_PLACEMENT:
                candidate_memory = bounded_resized_facts(root, reset_facts, identities, candidate_memory)
            facts, memory = reset_facts, candidate_memory
        elif relative_qualification == BOUNDED_MAPPED_STRUCTURE:
            memory = bounded_structure_facts(root, facts, identities)
        elif relative_qualification in {TOKEN_TREE_PLACEMENT, REDUCED_PORT_PLACEMENT}:
            memory = reduced_port_placement_facts(root, facts, identities,
                                                 repaired=relative_qualification == TOKEN_TREE_PLACEMENT)
        elif relative_qualification in SCALAR_PLACEMENT_STAGES:
            from verify_tri_oracle_scalar_placement_evidence import verify
            placed = verify(guarded=relative_qualification == GUARDED_SCALAR_PLACEMENT,
                            buffered=relative_qualification == BUFFERED_GRANT_PLACEMENT)
            clusters, arrays = placed["clusters"], placed["compute"]
            memory = placed["compiled_memory"]
            width, height = placed["die_mm"]
            facts.update(
                candidate_sha256=placed["candidate_sha256"],
                evidence_stage=SCALAR_PLACEMENT_STAGES[relative_qualification],
                candidate_cold_qualified=True,
                original_full_models_verified=True,
                die_width_mm=width,
                die_height_mm=height,
                clock_period_ns=placed["constraint_period_by_view_ns"]["setup_slow"],
                clusters=len(clusters),
                cores=sum(cluster["cores"] for cluster in clusters),
                array_instances=arrays["array_instances"],
                array_geometry=[arrays["array_rows"], arrays["array_lanes"]],
                operand_bits=arrays["operand_bits"],
                nominal_operations_per_second_at_paper_clock=arrays["nominal_operations_per_second_at_paper_clock"],
                fixed_memory_macros=memory["compiled_macros"],
                unplaced_instances=placed["unplaced_instances"],
            )
        elif qualification_path == root / REPEATER_PLACEMENT:
            from verify_tri_oracle_repeater_placement_evidence import verify
            placed = verify()
            clusters = placed["candidate_topology"]["clusters"]
            arrays = placed["candidate_topology"]["compute_arrays"]
            memory = placed["candidate_compiled_memory"]
            facts.update(
                candidate_sha256=placed["candidate_placement_netlist_sha256"],
                evidence_stage="cold Innovus repeater placement",
                candidate_cold_qualified=True,
                original_full_models_verified=placed["original_full_models_verified"],
                die_width_mm=placed["die_mm"][0],
                die_height_mm=placed["die_mm"][1],
                clock_period_ns=placed["core_clock_constraint_ns"],
                clusters=len(clusters),
                cores=sum(cluster["cores"] for cluster in clusters),
                array_instances=arrays["array_instances"],
                array_geometry=[arrays["array_rows"], arrays["array_lanes"]],
                operand_bits=arrays["operand_bits"],
                nominal_operations_per_second_at_paper_clock=arrays["nominal_operations_per_second_at_paper_clock"],
                fixed_memory_macros=placed["fixed_memory_macros"],
                unplaced_instances=placed["unplaced_instances"],
                parent_mapped_netlist_sha256=placed["parent_mapped_netlist_sha256"],
                parent_exact_feedforward_values=placed["parent_exact_feedforward_values"],
                parent_completed_slow_timing_paths=placed["parent_completed_slow_timing_paths"],
            )
        elif qualification_path == concurrent_import:
            from qualify_tri_oracle_concurrent_import import import_facts
            memory = import_facts(root, root / CONCURRENT_GROUP, concurrent_import.parent, facts, identities)
        elif qualification_path == latest_placement:
            sys.path.insert(0, str(root / MAPPED_PIPELINE))
            from qualify_final_placed_candidate import facts_for
            memory = facts_for(latest_placement.parent, facts)
        elif qualification_path == pipeline_placement:
            sys.path.insert(0, str(root / MAPPED_PIPELINE))
            from qualify_mapped_pipeline_for_routing import facts_for
            memory = facts_for(pipeline_placement.parent, facts)
            if not pipeline_placement.is_file():
                errors.append("Mapped pipeline placement and cold reload are pending")
        elif qualification_path == current_placement:
            memory = registered_memory(root, identities)
            width, height = memory["die_dimensions_mm"]
            facts.update(candidate_cold_qualified=True, die_width_mm=width, die_height_mm=height)
            registered_placement_facts(root, facts, identities, memory)
            registered_timing_facts(root, facts, identities, memory)
        elif not qualification_path.exists():
            errors.append("Current placement, full-model restoration and independent qualification are not complete")
        else:
            from qualify_tri_oracle_placement296 import read_worst_path, read_delay_settings
            from tri_oracle_hierarchy_fingerprint import hierarchy_fingerprint
            from tri_oracle_process_guard import _processes
            qraw = qualification_path.read_bytes()
            qualification = json.loads(qraw)
            identities[str(qualification_path)] = hashlib.sha256(qraw).hexdigest()
            assert qualification["state"] == "placed_parent_and_original_full_models_independently_qualified"
            for name, expected in qualification["evidence_sha256"].items():
                assert sha(name) == expected, "Changed qualification evidence "+name
                identities[name] = expected
            producer = root/"records/restore295_full_result.json"
            assert qualification["evidence_sha256"][str(producer)] == sha(producer)
            restored = json.loads(producer.read_text())
            assert restored["state"] == "full_original_models_cold_verified_and_three_corner_diagnostics_completed"
            for key in ["source_sha256", "native_evidence_sha256", "generated_sha256"]:
                for name, expected in restored.get(key, {}).items():
                    assert sha(name) == expected, "Changed native verification evidence "+name
                    assert name not in identities or identities[name] == expected
                    identities[name] = expected
            fingerprint = restored["output_database_fingerprint"]
            dependencies = {Path(name): value for name, value in fingerprint.get("directory_dependencies", {}).items()}
            assert hierarchy_fingerprint(restored["output_database"], directory_dependencies=dependencies) == fingerprint
            placed_path = root/"records/guidance294_placement_result.json"
            assert restored["source_sha256"][str(placed_path)] == sha(placed_path)
            placed = json.loads(placed_path.read_text())
            assert placed["state"] == "compact_parent_placement_cold_geometry_and_connectivity_verified"
            prefixes = [str(Path(record["output_directory"]))+"/" for record in [placed, restored]]
            workers = [pid for pid, (_, _, argv) in _processes().items()
                       if any(argv[i] == b"-log" and any(argv[i+1].startswith(prefix.encode()) for prefix in prefixes)
                              for i in range(len(argv)-1))]
            facts["native_workers_terminal"] = not workers
            facts["candidate_cold_qualified"] = (
                qualification["all_six_hierarchy_fields_preserved"] is True
                and qualification["original86_protected_targets_preserved"] is True
                and qualification["original_three_corner_constraints_preserved"] is True)
            facts["original_full_models_verified"] = (
                qualification["original_core_cells"] == 1889420
                and qualification["original_memory_models"] == 600
                and restored["full600_memory_restore_pending"] is False
                and restored["guidance_models_removed"] is True)
            accepted_path = root/"records/controller278_physical_functional_qualification.json"
            assert qualification["evidence_sha256"][str(accepted_path)] == sha(accepted_path)
            accepted = json.loads(accepted_path.read_text())
            facts.update(cores=accepted["actual_cores"], clusters=accepted["actual_clusters"])
            out = Path(restored["output_directory"])
            facts["die_width_mm"], facts["die_height_mm"] = dimensions(out/"full/restored_parent.def")
            text = (out/"cold/setup_typ.sdc").read_text()
            clocks = [line for line in text.splitlines()
                      if line.startswith("create_clock ") and re.search(r"-name\s+core_clock\b", line)]
            assert len(clocks) == 1
            match = re.search(r"-period\s+([0-9.]+)(?:\s|$)", clocks[0])
            assert match
            facts["clock_period_ns"] = float(match[1])
            facts["corner_slack_ns"] = {}
            settings = []
            for view in sorted(VIEWS):
                folder = out/("corner_"+view)
                actual = read_worst_path(folder/"slack_properties.tsv", view)
                assert actual == qualification["corner_diagnostics"][view]["worst"]
                facts["corner_slack_ns"][view] = actual["slack_ns"]
                for tag in ["before", "after"]:
                    settings.append(read_delay_settings(folder/(tag+"_delay_settings.tsv"),
                                                        require_high_fanout_disabled=True))
            facts["high_fanout_substitution_disabled"] = all(
                item["delaycal_enable_high_fanout"] == "false" for item in settings)
            # The real qualification flows are absent. Do not read success
            # Booleans from a placement receipt as substitutes for their proof.
            facts.update(dict.fromkeys(UNIMPLEMENTED_VERIFIERS, None))
            assert all(sha(name) == expected for name, expected in identities.items()), "Evidence changed during checking"
    except Exception as error:
        errors.append(repr(error))
    checks = placement_checks(facts)
    checks["memory_capacity_reconciled"] = memory is not None
    advance = False
    report = dict(mode="hold_only_missing_independent_paper_qualification_flows",
        unimplemented_verifiers=list(UNIMPLEMENTED_VERIFIERS),
        advance_to_clock_distribution_or_routing_allowed=advance,
        qualification=str(qualification_path),paper_sha256=PAPER_SHA256,
        observed_facts=facts,registered_memory=memory,checks=checks,failed_checks=[name for name, value in checks.items() if not value],
        verification_errors=errors,
        scope="Hold-only placement diagnostics. Memory is compared at the paper's rounded binary precision. Complete architecture, trained mapped execution and matching model accuracy remain unqualified.")
    print(json.dumps(report, indent=2))
    return 0 if advance else 1


if __name__ == "__main__":
    raise SystemExit(main())
