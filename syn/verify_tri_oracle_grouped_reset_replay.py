"""Verify the trained layer-10 Xcelium replay on the reset-buffered netlist."""

import argparse
import json
from pathlib import Path
import re

from audit_tri_oracle_placed_chip_boundary import digest


ROOT = Path(__file__).resolve().parents[1]
GRAPH = ROOT / "records/tri_oracle_grouped_reset_graph.json"


def verify(run, fixture, candidate):
    receipt = run / "receipt.json"
    observed = json.loads(receipt.read_text())
    assert observed["state"] == "buffered_placed_netlist_trained_projection_replayed_in_xcelium"
    assert observed["native"]["xcelium_exit_status"] == 0
    assert all(digest(ROOT / path) == expected for path, expected in observed["evidence_sha256"].items())
    graph = json.loads(GRAPH.read_text())
    assert digest(candidate) == observed["buffered_netlist_sha256"] == graph["buffered_netlist_sha256"]
    reference = fixture / "native_attention_handoff"
    original_receipt = reference / "receipt.json"
    original = json.loads(original_receipt.read_text())
    assert original["state"] == "mapped_grouped_attention_to_output_projection_verified"
    assert original["candidate_sha256"] == observed["reference_netlist_sha256"]
    original_bundle = reference / "bundle.sv"
    original_log = reference / "replay/xrun.log"
    original_attention = reference / "legacy_attention.hex"
    original_projection = reference / "output.hex"
    expected_path = fixture / "expected.bin"
    for path in (original_bundle, original_log, original_attention, original_projection, expected_path):
        assert digest(path) == original["input_sha256"][str(path)], path
    source = original_bundle.read_text()
    path, = re.findall(r'(?m)^`include "([^"]+/linked_physical\.v)"$', source)
    assert digest(Path(path)) == observed["reference_netlist_sha256"]
    bundle = run / "bundle.sv"
    assert bundle.read_text() == source.replace(path, str(candidate))
    log = (run / "xrun.log").read_text()
    reference_log = original_log.read_text()
    assert f"file: {bundle}" in log and "-top tri_oracle_native_grouped_command_tb" in log
    assert "-nospecify" in log and "-notimingchecks" in log
    assert log.count("Simulation complete via $finish(1)") == 1
    assert not re.search(r"(?m)^\S+: \*[EF],", log)
    assert re.findall(r"(?m)^NATIVE_ATTENTION_PROJECTION_GROUP_PASS group=(\d+)$", log) == list(map(str, range(32)))
    schedules = re.findall(r"(?m)^TRAINED_OFFLOAD_RESULT_PASS (.+)$", log)
    assert len(schedules) == 3 and schedules == re.findall(r"(?m)^TRAINED_OFFLOAD_RESULT_PASS (.+)$", reference_log)
    assert "NATIVE_ATTENTION_PROJECTION_PASS heads=32 tokens=2 codes=4096 write_beats=512" in log.splitlines()
    macro = r"(?m)^TRI_ORACLE_MAPPED_CENSUS (.+)$"
    census = sorted(re.findall(macro, log))
    assert len(census) == len(set(census)) == 631 and census == sorted(re.findall(macro, reference_log))
    assert (run / "legacy_attention.hex").read_bytes() == original_attention.read_bytes()
    projection = run / "output.hex"
    assert projection.read_bytes() == original_projection.read_bytes()
    rows = projection.read_text().splitlines()
    assert len(rows) == 64 and all(re.fullmatch(r"[0-9a-f]{128}", row) for row in rows)
    assert b"".join(bytes.fromhex(row)[::-1] for row in rows) == expected_path.read_bytes()
    assert observed["output_codes"] == 4096 and observed["heads"] == 32 and observed["tokens"] == 2
    observed["trained_attention_schedules_with_identical_cycles_and_requests"] = 3
    observed["projection_write_beats"] = 512
    observed["evidence_sha256"].update({
        str(path.relative_to(ROOT)): digest(path)
        for path in (receipt, original_receipt, expected_path, Path(__file__).resolve())
    })
    return observed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("run", "fixture", "candidate"):
        parser.add_argument(name, type=lambda path: Path(path).absolute())
    print(json.dumps(verify(**vars(parser.parse_args())), sort_keys=True, indent=2))
