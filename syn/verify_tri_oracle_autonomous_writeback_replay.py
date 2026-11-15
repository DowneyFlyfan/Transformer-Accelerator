"""Compare an autonomous whole-chip replay against the verified guarded run."""

import argparse
import json
from pathlib import Path
import re
import sys

from link_tri_oracle_writeback_control import sha


ROOT = Path(__file__).resolve().parents[1]
AUTONOMOUS = ROOT / ".cache/residual_command_request"
REPEATERS = AUTONOMOUS / "descriptor_fields/physical/command_repeaters"
REFERENCE = ROOT / ".cache/residual_bank_command_binding/trained"
VARIANTS = {
    "autonomous": (AUTONOMOUS, "tri_oracle_residual_command_request_mapping.json"),
    "repeaters": (REPEATERS, "tri_oracle_descriptor_repeaters_seed.json"),
    "reduced-ports": (REPEATERS / "internal_probes", "tri_oracle_internal_writeback_probes.json"),
}


def verify(variant, *, preflight=False):
    assert __debug__ and Path("/.dockerenv").is_file()
    evidence = {}

    def pin(path, expected=None):
        name = str(path.relative_to(ROOT))
        if name not in evidence:
            evidence[name] = sha(path)
        assert expected is None or evidence[name] == expected, name
        return path

    def read(path, expected=None):
        return json.loads(pin(path, expected).read_bytes())

    work, mapping_name = VARIANTS[variant]
    records = ROOT / "records"
    stage = work / "whole_chip"
    mapping = read(records / mapping_name)
    ref = read(records / "tri_oracle_residual_bank_command_trained_replay.json")
    manifest = read(stage / "inputs.json")
    assert Path(manifest["reference"]) == REFERENCE
    assert manifest["candidate_sha256"] == mapping["candidate_sha256"]
    candidate = work / "candidate.v"
    assert manifest["inputs"][str(candidate)] == manifest["candidate_sha256"]
    for name, digest in manifest["inputs"].items():
        pin(Path(name), digest)
    bundle = stage / "bundle.sv"
    assert str(bundle) in manifest["inputs"]
    includes = re.findall(r'(?m)^`include "([^"]+)"$', bundle.read_text())
    assert includes.count(str(candidate)) == 1 and set(includes) <= manifest["inputs"].keys()
    log = stage / "xrun.log"
    args = manifest["args"]
    assert args[0].endswith("/xrun") and args[args.index("-log") + 1] == str(log)
    assert {"-notimingchecks", "-nospecify"} <= set(args)
    assert args.count(str(bundle)) == 1

    reference_log, reference_progress = (
        pin(path, ref["evidence_sha256"][str(path.relative_to(ROOT))])
        for path in (REFERENCE / "xrun.log", REFERENCE / "progress.log")
    )
    guarded = read(records / "tri_oracle_guarded_scalar_cold_trained_writeback_xcelium.json")
    (verifier_path,) = (ROOT / name for name in guarded["evidence_sha256"] if name.endswith("/verify.py"))
    pin(verifier_path, guarded["evidence_sha256"][str(verifier_path.relative_to(ROOT))])
    sys.path.insert(0, str(verifier_path.parent))
    try:
        from verify import check_transcript
    finally:
        sys.path.pop(0)
    assert Path(check_transcript.__code__.co_filename) == verifier_path
    baseline = check_transcript(reference_log.read_text(), reference_progress.read_text())
    assert len(baseline[2]) == 631 and len(baseline[3]) == 90
    status = stage / "status.json"
    if preflight:
        return {"state": "whole_chip_replay_inputs_and_guarded_reference_verified",
                "candidate_sha256": manifest["candidate_sha256"]}

    terminal, scored = read(status), read(stage / "verified.json")
    assert terminal["exit_status"] == 0
    assert all(scored[name] == value for name, value in terminal.items())
    assert scored["candidate_sha256"] == mapping["candidate_sha256"]
    native = pin(log).read_text()
    lines = native.splitlines()
    assert lines.count(f"\t-log {log}") == lines.count(f"\t{bundle}") == 1
    assert {"\t-notimingchecks", "\t-nospecify"} <= set(lines)
    assert lines.count("AUTONOMOUS_RESIDUAL_LEASE_PASS override=0 released=1") == 1
    actual = check_transcript(native, pin(stage / "progress.log").read_text())
    assert actual[1:] == baseline[1:], "Mismatch in memory paths, transactions or cycle checkpoints"
    assert scored["compiled_memory_paths"] == len(actual[2])
    assert scored["exact_feedforward_values"] == scored["exact_writeback_values"] == 4096
    assert scored["independent_lease_from_validated_command"]
    assert scored["baseline_checkpoint_and_transaction_trace_equal"]
    assert scored["override_residual_request_used"] is False
    pin(Path(__file__))
    keep = {str(path.relative_to(ROOT)) for path in (
        candidate, bundle, log, stage / "progress.log", stage / "inputs.json", status, stage / "verified.json",
        reference_log, reference_progress, verifier_path, records / mapping_name, Path(__file__),
    )}
    return dict(
        state="whole_chip_autonomous_trained_feedforward_and_writeback_independently_verified",
        variant=variant,
        **scored,
        exact_reference_checkpoints=len(actual[3]),
        simulated_end_ns=actual[0],
        native_timing_checks_enabled=False,
        scope="Mapped functional Xcelium replay on two trained feed-forward tokens. Results and memory traffic "
              "match the guarded predecessor with its externally driven residual lease. Full-model accuracy, "
              "extracted timing and routed performance have separate checks.",
        evidence_sha256={name: digest for name, digest in evidence.items() if name in keep},
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("variant", choices=VARIANTS)
    parser.add_argument("--preflight", action="store_true")
    arguments = parser.parse_args()
    print(json.dumps(verify(arguments.variant, preflight=arguments.preflight), indent=2, sort_keys=True))
