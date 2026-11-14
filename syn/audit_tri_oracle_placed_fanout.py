"""Measure pin-only load violations without running early global estimation."""

import argparse
import csv
from decimal import Decimal
from hashlib import file_digest
import json
import os
from pathlib import Path
import subprocess
import time

from tri_oracle_artifact_fingerprint import artifact_fingerprint
from tri_oracle_process_guard import terminate_process_group


GIB = 1024**3
ROOT = Path.cwd()
TOOL = "/opt/cadence/INNOVUS251/bin/innovus"
RECIPE = ROOT / "syn/tri_oracle_report_placed_fanout.tcl"


def sha(path):
    with Path(path).open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def memory():
    with Path("/proc/meminfo").open() as source:
        available = next(int(row.split()[1]) * 1024 for row in source if row.startswith("MemAvailable:"))
    with Path("/sys/fs/cgroup/memory.stat").open() as source:
        anonymous = next(int(row.split()[1]) for row in source if row.startswith("anon "))
    return available, anonymous


def summarize(table, threshold):
    entries = []
    seen = set()
    eligible = complete = 0
    with table.open() as stream:
        for row in csv.DictReader(stream, delimiter="\t"):
            pin_load, limit = Decimal(row["pin_load_pf"]), Decimal(row["limit_pf"])
            count, missing = int(row["loads"]), int(row["missing_sink_caps"])
            assert row["net"] not in seen and count >= threshold and 0 <= missing <= count
            assert pin_load.is_finite() and limit.is_finite() and pin_load >= 0 and limit > 0
            seen.add(row["net"])
            eligible += 1
            complete += missing == 0
            if pin_load > limit:
                # Even where a sink lacks a model, the known load is a lower bound.
                entries.append(dict(row, ratio=float(pin_load / limit)))
    return dict(nets_with_pin_limits=eligible, nets_with_complete_pin_loads=complete,
                nets_over_limit_from_known_pin_loads=len(entries),
                worst=sorted(entries, key=lambda row: (-row["ratio"], row["net"]))[:8])


def run(placement, output, threshold):
    assert __debug__ and Path("/.dockerenv").is_file() and os.environ.get("CDS_LIC_FILE")
    assert output.is_relative_to(ROOT / ".cache") and threshold >= 64
    receipt = placement / "receipt.json"
    proof = json.loads(receipt.read_text())
    assert proof["state"] == "concurrent_chip_placed_and_cold_verified"
    checkpoint = placement / "place/placed.db"
    fingerprint = artifact_fingerprint(checkpoint)
    assert fingerprint == proof["placed_database"]
    netlist = placement / "place/placed.v"
    digest = sha(netlist)
    assert digest == proof["input_sha256"][str(netlist)]
    available, anonymous = memory()
    assert available >= 16 * GIB and anonymous < 3 * GIB
    output.mkdir()
    stem = output / "innovus"
    console = output / "console.log"
    env = os.environ | {"TRI_ORACLE_FANOUT_CHECKPOINT": str(checkpoint),
                        "TRI_ORACLE_FANOUT_THRESHOLD": str(threshold)}
    argv = ["/usr/bin/prlimit", f"--as={22 * GIB}", "--", TOOL, "-stylus", "-no_gui", "-batch",
            "-log", str(stem), "-files", str(RECIPE)]
    peak = anonymous
    minimum = available
    start = time.monotonic()
    with console.open("x") as stream:
        worker = subprocess.Popen(argv, cwd=output, env=env, stdout=stream, stderr=subprocess.STDOUT,
                                  stdin=subprocess.DEVNULL, start_new_session=True)
        print(f"PLACED_FANOUT_STARTED {worker.pid}", flush=True)
        try:
            while worker.poll() is None:
                available, anonymous = memory()
                minimum, peak = min(minimum, available), max(peak, anonymous)
                if available < 5 * GIB or anonymous >= 15 * GIB or time.monotonic() - start > 600:
                    raise RuntimeError(f"Fanout diagnostic resource guard: {minimum}, {peak}")
                time.sleep(0.5)
        finally:
            terminate_process_group(worker, log_argument=str(stem))
    assert worker.returncode == 0, worker.returncode
    log = console.read_text()
    assert "Started Early Global Route" not in log and "PreRoute RC Extraction DONE" not in log
    assert "**ERROR" not in log and "No more memory" not in log
    table = output / "placed_fanout.tsv"
    facts = summarize(table, threshold)
    marker = f"TRI_ORACLE_PLACED_FANOUT_DONE {facts['nets_with_pin_limits']}"
    assert log.splitlines().count(marker) == 1 and facts["nets_with_complete_pin_loads"] > 0
    candidates, = (int(line.split()[-1]) for line in log.splitlines() if line.startswith("TRI_ORACLE_FANOUT_CANDIDATES "))
    assert candidates >= facts["nets_with_pin_limits"]
    assert artifact_fingerprint(checkpoint) == fingerprint and sha(netlist) == digest
    evidence = {str(path.relative_to(ROOT)): sha(path) for path in (netlist, receipt, RECIPE, table, console,
                                                                   Path(__file__).resolve())}
    report = dict(state="whole_chip_placed_pin_load_screen_measured", placed_netlist_sha256=digest,
                  slow_corner="setup_slow", load_threshold=threshold, high_fanout_candidates=candidates,
                  peak_container_anonymous_bytes=peak, minimum_host_available_bytes=minimum,
                  evidence_sha256=evidence, **facts,
                  scope="Single-driver data nets at or above the load threshold. Sums use modeled sink pin values. "
                        "Wire load, slew and path slack remain unmeasured. This diagnostic cannot release routing.")
    with (output / "receipt.json").open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(f"PLACED_FANOUT_VERIFIED {facts['nets_with_pin_limits']} {facts['nets_over_limit_from_known_pin_loads']}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("placement", type=lambda path: Path(path).resolve())
    parser.add_argument("output", type=lambda path: Path(path).resolve())
    parser.add_argument("--threshold", type=int, default=128)
    run(**vars(parser.parse_args()))
