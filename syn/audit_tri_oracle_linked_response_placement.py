"""Independently check the response-address placement comparison."""

import argparse
from collections import Counter
import json
from pathlib import Path
import shutil

from audit_tri_oracle_compact_setup_paths import COMPACT, ROOT, audit, parse_setup_paths, read, sha
from tri_oracle_artifact_fingerprint import artifact_fingerprint
from verify_tri_oracle_shared_memory import require


BASELINE = (COMPACT / "weight_data_unmask/row_enable_bank_buffer_trial"
            / "attention_select_buffer_trial/physical_comparison")
NATIVE_STAGES = {
    "eco": ("native_placement", "RESPONSE_ADDRESS_PLACEMENT_SAVED"),
    "extract": ("native_extraction", "COMPACT_ESTIMATED_PARASITICS_WRITTEN"),
    "report": ("native_report", "COMPACT_ESTIMATED_PARASITICS_RELOADED"),
}


def matched_delta(baseline_paths, candidate_paths):
    periods = {path["period_ns"] for path in baseline_paths + candidate_paths}
    require(len(periods) == 1, "Matched timing requires the same clock period")
    return candidate_paths[0]["slack_ns"] - baseline_paths[0]["slack_ns"]


def preflight(directory, pin):
    output = directory / "physical_comparison"
    setup_path, link_path = output / "prepared.json", directory / "receipt.json"
    for path in (setup_path, link_path):
        pin(path)
    setup, link = read(setup_path), read(link_path)
    require(setup["state"] == "response_address_placement_comparison_prepared",
            "Placement comparison preparation is missing")
    require(link["state"] == "mapped_response_address_logic_linked_with_buffered_fabric_preserved",
            "Wrong candidate type")
    for path, expected in setup["input_sha256"].items():
        pin(Path(path), expected)
    candidate = directory / "candidate.v"
    require(pin(candidate) == setup["candidate_sha256"] == link["candidate_sha256"]
            and setup["top"] == link["top"], "Placement selected a different candidate")

    baseline = BASELINE / "eco/placed.db"
    require(artifact_fingerprint(baseline) == setup["baseline_database"], "Buffered database changed")
    baseline_summary, baseline_evidence = audit(BASELINE)
    for path, expected in baseline_evidence.items():
        pin(ROOT / path, expected)
    baseline_paths = parse_setup_paths((BASELINE / "report/timing.rpt").read_text())
    required = {"-keep_inst_location", "-no_eco_place", "-no_eco_route", "-skip_ccopt"}
    script = (output / "eco/place.tcl").read_text()
    commands = [line for line in script.splitlines() if line.startswith("eco_design ")]
    require(len(commands) == 1 and required <= set(commands[0].split()) and str(candidate) in commands[0],
            "Placement script changed the preserved geometry or allowed routing")
    return setup, baseline_summary, baseline_paths


def completed(directory, setup, baseline, baseline_paths, pin):
    work = directory / "physical_comparison"
    proof_path = work / "receipt.json"
    pin(proof_path)
    proof = read(proof_path)
    require(proof["state"] == "linked_response_address_matched_placement_timing_measured"
            and proof["candidate_sha256"] == setup["candidate_sha256"],
            "Missing completed placement comparison for this candidate")
    pins = proof["evidence_sha256"]
    for path, field, state in (
        (directory / "integrated_attention/receipt.json", "replay", "response_address_linked_netlist_preserved_archived_attention"),
        (directory / "integrated_trained/receipt.json", "native", "response_address_linked_netlist_preserved_trained_layer"),
    ):
        pin(path, pins[str(path)])
        replay = read(path)
        require(replay["state"] == state and replay["candidate_sha256"] == proof["candidate_sha256"]
                and replay[field]["native_exit_status"] == 0 and replay["compiled_memory_macros"] == 623,
                f"Native replay does not qualify this placement: {path}")
        if field == "native":
            progress = path.with_name("progress.log")
            pin(progress, replay["input_sha256"][str(progress)])
            archive = COMPACT / "linked_tensor_trained/progress.log"
            require(pin(archive) == pin(progress) and replay["counters"]["exact_outputs"] == 32768,
                    "Trained outputs or milestone cycles differ")
    expected_poses = (BASELINE / "report/macro_poses.tsv").read_text().splitlines()
    require(len(expected_poses) == len(set(expected_poses)) == proof["fixed_memory_macros"] == 623,
            "Baseline compiled-memory poses are incomplete")
    for stage, (receipt_key, marker) in NATIVE_STAGES.items():
        folder = work / stage
        log = folder / "console.log"
        stage_receipt = proof[receipt_key]
        pin(log, stage_receipt["log_sha256"])
        lines = log.read_text().splitlines()
        require(stage_receipt["native_exit_status"] == 0 and lines.count(marker) == 1,
                f"Incomplete native stage: {stage}")
        if stage == "eco":
            require(lines.count("RESPONSE_ADDRESS_PRESERVED_BUFFERS 192") == 1
                    and lines.count("RESPONSE_ADDRESS_PRESERVED_BUFFERS 72") == 1
                    and proof["retained_timing_buffers"] == 264, "Verified buffers were not preserved")
        else:
            require(lines.count("PLACED_TIMING_MODE single HIGH_FANOUT_DEFAULT_DELAY false") == 1,
                    f"Timing configuration changed: {stage}")
        poses = folder / "macro_poses.tsv"
        pin(poses)
        require(sorted(poses.read_text().splitlines()) == sorted(expected_poses), f"Macro pose changed: {stage}")
    database = work / "eco/placed.db"
    checkpoint = artifact_fingerprint(database)
    require(checkpoint == proof["placed_database"], "Placed checkpoint changed")
    prefixes = ("libs/mmmc/", "libs/lef/")
    old_files, new_files = setup["baseline_database"]["files"], checkpoint["files"]
    original = {name: data["sha256"] for name, data in old_files.items() if name.startswith(prefixes)}
    current = {name: data["sha256"] for name, data in new_files.items() if name.startswith(prefixes)}
    require(original and current == original
            and new_files["viewDefinition.tcl"] == old_files["viewDefinition.tcl"],
            "Timing views or physical libraries changed across the placement comparison")
    report = work / "report/timing.rpt"
    pin(report, pins[str(report)])
    annotation = work / "report/annotation.rpt"
    pin(annotation, pins[str(annotation)])
    pin(work / "estimated_slow.spef", proof["estimated_spef_sha256"])
    paths = parse_setup_paths(report.read_text())
    delta = matched_delta(baseline_paths, paths)
    timing = {"reported_paths": len(paths), "violating_paths": sum(path["slack_ns"] < 0 for path in paths),
              "worst_slack_ns": paths[0]["slack_ns"]}
    require(timing == proof["timing"] and baseline["timing"] == proof["baseline_timing"]
            and abs(delta - proof["delta_worst_slack_ns"]) < 1e-9, "Native path summaries disagree")
    return {"timing": timing, "delta_worst_slack_ns": delta, "worst_path": paths[0],
            "startpoints": dict(Counter(path["startpoint"] for path in paths))}


def run(directory, preflight_only):
    require(__debug__, "Run the audit with assertions enabled")
    evidence = {}

    def pin(path, expected=None):
        digest = sha(path)
        require(expected is None or digest == expected, f"Changed evidence: {path}")
        require(evidence.setdefault(str(path), digest) == digest, f"Evidence changed during audit: {path}")
        return digest

    setup, baseline, baseline_paths = preflight(directory, pin)
    result = {
        "state": "response_address_comparison_inputs_verified",
        "candidate_sha256": setup["candidate_sha256"], "baseline_timing": baseline["timing"],
        "disk_available_bytes": shutil.disk_usage(directory).free,
        "scope": "Matched pre-route setup diagnostics for the placed decoder at the slow corner.",
    }
    if not preflight_only:
        result.update(state="response_address_placed_setup_independently_verified",
                      **completed(directory, setup, baseline, baseline_paths, pin))
    for helper in (parse_setup_paths, artifact_fingerprint):
        pin(Path(helper.__code__.co_filename).resolve())
    pin(Path(__file__).resolve())
    require(all(sha(path) == digest for path, digest in evidence.items()), "Evidence changed during audit")
    return result | {"evidence_sha256": {str(Path(path).relative_to(ROOT)): value for path, value in evidence.items()}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=lambda path: Path(path).resolve())
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args.candidate, args.preflight), indent=2, sort_keys=True))
