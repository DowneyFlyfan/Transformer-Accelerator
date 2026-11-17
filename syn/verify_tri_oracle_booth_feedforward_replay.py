"""Independently verify the terminal feed-forward replay from the host."""

import argparse
import json
from pathlib import Path
import re

from audit_tri_oracle_placed_chip_boundary import digest
from run_tri_oracle_booth_feedforward_replay import ROOT, TOP, verify_inputs


PROOF = ROOT / "records/tri_oracle_corrected_booth_feedforward_replay_preflight.json"
PLACEMENT = ROOT / "records/tri_oracle_corrected_booth_buffered_placement_roundtrip.json"
RESULT = re.compile(r"(?m)^FEEDFORWARD_PHYSICAL_PASS strips=512 outputs=4096 responses=1 cycles=(\d+)$")
MILESTONES = (
    "FEEDFORWARD_PHYSICAL_FIXTURES_LOADED",
    "FEEDFORWARD_PHYSICAL_PROJECTION_REQUESTS count=64",
    "FEEDFORWARD_PHYSICAL_ACTIVATIONS_COMMITTED bytes=4096",
    "FEEDFORWARD_PHYSICAL_INTERMEDIATES_COMMITTED bytes=11264",
    *(f"FEEDFORWARD_PHYSICAL_WRITEBACK_PROGRESS strips={count}" for count in range(32, 513, 32)),
)


def verify_native_result(transcript, expected, observed):
    if re.search(r"\*(?:E|F|SE),", transcript):
        raise ValueError("The native transcript contains an error")
    matches = list(RESULT.finditer(transcript))
    if len(matches) != 1 or int(matches[0][1]) <= 0:
        raise ValueError("Missing or duplicate native final inventory")
    result = matches[0]
    complete = list(re.finditer(r"(?m)^Simulation complete via \$finish\(1\) at time (.+)$", transcript))
    if len(complete) != 1 or complete[0].start() <= result.end():
        raise ValueError("The simulator did not finish after the final inventory")
    previous = -1
    for milestone in MILESTONES:
        marker = f"\n{milestone}\n"
        offset = transcript.find(marker)
        if offset <= previous or transcript.count(marker) != 1:
            raise ValueError(f"Missing, duplicate or out-of-order milestone: {milestone}")
        previous = offset
    if previous >= result.start():
        raise ValueError("The output checkpoints must precede the final inventory")
    packets = verify_packets(expected, observed, complete=True)
    return packets | {"cycles": int(result[1]), "simulator_finish_time": complete[0][1]}


def verify_packets(expected, observed, *, complete):
    expected_lines = expected.splitlines()
    observed_lines = observed.splitlines()
    if len(expected_lines) != 512 or not 0 < len(observed_lines) <= 512:
        raise ValueError("Invalid feed-forward writeback packet count")
    if complete and len(observed_lines) != 512:
        raise ValueError("Expected 512 captured physical writeback packets")
    for index, actual in enumerate(observed_lines):
        golden = expected_lines[index]
        if re.fullmatch(r"[0-9a-fA-F]{52}", actual) is None or actual.lower() != golden.lower():
            raise ValueError(f"Physical writeback mismatch at strip {index}")
    return {"physical_writeback_packets": len(observed_lines), "exact_writeback_values": 8 * len(observed_lines)}


def verify(work, archive):
    packets = verify_inputs(work, archive)
    proof = json.loads(PROOF.read_text())
    placement = json.loads(PLACEMENT.read_text())
    prepared = work / "prepared.json"
    cold = work.parent / "cold/cold.v"
    if (digest(prepared) != proof["evidence_sha256"][str(prepared.relative_to(ROOT))]
            or proof["cold_netlist_sha256"] != placement["evidence_sha256"][str(cold.relative_to(ROOT))]):
        raise ValueError("The replay is not bound to the verified repaired placement and preflight")
    status_path = work / "native_status.json"
    if not status_path.is_file():
        raise ValueError("The native replay has no terminal receipt yet")
    status = json.loads(status_path.read_text())
    if status["exit_status"] != 0 or status["stop_reason"] is not None:
        raise ValueError(f"Native worker did not complete: {status}")
    log = work / "xrun.log"
    transcript = log.read_text()
    arguments = (str(work / "bundle.sv"), f"-top {TOP}", f"+REPLAY={work}",
                 f"+ARCHIVE={archive}", f"+PACKETS={packets}")
    for argument in arguments:
        if f"\t{argument}\n" not in transcript:
            raise ValueError(f"Native invocation is missing {argument}")
    expected = work / "host_writeback.hex"
    observed = work / "observed_writeback.hex"
    result = verify_native_result(transcript, expected.read_text(), observed.read_text())
    paths = (PLACEMENT, PROOF, prepared, status_path, expected, observed, log, Path(__file__).resolve())
    return {
        "state": "repaired_booth_trained_feedforward_replayed_through_physical_ports",
        "scope": "Functional hardware replay of two trained layer 10 tokens with pad-level command, external memory "
                 "and writeback checks. The replay uses archived projection inputs.",
        "cold_netlist_sha256": proof["cold_netlist_sha256"],
        "positions": proof["positions"],
        "native": status,
        **result,
        "evidence_sha256": {str(path.relative_to(ROOT)): digest(path) for path in paths},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    args = parser.parse_args()
    if Path.cwd() != ROOT or Path("/.dockerenv").is_file():
        parser.error("Run the verifier from the project folder on the host")
    print(json.dumps(verify(args.work.resolve(), args.archive.resolve()), indent=2, sort_keys=True))
