"""Check all observed physical cache writes and the native tool receipt on the host."""
import json
from pathlib import Path
import re
import shlex

from prepare_tri_oracle_booth_packet_replay import (
    PEER, ROOT, WORK as ATTENTION, digest, include, replace_once,
)


WORK = ROOT / ATTENTION.parent / "projection_replay"
TEMPLATE = ROOT / "verilog/tri_oracle_booth_packet_projection_tb.svh"


def load(path):
    return json.loads(path.read_text())


def verify_compiled_sources(setup):
    previous = ROOT / ATTENTION
    prepared = load(previous / "prepared.json")
    assert setup["cold_netlist_sha256"] == prepared["netlist_sha256"]
    physical_peer = PEER.read_text()
    for module in (
        "tri_oracle_flit_to_pads", "tri_oracle_flit_from_pads", "tri_oracle_credit_bypass_fifo",
    ):
        physical_peer = physical_peer.replace(module, "tb_" + module)
    expected = replace_once(TEMPLATE.read_text(), "  // PHYSICAL_PORT_PEER", physical_peer.rstrip())
    actual = (WORK / "projection_tb.sv").read_text()
    # The published template formats the stimulus blocks with indentation.
    assert [line.strip() for line in actual.splitlines()] == [
        line.strip() for line in expected.splitlines()
    ]
    base_bundle = previous / "bundle.sv"
    assert digest(base_bundle) == prepared["evidence_sha256"][str(base_bundle.relative_to(ROOT))]
    expected_bundle = replace_once(
        base_bundle.read_text(), include(previous / "attention_tb.sv"), include(WORK / "projection_tb.sv")
    )
    assert (WORK / "bundle.sv").read_text() == expected_bundle
    for source in map(Path, re.findall(r'(?m)^`include "([^"]+)"$', expected_bundle)):
        if source != WORK / "projection_tb.sv":
            assert digest(source) == prepared["evidence_sha256"][str(source.relative_to(ROOT))], source


def verify():
    setup = load(WORK / "prepared.json")
    assert setup["state"] == "trained_projection_bound_to_corrected_full_chip"
    expected_model = ROOT / "records/tri_oracle_trained_projection_gpu_reference.json"
    reference = load(expected_model)
    roundtrip = ROOT / "records/tri_oracle_corrected_booth_placement_roundtrip.json"
    placed = load(roundtrip)
    cold = WORK.parent / "cold/cold.v"
    cold_sha = digest(cold)
    assert cold_sha == placed["evidence_sha256"][str(cold.relative_to(ROOT))] == setup["cold_netlist_sha256"]
    assert digest(WORK / "bundle.sv") == setup["bundle_sha256"]
    assert digest(WORK / "projection_tb.sv") == setup["bench_sha256"]
    verify_compiled_sources(setup)
    fixture = ROOT / setup["testbench_fixture"]
    assert reference["state"] == "trained_projection_fixture_verified_with_independent_gpu_arithmetic"
    for name, expected in setup["fixture_sha256"].items():
        path = fixture / name
        assert digest(path) == expected == reference["evidence_sha256"][str(path.relative_to(ROOT))]
    expected_hex = (fixture / "expected.hex").read_text().splitlines()
    groups, slots = setup["cases"], setup["slots"]
    assert groups == [0, 32, 36] and slots == 16
    vectors = len(groups) * slots
    dump = WORK / "projection.hex"
    expected = [expected_hex[group * reference["retained_tokens"] + slot] for group in groups for slot in range(slots)]
    assert dump.read_text().splitlines() == expected

    status = load(WORK / "native_status.json")
    assert status["exit_status"] == 0 and status["stop_reason"] is None
    history = WORK / "xrun.history"
    invocation = next(line for line in reversed(history.read_text().splitlines()) if line.startswith("s"))
    arguments = shlex.split(invocation.split("):", 1)[1])
    assert arguments[0] == "xrun" and arguments[arguments.index("-top") + 1] == setup["testbench_top"]
    assert str(WORK / "bundle.sv") in arguments
    assert f"+FIXTURE={fixture}" in arguments and f"+DUMP={dump}" in arguments
    log = WORK / "xrun.log"
    text = log.read_text()
    assert text.count("Simulation complete via $finish(1)") == 1 and not re.search(r"\*[EF],", text)
    groups_started = re.findall(r"(?m)^BOOTH_PROJECTION_GROUP_STARTED group=(\d+)$", text)
    assert list(map(int, groups_started)) == groups
    groups_passed = re.findall(r"(?m)^BOOTH_PROJECTION_GROUP_PASS group=(\d+) vectors=(\d+)$", text)
    assert [tuple(map(int, match)) for match in groups_passed] == [(group, slots) for group in groups]
    (summary,) = re.findall(r"(?m)^COLD_PACKET_PROJECTION_PASS (.+)$", text)
    totals = {key: int(value) for key, value in (word.split("=") for word in summary.split())}
    assert totals["vectors"] == totals["acks"] == vectors
    assert totals["writes"] == vectors * 8
    assert totals["activation_words"] == vectors * 256
    assert totals["weight_words"] == len(groups) * 64 * 256
    assert totals["read_bursts"] > 0 and totals["stalls"] > 0
    (outgoing_bytes, response_count), = re.findall(
        r"(?m)^BOOTH_PROJECTION_PHYSICAL_LINK_PASS outgoing_bytes=(\d+) scalar_chunks=(\d+)$", text)
    assert int(outgoing_bytes) > 0
    assert int(response_count) == totals["activation_words"] + totals["weight_words"] + vectors
    evidence = (expected_model, roundtrip, WORK / "bundle.sv", WORK / "projection_tb.sv",
                WORK / "prepare.py", WORK / "prepared.json", WORK / "run.py", WORK / "native_status.json",
                history, log, dump, TEMPLATE, ROOT / PEER, Path(__file__).resolve())
    return {
        "state": "trained_query_key_value_projections_verified_on_corrected_physical_ports",
        "cold_netlist_sha256": cold_sha,
        "query_key_value_groups": groups,
        "first_retained_tokens_per_group": slots,
        "cache_bytes_matched": vectors * 64,
        "counts": totals,
        "outgoing_request_bytes": int(outgoing_bytes),
        "incoming_scalar_chunks": int(response_count),
        "native_wall_seconds": status["wall_seconds"],
        "scope": "Three trained projection groups sent via the chip's physical host and memory ports. All rotary inputs are host records. Data-level simulation on the verified placed export.",
        "evidence_sha256": {str(path.relative_to(ROOT)): digest(path) for path in evidence},
    }


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    print(json.dumps(verify(), indent=2, sort_keys=True))
