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


def qualification_source(root, requested, *previous):
    if requested is not None:
        return requested.resolve()
    for candidate in (SCALAR_PLACEMENT, REPEATER_PLACEMENT):
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
        if qualification_path == root / SCALAR_PLACEMENT:
            from verify_tri_oracle_scalar_placement_evidence import verify
            placed = verify()
            clusters, arrays = placed["clusters"], placed["compute"]
            memory = placed["compiled_memory"]
            width, height = placed["die_mm"]
            facts.update(
                candidate_sha256=placed["candidate_sha256"],
                evidence_stage="cold Innovus scalar placement",
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
