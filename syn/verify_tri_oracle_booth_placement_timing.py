"""Verify three native pre-route timing views for the repaired Booth chip."""

from argparse import ArgumentParser
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re
import time

from tri_oracle_artifact_fingerprint import artifact_fingerprint
from verify_tri_oracle_corrected_booth_roundtrip import ROOT, TOP, constraints, digest

PLACEMENT = Path("records/tri_oracle_corrected_booth_buffered_placement_roundtrip.json")
DRIVER = Path("syn/tri_oracle_report_booth_placement_timing.tcl")
VIEWS = ("setup_slow", "setup_typ", "hold_fast")


def read(path):
    return json.loads(path.read_text())


def constraint_commands(path):
    return Counter(" ".join(line.split()) for line in path.read_text().splitlines()
                   if line.strip() and not line.lstrip().startswith("#"))


def view_reports(folder, view):
    status = read(folder / "status.json")
    assert status["exit_status"] == 0 and status["stop_reason"] is None, (view, status)
    console = (folder / "console.log").read_text()
    lines = console.splitlines()
    assert lines.count(f"BOOTH_PLACEMENT_TIMING_PASS {view}") == 1
    for when in ("before", "after"):
        assert lines.count(f"BOOTH_TIMING_SETTINGS {when} {view} false false") == 1
    assert "PreRoute RC Extraction DONE" in console and "End delay calculation (fullDC)" in console
    assert not re.search(r"(?m)^\*\*?ERROR:", console)
    simplified = sorted(set(re.findall(r"(?m)^\*\*WARN: \(IMPESI-5043\):\s*Net (\S+)", console)))
    assert constraint_commands(folder / "before.sdc") == constraint_commands(folder / "after.sdc"), view
    annotation = (folder / "annotation.rpt").read_text()
    fields = re.findall(r"(?m)^\| real net \(complete\)\s*\|\s*(\d+)\s*\|\s*(\d+)\s+[\d.]+%\s*\|\s*(\d+)",
                        annotation)
    assert len(fields) == 1, view
    total, annotated, not_annotated = map(int, fields[0])
    assert total > 0 and annotated + not_annotated == total

    report = (folder / "timing.rpt").read_text()
    option = "-early" if view == "hold_fast" else "-check_type setup"
    assert f"report_timing -view $view {option} -max_paths 20 > timing.rpt" in report
    paths = re.findall(r"(?m)^Path (\d+): (MET|VIOLATED) \((-?\d+\.\d+) ns\) (.+)$", report)
    assert len(paths) == 20 and [int(row[0]) for row in paths] == list(range(1, 21))
    assert re.findall(r"(?m)^\s*View:\s+(\w+)\s*$", report) == [view] * len(paths)
    slacks = [float(row[2]) for row in paths]
    assert slacks == sorted(slacks)
    assert all(entry[2].startswith("-") == (entry[1] == "VIOLATED") for entry in paths)
    check = "Hold" if view == "hold_fast" else "Setup"
    other_check = "Setup" if view == "hold_fast" else "Hold"
    assert all(not entry[3].startswith(other_check + " Check") for entry in paths), view
    return {
        "native": status,
        "check": check.lower(),
        "pre_route_extraction_completed": True,
        "high_fanout_substitution": False,
        "ignore_net_load": False,
        "real_complete_nets": total,
        "externally_annotated_nets": annotated,
        "worst_slack_ns": slacks[0],
        "reported_path_count": len(paths),
        "violating_reported_paths": sum(entry[1] == "VIOLATED" for entry in paths),
        "worst_check": paths[0][3],
        "detailed_analysis_skipped_nets": simplified,
    }


def verify(root=ROOT, *, allow_incomplete=False):
    placement = read(root / PLACEMENT)
    assert placement["state"] == "corrected_buffer_repair_placement_and_cold_reload_verified"
    database = Path(placement["database"])
    stage = database.parents[1]
    output = stage / "timing_three_views"
    plan_file = output / "prepared_timing.json"
    plan = read(root / plan_file)
    assert Path(plan["database"]) == root / database and tuple(plan["views"]) == VIEWS
    assert plan["driver_sha256"] == digest(root / DRIVER)
    fingerprint = json.dumps(artifact_fingerprint(root / database), sort_keys=True, separators=(",", ":")).encode()
    database_hash = sha256(fingerprint).hexdigest()
    assert database_hash == placement["database_fingerprint_sha256"] == plan["database_fingerprint_sha256"]
    results = {}
    pending, failed = [], {}
    evidence = [PLACEMENT, DRIVER, plan_file, Path(__file__).resolve().relative_to(ROOT)]
    for view in VIEWS:
        target = stage / "cold" / f"{view}.sdc"
        assert digest(root / target) == placement["evidence_sha256"][str(target)]
        folder = output / view
        if allow_incomplete:
            status_path = folder / "status.json"
            if not (root / status_path).is_file():
                pending.append(view)
                continue
            status = read(root / status_path)
            if status["exit_status"] != 0 or status["stop_reason"] is not None:
                failed[view] = status
                evidence.append(status_path)
                continue
        assert constraints(root / folder / "before.sdc") == constraints(root / target)
        results[view] = view_reports(root / folder, view)
        evidence.extend([target, *(folder / name for name in
                                   ("before.sdc", "after.sdc", "console.log", "status.json",
                                    "annotation.rpt", "timing.rpt"))])
    report = {
        "state": ("corrected_buffered_booth_three_pre_route_timing_views_measured" if len(results) == len(VIEWS)
                  else "corrected_buffered_booth_pre_route_timing_incomplete"),
        "scope": "Single-view early-route extraction estimates from the same repaired placement, under the original constraints and ideal clocks.",
        "top": TOP,
        "database_fingerprint_sha256": database_hash,
        "corners": results,
        "evidence_sha256": {str(path): digest(root / path) for path in evidence},
    }
    if allow_incomplete:
        report.update(pending_views=pending, failed_views=failed)
    return report


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--wait", action="store_true", help="Wait for the scheduled three-view Innovus run")
    if parser.parse_args().wait:
        output = Path(read(PLACEMENT)["database"]).parents[1] / "timing_three_views"
        deadline = time.monotonic() + 49 * 3600
        while True:
            text = (output / "supervisor.log").read_text()
            if "BOOTH_TIMING_THREE_VIEW_COMPLETE" in text.splitlines():
                break
            if "Traceback" in text or time.monotonic() > deadline:
                raise RuntimeError(f"Timing worker did not complete. See {output / 'supervisor.log'}")
            time.sleep(20)
    print(json.dumps(verify(), indent=2, sort_keys=True))
