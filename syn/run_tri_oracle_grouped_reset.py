"""Run and cold-check the grouped reset placement trial under a memory guard."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from audit_tri_oracle_placed_fanout import GIB, TOOL, memory, sha
from tri_oracle_artifact_fingerprint import artifact_fingerprint
from tri_oracle_process_guard import terminate_process_group


ROOT = Path.cwd()
RECIPE = ROOT / "syn/tri_oracle_apply_grouped_reset.tcl"


def native(output, mode, checkpoint, plan):
    available, anonymous = memory()
    assert available > 16 * GIB and anonymous < 3 * GIB
    output.mkdir()
    stem = output / "innovus"
    log = output / "console.log"
    env = os.environ | {"TRI_ORACLE_RESET_MODE": mode, "TRI_ORACLE_RESET_CHECKPOINT": str(checkpoint),
                        "TRI_ORACLE_RESET_PLAN": str(plan)}
    argv = ["/usr/bin/prlimit", f"--as={23 * GIB}", "--", TOOL, "-stylus", "-no_gui", "-batch",
            "-log", str(stem), "-files", str(RECIPE)]
    start = time.monotonic()
    peak, minimum = anonymous, available
    with log.open("x") as stream:
        worker = subprocess.Popen(argv, cwd=output, env=env, stdout=stream, stderr=subprocess.STDOUT,
                                  stdin=subprocess.DEVNULL, start_new_session=True)
        print(f"GROUPED_RESET_STAGE_STARTED {mode} {worker.pid}", flush=True)
        try:
            while worker.poll() is None:
                available, anonymous = memory()
                peak, minimum = max(peak, anonymous), min(minimum, available)
                if minimum < 5 * GIB or peak > 15 * GIB or time.monotonic() - start > 3600:
                    raise RuntimeError(f"Reset trial resource guard: {minimum}, {peak}")
                time.sleep(0.5)
        finally:
            terminate_process_group(worker, log_argument=str(stem))
    text = log.read_text()
    assert worker.returncode == 0 and "**ERROR" not in text
    assert f"TRI_ORACLE_GROUPED_RESET_{mode}_PASS" in text.splitlines()
    assert "Started Early Global Route" not in text and "PreRoute RC Extraction DONE" not in text
    return dict(seconds=time.monotonic()-start, peak_anonymous_bytes=peak, minimum_host_available_bytes=minimum)


def run(placement, plan, plan_receipt, output):
    assert __debug__ and Path("/.dockerenv").is_file() and os.environ.get("CDS_LIC_FILE")
    assert output.is_relative_to(ROOT / ".cache")
    assert shutil.disk_usage(output.parent).free >= 8 * GIB, "Reset trial needs 8 GiB of free disk space"
    reference = json.loads((placement / "receipt.json").read_text())
    assert reference["state"] == "concurrent_chip_placed_and_cold_verified"
    checkpoint = placement / "place/placed.db"
    checkpoint_hash = artifact_fingerprint(checkpoint)
    assert checkpoint_hash == reference["placed_database"]
    planned = json.loads(plan_receipt.read_text())
    assert planned["placed_netlist_sha256"] == reference["input_sha256"][str(placement / "place/placed.v")]
    assert sha(placement / "place/placed.v") == planned["placed_netlist_sha256"]
    assert planned["state"] == "placed_grouped_reset_trees_planned_and_pin_loads_checked"
    plan_hashes = {plan / f"grouped_{group}.tsv": planned["evidence_sha256"][str((plan / f"grouped_{group}.tsv").relative_to(ROOT))]
                   for group in range(5)}
    assert all(sha(path) == digest for path, digest in plan_hashes.items())
    assert all(branch["buffers"] == 774 and branch["sinks"] == 18484 for branch in planned["groups"].values())
    output.mkdir()
    prepare, apply, cold = (output / step for step in ("prepare", "apply", "cold"))
    prep = native(prepare, "prepare", checkpoint, plan)
    prepared = prepare / "prepared.db"
    prepared_hash = artifact_fingerprint(prepared)
    first = native(apply, "apply", prepared, plan)
    assert artifact_fingerprint(prepared) == prepared_hash
    new = apply / "trial.db"
    new_hash = artifact_fingerprint(new)
    second = native(cold, "cold", new, plan)
    assert artifact_fingerprint(new) == new_hash and artifact_fingerprint(checkpoint) == checkpoint_hash
    assert (apply / "reset_tree.tsv").read_bytes() == (cold / "reset_tree.tsv").read_bytes()
    assert all(sha(path) == digest for path, digest in plan_hashes.items())
    names = (RECIPE, plan_receipt, apply / "trial.v", apply / "trial.def", apply / "console.log",
             cold / "console.log", cold / "reset_tree.tsv", apply / "placement.rpt")
    result = dict(state="native_grouped_reset_trial_placed_and_cold_connectivity_checked",
                  original_netlist_sha256=planned["placed_netlist_sha256"],
                  evidence_sha256={str(path.relative_to(ROOT)): sha(path) for path in names},
                  native=dict(prepare=prep, apply=first, cold=second), scope="Reset tree connectivity checked on a separate placement. "
                  "Independent whole-chip equivalence, timing and functional replay are pending.")
    with (output / "receipt.json").open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print("GROUPED_RESET_TRIAL_COLD_CHECKED", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("placement", "plan", "plan_receipt", "output"):
        parser.add_argument(name, type=lambda value: Path(value).resolve())
    run(**vars(parser.parse_args()))
