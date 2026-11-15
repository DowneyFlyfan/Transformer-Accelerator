"""Run and compare the indexed whole-chip replay using the native Cadence flow."""

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import shutil
import subprocess
import time

from audit_tri_oracle_placed_chip_boundary import digest
from audit_tri_oracle_placed_fanout import GIB, memory
from tri_oracle_process_guard import terminate_process_group


def read(path):
    return json.loads(path.read_text())


def validate_inputs(manifest):
    for name, expected in manifest["inputs"].items():
        assert digest(Path(name)) == expected, name


def await_raw(stage, candidate):
    deadline = time.monotonic() + 3600
    last_live = time.monotonic()
    marker = re.compile(r"(?m)^XSIM_STARTED pid=(\d+)$")
    while True:
        supervisor = (stage / "supervisor.log").read_text()
        pid, = marker.findall(supervisor)
        status = stage / "status.json"
        if status.is_file() and status.stat().st_size:
            assert read(status)["exit_status"] == 0, status
        verified = stage / "verified.json"
        if verified.is_file() and verified.stat().st_size:
            proof = read(verified)
            assert proof["candidate_sha256"] == candidate and proof["exit_status"] == 0
            assert proof["baseline_checkpoint_and_transaction_trace_equal"]
            assert proof["exact_feedforward_values"] == proof["exact_writeback_values"] == 4096
            return proof
        worker = Path("/proc") / pid
        try:
            live = (worker / "cwd").readlink() == stage and (
                worker / "comm"
            ).read_text().strip() in {"xrun", "xmelab", "xmsim"}
        except FileNotFoundError:
            live = False
        now = time.monotonic()
        if live:
            last_live = now
        if now - last_live > 60 or now >= deadline:
            raise RuntimeError("Raw replay ended without a verified result")
        time.sleep(5)


def await_memory():
    deadline = time.monotonic() + 600
    while True:
        available, anonymous = memory()
        if available >= 14 * GIB and anonymous < 6 * GIB:
            return available, anonymous
        if time.monotonic() >= deadline:
            raise RuntimeError(f"Memory headroom unavailable: {available} host bytes, {anonymous} anonymous bytes")
        time.sleep(5)


def run_xcelium(stage, args):
    low, peak = await_memory()
    assert shutil.disk_usage(stage).free > 12 * GIB
    start = time.monotonic()
    with (stage / "console.log").open("x") as console:
        worker = subprocess.Popen(args, cwd=stage, stdout=console, stderr=subprocess.STDOUT,
                                  stdin=subprocess.DEVNULL, start_new_session=True)
        print(f"INDEXED_XSIM_STARTED pid={worker.pid}", flush=True)
        try:
            while worker.poll() is None:
                available, anonymous = memory()
                low, peak = min(low, available), max(peak, anonymous)
                assert available > 5 * GIB and anonymous < 15.5 * GIB, (available, anonymous)
                assert shutil.disk_usage(stage).free > 5 * GIB
                assert time.monotonic() - start < 3600
                time.sleep(1)
        finally:
            terminate_process_group(worker, log_argument=str(stage / "xrun.log"))
    return {"exit_status": worker.returncode, "wall_seconds": time.monotonic() - start,
            "minimum_host_available_bytes": low, "peak_container_anonymous_bytes": peak}


def checkpoints(path):
    return [re.sub(r" cycle=\d+$", "", line) for line in path.read_text().splitlines()]


def traffic(log):
    marker, = re.findall(
        r"(?m)^PACKED_DECODER_PASS packed=1 trained=1 outputs=4096 wide_bursts=(\d+) "
        r"wide_beats=(\d+) scalar_down_beats=0 cycles=(\d+)$", log
    )
    bursts, beats, cycles = map(int, marker)
    return {"weight_requests": bursts, "weight_response_beats": beats, "cycles": cycles}


def verify(stage, reference, proof, native):
    assert native["exit_status"] == 0
    log = (stage / "xrun.log").read_text()
    raw = (reference / "xrun.log").read_text()
    assert not re.search(r"\*[EF],", log)
    assert log.count("Simulation complete via $finish(1)") == 1
    assert log.count("\nUNIFIED_CHIP_FEEDFORWARD_PASS descriptor_words=16 commands=1 responses=1\n") == 1
    markers = (
        "DIRECT_PROJECTION_ACTIVATION_PASS packets=64 strips=512 bytes=4096 writeback_reads=512",
        "LIVE_MAPPED_FEEDFORWARD_WRITEBACK_PASS strips=512 values=4096",
        "AUTONOMOUS_RESIDUAL_LEASE_PASS override=0 released=1",
    )
    assert all(log.count("\n" + marker + "\n") == 1 for marker in markers)
    assert re.search(r"(?m)^BATCH408_PASS tokens=2 hidden=2048 intermediate=5632 outputs=2048 exact_outputs=4096 "
                     r".* fault=0 trained=1$", log)
    assert checkpoints(stage / "progress.log") == checkpoints(reference / "progress.log")
    count = len(checkpoints(stage / "progress.log"))
    assert count == 90
    census = r"(?m)^TRI_ORACLE_MAPPED_CENSUS .+$"
    paths = re.findall(census, log)
    assert len(paths) == 631 and Counter(paths) == Counter(re.findall(census, raw))
    rows = re.findall(
        r"(?m)^INDEXED_NATIVE_READS lane=([01]) pair_index=(\d+) pair_payload=(\d+) down_index=(\d+) down_payload=(\d+)$",
        log
    )
    assert [int(row[0]) for row in rows] == [0, 1]
    indexed = traffic(log)
    raw_traffic = traffic(raw)
    lanes = [dict(zip(("pair_index", "pair_payload", "down_index", "down_payload"),
                      map(int, row[1:]), strict=True)) for row in rows]
    assert all(min(lane.values()) > 0 for lane in lanes)
    assert sum(sum(lane.values()) for lane in lanes) == indexed["weight_response_beats"]
    return {
        "state": "native_indexed_trained_feedforward_and_writeback_verified",
        "candidate_sha256": proof["candidate_sha256"],
        "functional_checkpoints": count,
        "compiled_memory_paths": len(paths),
        "exact_feedforward_outputs": 4096,
        "exact_writeback_outputs": 4096,
        "raw": raw_traffic,
        "indexed": indexed,
        "indexed_response_beats_by_lane": lanes,
        "native": native,
        "transcript_sha256": {
            str(p): digest(p)
            for p in (stage / "xrun.log", stage / "progress.log",
                      reference / "xrun.log", reference / "progress.log", reference / "verified.json")
        },
    }


def main():
    assert __debug__ and Path("/.dockerenv").is_file()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", type=Path)
    args = parser.parse_args()
    stage = args.stage.resolve()
    manifest = read(stage / "inputs.json")
    validate_inputs(manifest)
    raw = Path(manifest["raw_replay_stage"])
    print(f"INDEXED_WAITING_FOR_RAW {raw}", flush=True)
    proof = await_raw(raw, manifest["candidate_sha256"])
    print("INDEXED_RAW_REFERENCE_VERIFIED", flush=True)
    native = run_xcelium(stage, manifest["args"])
    (stage / "status.json").write_text(json.dumps(native, indent=2, sort_keys=True) + "\n")
    validate_inputs(manifest)
    result = verify(stage, raw, proof, native)
    with (stage / "verified.json").open("x") as receipt:
        json.dump(result, receipt, sort_keys=True, indent=2)
        receipt.write("\n")
    print(result, flush=True)


if __name__ == "__main__":
    main()
