"""Verify the trained streaming workload on the repaired mapped chip."""

import json
from pathlib import Path
import re

from prepare_tri_oracle_booth_streaming_packet import PLACEMENT, REFERENCE, ROOT, digest


def load(path):
    return json.loads(path.read_text())


def verify_outputs(reference, fixture, transcript, output):
    assert not re.search(r"\*[EF],", transcript)
    assert transcript.count("Simulation complete via $finish(1)") == 1
    measured = re.findall(r"(?m)^STREAMING_MERGE_FRAME_PASS layer=(\d+) maps=(\d+) vectors=(\d+)$",
                          transcript)
    signs = reference["sign_vectors_per_layer"]
    assert len(measured) == len(signs) == 11
    for layer, (frame, entries, vectors) in enumerate(measured):
        assert int(frame) == layer and int(entries) == 576
        assert int(vectors) in (signs[layer], signs[layer] + 1)
    assert re.findall(r"(?m)^HOST_CONTROL_RELOCATED_PASS .* restored_words=(\d+)$", transcript) == ["90"]
    head = reference["prediction"]
    expected = (reference["head"] << 37) | (head["inner"] << 19) | (head["recent"] << 1) | int(head["streaming"])
    assert re.findall(r"(?m)^HOST_CONTROL_HEAD_PASS prediction=([0-9a-f]{12})$", transcript) == [f"{expected:012x}"]

    wanted = [int(line, 16) for line in (fixture / "value_order.hex").read_text().splitlines()]
    observed = [tuple(map(int, pair)) for pair in re.findall(
        r"(?m)^STREAMING_VALUE_READ index=(\d+) rank=(\d+)$", transcript)]
    assert observed == list(enumerate(wanted)) and len(observed) == 128
    rows = reference["output_rows"]
    results = [tuple(map(int, pair)) for pair in re.findall(
        r"(?m)^PACKET_ATTENTION_ROW_PASS rank=(\d+) value_reads=(\d+) at ", transcript)]
    assert results == [(row["rank"], row["selected_keys"]) for row in rows]
    expected_rows = [line.split()[-1] for line in (fixture / "rows.txt").read_text().splitlines()[1:]]
    assert output.splitlines() == expected_rows and len(expected_rows) == len(rows) == 2
    assert re.search(r"(?m)^COLD_PACKET_ATTENTION_PASS rows=2 host_words=319 maps=6336 "
                     r"context_words=990 reads=\d+ value_reads=128 wide=\d+ auxiliary=\d+$", transcript)
    return {
        "token_merge_maps": len(measured) * 576,
        "restored_context_words": 90,
        "external_value_requests": len(observed),
        "exact_output_values": sum(len(word) // 8 for word in expected_rows),
    }


def verify():
    reference = load(REFERENCE)
    placement = load(PLACEMENT)
    native = Path(placement["database"]).parents[1] / "streaming_packet"
    plan_file = native / "prepared.json"
    plan = load(plan_file)
    fixture = Path(plan["testbench_fixture"])
    assert plan["cold_netlist_sha256"] == reference["cold_netlist_sha256"]
    for filename, checksum in (plan["evidence_sha256"] | reference["evidence_sha256"]).items():
        assert digest(ROOT / filename) == checksum, filename
    native_status = native / "native_status.json"
    status = load(native_status)
    assert status["exit_status"] == 0 and status["stop_reason"] is None
    log, output = native / "xrun.log", native / "attention.hex"
    transcript = log.read_text()
    assert str(ROOT / (native / "bundle.sv")) in transcript and str(ROOT / fixture) in transcript
    results = verify_outputs(reference, fixture, transcript, output.read_text())
    paths = (REFERENCE, PLACEMENT, plan_file, native_status, log, output, Path(__file__).resolve().relative_to(ROOT))
    return {
        "state": "repaired_booth_trained_streaming_rows_verified_through_physical_ports",
        "scope": "Eleven live token-merge frames followed by head prediction and attention with externally supplied projections.",
        "cold_netlist_sha256": plan["cold_netlist_sha256"],
        "layer": reference["layer"],
        "head": reference["head"],
        "prediction": reference["prediction"],
        "output_rows": reference["output_rows"],
        "native": status,
        **results,
        "evidence_sha256": {str(path): digest(path) for path in paths},
    }


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    print(json.dumps(verify(), indent=2, sort_keys=True))
