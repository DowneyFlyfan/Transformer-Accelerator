"""Resume a verified projection replay after another native job releases memory."""

from argparse import ArgumentParser
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

from audit_tri_oracle_placed_fanout import GIB, memory
from tri_oracle_process_guard import terminate_process_group
from verify_tri_oracle_booth_attention_checkpoint import (
    DRIVER, LOCK, NATIVE, ROOT, WORK, checkpoint_artifacts, checkpoint_prefix,
    digest, previous_recovery, restore_invocation, verify_stopped_log,
)

TARGET = ["docker", "exec", "-w", str(ROOT), "-e", f"PYTHONPATH={ROOT / 'syn'}", "tri-oracle-eda"]
RESERVE = 5 * GIB
START = 13 * GIB
# A saved slot has consumed about 1.4 GiB. Leave two slots' worth above the
# same reserve used to stop a running replay.
START_DISK = 12 * GIB
DISK_RESERVE = 9 * GIB


def load(path):
    return json.loads(path.read_text())


def write(path, data):
    with path.open("x") as out:
        json.dump(data, out, indent=2, sort_keys=True)
        out.write("\n")


def verify_recovery(folder):
    definition = load(folder / "prepared_recovery.json")
    parent = previous_recovery(folder, definition)
    if parent is not None:
        verify_stopped_log(parent / "resume_status.json", (parent / "resume.log").read_text(),
                           definition["source_status_sha256"])
    facts, prefix, _ = checkpoint_artifacts(parent)
    for key, value in facts.items():
        assert definition[key] == value, key
    assert (folder / "checkpoint_prefix.log").read_text() == prefix
    assert definition["restore"] == restore_invocation(
        load(NATIVE / "prepared_native.json"), facts, folder / "resume.log")
    assert definition["restore"]["driver_sha256"] == digest(DRIVER)
    return definition


def worker(folder):
    assert Path("/.dockerenv").exists()
    definition = load(folder / "prepared_recovery.json")
    restore = definition["restore"]
    log = folder / "resume.log"
    allowed, anonymous = memory()
    assert allowed >= START and anonymous <= 5 * GIB
    assert shutil.disk_usage(folder).free >= START_DISK
    low, peak = allowed, anonymous
    start = time.monotonic()
    stop_reason = None
    with (folder / "resume.console").open("x") as console:
        child = subprocess.Popen(restore["command"], env=os.environ | restore["environment"],
                                 cwd=NATIVE, stdin=subprocess.DEVNULL, stdout=console,
                                 stderr=subprocess.STDOUT, start_new_session=True)
        print(f"BOOTH_RESTORE_STARTED {child.pid} {definition['snapshot']}", flush=True)
        try:
            while child.poll() is None:
                available, anonymous = memory()
                low, peak = min(low, available), max(peak, anonymous)
                if available < RESERVE or anonymous >= 20 * GIB:
                    stop_reason = "Memory reserve reached"
                elif shutil.disk_usage(folder).free < DISK_RESERVE:
                    stop_reason = "Disk reserve reached"
                elif time.monotonic() - start >= 72 * 3600:
                    stop_reason = "72-hour runtime limit reached"
                if stop_reason:
                    break
                time.sleep(2)
        finally:
            terminate_process_group(child, log_argument=str(log))
    result = {
        "exit_status": child.returncode, "stop_reason": stop_reason,
        "log_sha256": digest(log) if log.is_file() else None,
        "minimum_host_available_bytes": low, "peak_container_anonymous_bytes": peak,
        "wall_seconds": time.monotonic() - start,
    }
    write(folder / "resume_status.json", result)
    print("BOOTH_RESTORE_TERMINAL", result, flush=True)
    return 0 if child.returncode == 0 and stop_reason is None else 1


def joined_transcript(folder, definition):
    original = (folder / "checkpoint_prefix.log").read_text()
    assert digest(folder / "checkpoint_prefix.log") == definition["replay_prefix_sha256"]
    log = folder / "resume.log"
    status = load(folder / "resume_status.json")
    assert status["exit_status"] == 0 and status["stop_reason"] is None
    assert digest(log) == status["log_sha256"]
    resumed = log.read_text()
    assert not re.search(r"\*[EF],", resumed)
    assert f"Loading snapshot {definition['snapshot']}" in resumed
    saved_index = definition["checkpoint_count"] - 1
    assert re.findall(r"(?m)^TRI_UNSEEDED_PACKET_RESTORE (\d+)$", resumed) == [str(saved_index)]
    assert len(re.findall(r"(?m)^Simulation complete via \$finish\(1\) at time ", resumed)) == 1
    full = original + resumed
    checkpoint_prefix(full)
    transcript = folder / "combined.log"
    with transcript.open("x") as out:
        out.write(full)
    status_path = folder / "combined_status.json"
    write(status_path, status | {"log_sha256": digest(transcript), "resume_log_sha256": status["log_sha256"]})
    return transcript, status_path


def supervise(folder, after_status):
    definition = verify_recovery(folder)
    if after_status is not None:
        print(f"BOOTH_RESTORE_WAITING_FOR_NATIVE_RECEIPT {after_status}", flush=True)
        while not after_status.is_file():
            time.sleep(15)
        receipt = load(after_status)
        assert type(receipt["exit_status"]) is int
        print(f"BOOTH_RESTORE_OTHER_JOB_TERMINAL status={receipt['exit_status']}", flush=True)
    print("BOOTH_RESTORE_WAITING_FOR_PLACEMENT_LANE", flush=True)
    deadline = time.monotonic() + 72 * 3600
    while time.monotonic() < deadline:
        with LOCK.open("r") as lane:
            try:
                fcntl.flock(lane, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                pass
            else:
                probe = subprocess.check_output(TARGET + [
                    "python3", "-B", "-c",
                    "from audit_tri_oracle_placed_fanout import memory; print(*memory())"], text=True)
                available, anonymous = map(int, probe.split())
                if available >= START and anonymous <= 5 * GIB and shutil.disk_usage(folder).free >= START_DISK:
                    subprocess.run(TARGET + ["python3", "-B", str(Path(__file__).resolve()),
                                              "--worker", str(folder)], check=True)
                    import sys

                    sys.path.insert(0, str(WORK))
                    from verify_native import verify
                    transcript, status = joined_transcript(folder, definition)
                    write(folder / "verified.json", verify(NATIVE, transcript=transcript, status_path=status))
                    print("BOOTH_RESTORE_VERIFIED", flush=True)
                    return
        time.sleep(20)
    raise TimeoutError("Xcelium restore waited for its execution lane for 72 hours")


def main():
    parser = ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--preflight", type=Path)
    modes.add_argument("--resume", type=Path)
    modes.add_argument("--worker", type=Path)
    parser.add_argument("--after-status", type=Path)
    args = parser.parse_args()
    if args.worker:
        return worker(args.worker)
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    if args.preflight is not None:
        print(json.dumps(verify_recovery(args.preflight.resolve()), indent=2, sort_keys=True))
    else:
        supervise(args.resume.resolve(), args.after_status)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
