"""Run the trained raw and indexed fixtures on a bound dual-group candidate."""

import argparse
import importlib.util
import json
from pathlib import Path
import re
import sys
import time

from audit_tri_oracle_placed_chip_boundary import digest
from run_tri_oracle_indexed_native_replay import read, run_xcelium, validate_inputs, verify


def write(path, data):
    with path.open("x") as receipt:
        json.dump(data, receipt, indent=2, sort_keys=True)
        receipt.write("\n")


def prepare(reference, candidate, candidate_hash, output):
    baseline = read(reference / "inputs.json")
    old_bundle = reference / "bundle.sv"
    source, = [name for name, checksum in baseline["inputs"].items()
               if checksum == baseline["candidate_sha256"]]
    old_include = f'`include "{source}"'
    text = old_bundle.read_text()
    assert text.splitlines().count(old_include) == 1
    assert digest(old_bundle) == baseline["inputs"][str(old_bundle)]
    output.mkdir()
    bundle = output / "bundle.sv"
    bundle.write_text(text.replace(old_include, f'`include "{candidate}"', 1))
    paths = {name: checksum for name, checksum in baseline["inputs"].items()
             if name not in (source, str(old_bundle))}
    paths[str(candidate)] = candidate_hash
    paths[str(bundle)] = digest(bundle)
    options = [arg.replace(str(reference) + "/", str(output) + "/") for arg in baseline["args"]]
    assert options.count(str(bundle)) == 1
    assert options[options.index("-log") + 1] == str(output / "xrun.log")
    assert options.count(f"+PROGRESS={output / 'progress.log'}") == 1
    return {"candidate_sha256": candidate_hash, "reference_stage": str(reference),
            "reference_candidate_sha256": baseline["candidate_sha256"],
            "inputs": paths, "args": options}


def await_previous(stage):
    """Wait for the specific existing indexed experiment to finish."""
    deadline = time.monotonic() + 3600
    last_live = time.monotonic()
    while True:
        status = stage / "status.json"
        proof = stage / "verified.json"
        if status.is_file() and proof.is_file():
            try:
                result, measured = read(proof), read(status)
            except json.JSONDecodeError:
                time.sleep(1)
                continue
            assert measured["exit_status"] == result["native"]["exit_status"] == 0
            assert result["candidate_sha256"] == read(stage / "inputs.json")["candidate_sha256"]
            assert result["state"] == "native_indexed_trained_feedforward_and_writeback_verified"
            return result
        if status.is_file() and status.stat().st_size:
            try:
                terminal = read(status)
            except json.JSONDecodeError:
                terminal = {}
            if terminal.get("exit_status", 0) != 0:
                raise RuntimeError(f"The reference run failed with exit status {terminal['exit_status']}")
        pid, = re.findall(r"(?m)^INDEXED_XSIM_STARTED pid=(\d+)$",
                          (stage / "supervisor.log").read_text())
        proc = Path("/proc") / pid
        try:
            if (proc / "cwd").readlink() == stage and (
                proc / "comm"
            ).read_text().strip() in {"xrun", "xmelab", "xmsim"}:
                last_live = time.monotonic()
        except FileNotFoundError:
            pass
        now = time.monotonic()
        if now > deadline or now - last_live > 60:
            raise RuntimeError("The reference indexed replay ended without verified evidence")
        time.sleep(5)


def raw_transcript_checker():
    record = read(Path("records/tri_oracle_guarded_scalar_cold_trained_writeback_xcelium.json"))
    verifier, = (Path(name) for name in record["evidence_sha256"] if name.endswith("/verify.py"))
    assert digest(verifier) == record["evidence_sha256"][str(verifier)]
    spec = importlib.util.spec_from_file_location("tri_oracle_guarded_transcript", verifier)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(verifier.resolve().parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module.check_transcript, verifier


def verify_raw(stage, reference, manifest, native):
    assert native["exit_status"] == 0
    witness = read(reference / "verified.json")
    assert witness["candidate_sha256"] == manifest["reference_candidate_sha256"]
    checker, verifier = raw_transcript_checker()
    log = stage / "xrun.log"
    progress = stage / "progress.log"
    previous_log = reference / "xrun.log"
    previous_progress = reference / "progress.log"
    text = log.read_text()
    assert text.splitlines().count("AUTONOMOUS_RESIDUAL_LEASE_PASS override=0 released=1") == 1
    assert text.splitlines().count(f"\t-log {log}") == 1
    assert text.splitlines().count(f"\t{stage / 'bundle.sv'}") == 1
    measured = checker(text, progress.read_text())
    assert measured == checker(previous_log.read_text(), previous_progress.read_text())
    assert len(measured[3]) == 90
    return dict(
        state="widened_native_raw_replay_matches_reference",
        candidate_sha256=manifest["candidate_sha256"],
        baseline_checkpoint_and_transaction_trace_equal=True,
        functional_checkpoints=len(measured[3]),
        compiled_memory_paths=len(measured[2]),
        exact_feedforward_values=4096,
        exact_writeback_values=4096,
        **native,
        evidence_sha256={str(p): digest(p) for p in
                         (log, progress, previous_log, previous_progress, verifier)},
    )


def execute(candidate, link_receipt, raw_reference, indexed_reference, output, *, preflight=False):
    reference_proof = read(link_receipt)
    candidate_hash = digest(candidate)
    assert candidate_hash == reference_proof["candidate_sha256"]
    assert reference_proof["compiled_memory_paths"] == 631
    for reference in (raw_reference, indexed_reference):
        reference_manifest = read(reference / "inputs.json")
        assert reference_manifest["candidate_sha256"] == reference_proof["base_sha256"]
    output.mkdir()
    raw, indexed = (output / mode for mode in ("raw", "indexed"))
    manifests = [prepare(reference, candidate, candidate_hash, stage) for reference, stage in
                 ((raw_reference, raw), (indexed_reference, indexed))]
    for stage, manifest in zip((raw, indexed), manifests, strict=True):
        validate_inputs(manifest)
        write(stage / "inputs.json", manifest)
    print("DUAL_GROUP_REPLAY_INPUTS_VERIFIED", candidate_hash, flush=True)
    if preflight:
        return

    prior_indexed = await_previous(indexed_reference)
    print("DUAL_GROUP_PREVIOUS_INDEXED_VERIFIED", flush=True)
    raw_native = run_xcelium(raw, manifests[0]["args"])
    write(raw / "status.json", raw_native)
    validate_inputs(manifests[0])
    raw_proof = verify_raw(raw, raw_reference, manifests[0], raw_native)
    write(raw / "verified.json", raw_proof)
    print("DUAL_GROUP_RAW_REPLAY_VERIFIED", flush=True)
    indexed_native = run_xcelium(indexed, manifests[1]["args"])
    write(indexed / "status.json", indexed_native)
    validate_inputs(manifests[1])
    result = verify(indexed, raw, raw_proof, indexed_native)
    assert result["candidate_sha256"] == candidate_hash
    assert result["indexed_response_beats_by_lane"] == prior_indexed["indexed_response_beats_by_lane"]
    result["earlier_indexed_traffic"] = prior_indexed["indexed"]
    result["scope"] = "Candidate-bound trained functional replay with timing checks disabled."
    write(indexed / "verified.json", result)
    print("DUAL_GROUP_INDEXED_REPLAY_VERIFIED", flush=True)


def main():
    assert __debug__ and Path("/.dockerenv").is_file()
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("candidate", "link_receipt", "raw_reference", "indexed_reference", "output"):
        parser.add_argument(name, type=Path)
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()
    execute(*(getattr(args, name).resolve() for name in
              ("candidate", "link_receipt", "raw_reference", "indexed_reference", "output")),
            preflight=args.preflight)


if __name__ == "__main__":
    main()
