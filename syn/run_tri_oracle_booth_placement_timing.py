"""Run the three repaired-placement timing estimates one at a time in Innovus."""

import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from audit_tri_oracle_placed_fanout import GIB, TOOL, memory
from tri_oracle_artifact_fingerprint import artifact_fingerprint
from tri_oracle_process_guard import terminate_process_group
from verify_tri_oracle_booth_placement_timing import DRIVER, PLACEMENT, ROOT, TOP, VIEWS, digest, read

LOCK = ROOT / ".cache/physical/carry_lookahead_comparison/placed_drive_strength/native_lane.lock"
START_AVAILABLE = 20 * GIB
START_ANONYMOUS = 5 * GIB
START_DISK = 11 * GIB


def ready(output):
    available, anonymous = memory()
    return (available >= START_AVAILABLE and anonymous <= START_ANONYMOUS and
            shutil.disk_usage(output).free >= START_DISK)


def measure(output, database, view):
    folder = output / view
    folder.mkdir()
    stem = str(folder / "innovus")
    command = ["/usr/bin/prlimit", f"--as={28 * GIB}", "--", TOOL, "-stylus",
               "-no_gui", "-batch", "-log", stem, "-files", str(ROOT / DRIVER)]
    env = os.environ | {"TRI_ORACLE_BOOTH_TIMING_DATABASE": str(database),
                        "TRI_ORACLE_BOOTH_TIMING_TOP": TOP, "TRI_ORACLE_BOOTH_TIMING_VIEW": view}
    start = time.monotonic()
    lowest, peak = memory()
    stop_reason = None
    log = folder / "console.log"
    with log.open("x") as stream:
        child = subprocess.Popen(command, cwd=folder, env=env, stdin=subprocess.DEVNULL,
                                 stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        print("BOOTH_TIMING_VIEW_STARTED", view, child.pid, flush=True)
        try:
            while child.poll() is None:
                available, anonymous = memory()
                lowest, peak = min(lowest, available), max(peak, anonymous)
                if available < 5 * GIB or anonymous >= 20 * GIB:
                    stop_reason = f"Memory reserve reached: {available} available, {anonymous} anonymous"
                elif shutil.disk_usage(folder).free < 7 * GIB:
                    stop_reason = "Disk reserve reached"
                elif time.monotonic() - start >= 900:
                    stop_reason = "Timing view exceeded 900 seconds"
                if stop_reason:
                    break
                time.sleep(0.5)
        finally:
            terminate_process_group(child, log_argument=stem)
    result = {
        "exit_status": child.returncode,
        "stop_reason": stop_reason,
        "wall_seconds": time.monotonic() - start,
        "minimum_host_available_bytes": lowest,
        "peak_container_anonymous_bytes": peak,
    }
    (folder / "status.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print("BOOTH_TIMING_VIEW_TERMINAL", view, result, flush=True)
    assert result["exit_status"] == 0 and stop_reason is None, result
    assert f"BOOTH_PLACEMENT_TIMING_PASS {view}" in log.read_text().splitlines()


def run():
    assert __debug__ and Path.cwd() == ROOT and Path("/.dockerenv").exists()
    placement = read(PLACEMENT)
    assert placement["state"] == "corrected_buffer_repair_placement_and_cold_reload_verified"
    database = ROOT / placement["database"]
    output = database.parents[1] / "timing_three_views"
    plan = read(output / "prepared_timing.json")
    assert Path(plan["database"]) == database and tuple(plan["views"]) == VIEWS
    assert plan["database_fingerprint_sha256"] == placement["database_fingerprint_sha256"]
    assert plan["driver_sha256"] == digest(DRIVER) and plan["runner_sha256"] == digest(Path(__file__))
    deadline = time.monotonic() + 48 * 3600
    print("BOOTH_TIMING_THREE_VIEW_WAIT", memory(), "available_floor", START_AVAILABLE, flush=True)
    while time.monotonic() < deadline:
        if ready(output):
            with LOCK.open("r") as lane:
                try:
                    fcntl.flock(lane, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    pass
                else:
                    for view in VIEWS:
                        limit = time.monotonic() + 180
                        while not ready(output):
                            assert time.monotonic() < limit, (view, memory())
                            time.sleep(5)
                        canonical = json.dumps(artifact_fingerprint(database), sort_keys=True,
                                               separators=(",", ":")).encode()
                        assert sha256(canonical).hexdigest() == plan["database_fingerprint_sha256"]
                        measure(output, database, view)
                    print("BOOTH_TIMING_THREE_VIEW_COMPLETE", flush=True)
                    return
        time.sleep(20)
    raise TimeoutError("The three timing views never had the required memory and exclusive tool lane")


if __name__ == "__main__":
    run()
