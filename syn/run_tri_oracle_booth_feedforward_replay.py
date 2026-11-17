"""Run the trained feed-forward replay in the existing Cadence container."""

import argparse
import fcntl
import json
from pathlib import Path
import shutil
import subprocess
import time

from audit_tri_oracle_placed_chip_boundary import digest
from audit_tri_oracle_placed_fanout import GIB, memory
from tri_oracle_process_guard import terminate_process_group


ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / ".cache/physical/carry_lookahead_comparison/placed_drive_strength/native_lane.lock"
TOP = "tri_oracle_booth_feedforward_replay_tb"


def wait_for_resources(work):
    previous = None
    while True:
        available, anonymous = memory()
        disk = shutil.disk_usage(work).free
        if disk < 15 * GIB:
            reason = "less than 15 GiB free disk"
        elif available < 12 * GIB:
            reason = "less than 12 GiB available host memory"
        elif anonymous > 5 * GIB:
            reason = "more than 5 GiB container anonymous memory"
        else:
            return
        if reason != previous:
            print(f"FEEDFORWARD_PHYSICAL_WAIT {reason} available={available} anonymous={anonymous}", flush=True)
            previous = reason
        time.sleep(15)


def verify_inputs(work, archive):
    prepared = json.loads((work / "prepared.json").read_text())
    for name, expected in prepared["output_sha256"].items():
        if digest(work / name) != expected:
            raise ValueError(f"Changed replay artifact {name}")
    for name in ("learned/activation.hex", "fixture/intermediate.hex", "sign_reads.hex", "pair.bin", "down.bin"):
        if digest(archive / name) != prepared["input_sha256"][name]:
            raise ValueError(f"Changed archive input {name}")
    packets = ROOT / prepared["external_inputs"]["PACKETS"]
    cold = work.parent / "cold/cold.v"
    bench = ROOT / f"verilog/{TOP}.sv"
    paths = ((packets, prepared["input_sha256"]["PACKETS"]),
             (cold, prepared["cold_netlist_sha256"]),
             (bench, prepared["native_source_sha256"]["replay_testbench_sha256"]))
    for path, expected in paths:
        if digest(path) != expected:
            raise ValueError(f"Changed replay input {path}")
    return packets


def run(work, archive, packets):
    log = work / "xrun.log"
    argv = [
        "/usr/bin/prlimit", f"--as={10 * GIB}", "--", "/opt/cadence/bin/xrun",
        "-64bit", "-sv", "-nospecify", "-notimingchecks", "-sequdp_nba_delay", "-xmerror", "RECOME",
        "-top", TOP, "-incdir", str(work), "-l", str(log), str(work / "bundle.sv"),
        f"+REPLAY={work}", f"+ARCHIVE={archive}", f"+PACKETS={packets}",
    ]
    low, peak = memory()
    started = time.monotonic()
    reason = None
    with (work / "console.log").open("x") as output:
        worker = subprocess.Popen(argv, cwd=work, stdout=output, stderr=subprocess.STDOUT,
                                  stdin=subprocess.DEVNULL, start_new_session=True)
        print("FEEDFORWARD_PHYSICAL_STARTED", worker.pid, flush=True)
        try:
            while worker.poll() is None:
                available, anonymous = memory()
                low, peak = min(low, available), max(peak, anonymous)
                if available < 5 * GIB or anonymous >= 20 * GIB:
                    reason = "Host or container memory guard"
                elif shutil.disk_usage(work).free < 7 * GIB:
                    reason = "Disk space guard"
                elif time.monotonic() - started > 21600:
                    reason = "Six-hour native run budget"
                if reason:
                    break
                time.sleep(1)
        finally:
            terminate_process_group(worker, log_argument=log)
    receipt = {
        "exit_status": worker.returncode,
        "stop_reason": reason,
        "wall_seconds": time.monotonic() - started,
        "minimum_host_available_bytes": low,
        "peak_container_anonymous_bytes": peak,
    }
    (work / "native_status.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print("FEEDFORWARD_PHYSICAL_TERMINAL", receipt, flush=True)
    return worker.returncode


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()
    work, archive = args.work.resolve(), args.archive.resolve()
    if args.preflight:
        if Path("/.dockerenv").is_file():
            raise RuntimeError("Verify inputs from the project folder on the host")
        print(f"FEEDFORWARD_PHYSICAL_INPUTS_VERIFIED packets={verify_inputs(work, archive)}")
        raise SystemExit(0)
    if not Path("/.dockerenv").is_file():
        raise RuntimeError("Run the native worker with docker exec in the Cadence container")
    if (work / "console.log").exists():
        raise FileExistsError(work / "console.log")
    prepared = json.loads((work / "prepared.json").read_text())
    packets = ROOT / prepared["external_inputs"]["PACKETS"]
    reported_busy = False
    while True:
        wait_for_resources(work)
        with LOCK.open("r") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                busy = True
            else:
                busy = False
                available, anonymous = memory()
                if available >= 12 * GIB and anonymous <= 5 * GIB and shutil.disk_usage(work).free >= 15 * GIB:
                    raise SystemExit(run(work, archive, packets))
        if busy and not reported_busy:
            print("FEEDFORWARD_PHYSICAL_WAIT native execution lock held", flush=True)
        reported_busy = busy
        time.sleep(15)
