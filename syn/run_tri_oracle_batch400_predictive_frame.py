"""Qualify the joined raw-residual predictor and compute fabric in Xcelium."""

from concurrent.futures import ThreadPoolExecutor
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time

from prepare_tri_oracle_batch400_bench import hierarchy_bench, integrated_bench
from run_tri_oracle_batch396_masks import GIB, check_memory, sha256
from tri_oracle_process_guard import terminate_process_group


ROOT = Path(__file__).resolve().parents[1]
TOP = "tri_oracle_batched400_predictive_tb"


def main(batch="400"):
    assert batch in ("400", "401")
    backend_path = ROOT / "records/batch393_literal_result.json"
    frontend_path = ROOT / "records/batch399_mask_packet_result.json"
    backend = json.loads(backend_path.read_text())
    frontend = json.loads(frontend_path.read_text())
    assert backend["state"] == "literal_joined_feedforward_and_six_recoveries_passed"
    assert frontend["state"] == "trained_predictor_to_keep_packets_verified"
    prior_sources = backend["source_sha256"] | frontend["source_sha256"]
    sources = [Path(path) for path in backend["source_sha256"]
               if path.endswith((".sv", ".v")) and not path.endswith(("_tb.sv", "_hierarchy.sv"))]
    sources.extend(ROOT / "verilog" / (name + ".sv") for name in (
        "tri_oracle_rmsnorm", "tri_oracle_sign_fetch", "tri_oracle_strip_predictor", "tri_oracle_batched_outliers398",
        "tri_oracle_batched_mask_packet399", "tri_oracle_batched_predictive400",
    ))
    tracked = [
        ROOT / "verilog/tri_oracle_batched393_tb.sv", ROOT / "verilog/tri_oracle_batch357_hierarchy.sv",
        ROOT / "syn/prepare_tri_oracle_batch400_bench.py", ROOT / "syn/run_tri_oracle_batch396_masks.py",
        ROOT / "syn/tri_oracle_process_guard.py", backend_path, frontend_path, Path(__file__), *sources,
    ]
    hashes = {str(path): sha256(path) for path in tracked}
    assert all(prior_sources[path] == digest for path, digest in hashes.items() if path in prior_sources)
    check_memory(14 * GIB)
    directory = ROOT / f".cache/physical/simulation/batch{batch}_predictive"
    output = ROOT / f"records/batch{batch}_predictive_result.json"
    archive = ROOT / f"records/batch{batch}_native_logs.json.gz"
    assert not directory.exists() and not output.exists() and not archive.exists()
    directory.mkdir()
    bench_text, hierarchy_text = integrated_bench(), hierarchy_bench()
    stopped = False
    began = time.monotonic()

    def stop(_number, _frame):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    def run(fault):
        channels = 192 if fault in (1, 5, 7, 11) else 96
        log = directory / f"fault{fault}.log"
        started = time.monotonic()
        assert not stopped
        with tempfile.TemporaryDirectory(prefix=f"fault{fault}_", dir=directory) as folder:
            work = Path(folder)
            bench = work / "bench.sv"
            hierarchy = work / "hierarchy.sv"
            bundle = work / "bundle.sv"
            bench.write_text(bench_text)
            hierarchy.write_text(hierarchy_text)
            bundle.write_text('`define UNIT_DELAY\n`define TRI_ORACLE_SRAM_CLUSTER_BIND_PUBLIC\n' +
                              "".join(f'`include "{path}"\n' for path in (*sources, bench, hierarchy)))
            command = [
                "taskset", "-c", str(8 + fault), "/opt/cadence/bin/xrun", "-64bit", "-sv",
                "-xmerror", "RECOME", "-notimingchecks", "-top", TOP, "-top", "tri_oracle_batch357_hierarchy",
                "-xmlibdirname", str(work / "xcelium.d"), "-l", str(work / "native.log"),
                "-history_file", str(work / "history"), "-defparam", f"{TOP}.FAULT={fault}",
                "-defparam", f"{TOP}.INTERMEDIATE={channels}", str(bundle),
            ]
            with log.open("x") as stream:
                child = subprocess.Popen(command, cwd=work, stdout=stream, stderr=subprocess.STDOUT,
                                         stdin=subprocess.DEVNULL, start_new_session=True)
                print(f"BATCH400_STARTED fault={fault} group={child.pid}", flush=True)
                try:
                    while child.poll() is None:
                        check_memory(8 * GIB)
                        assert not stopped and time.monotonic() - started < 240
                        time.sleep(0.5)
                    assert child.returncode == 0, f"Predictive frame failed: {log}"
                finally:
                    terminate_process_group(child)
        text = log.read_text()
        assert not re.search(r"\*(?:E|F),|\*ERROR|Simulation terminated via \$fatal", text)
        assert text.splitlines().count("BATCH357_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=602") == 1
        inv, = re.findall(r"^BATCH400_PASS (.+)$", text, re.MULTILINE)
        inventory = {name: int(value) for name, value in (part.split("=") for part in inv.split())}
        assert inventory["fault"] == fault and inventory["trained"] == 0
        assert (inventory["tokens"], inventory["hidden"], inventory["intermediate"], inventory["outputs"]) == (3, 64, channels, 173)
        assert (inventory["exact_outputs"], inventory["intermediate_bytes"], inventory["output_packets"]) == (519, 3 * channels, 6)
        bus_line, = re.findall(r"^BATCH400_SHARED_BUS (.+)$", text, re.MULTILINE)
        bus = {name: int(value) for name, value in (part.split("=") for part in bus_line.split())}
        assert bus["sign_requests"] == 12 * (channels // 32) and bus["valid_masks"] == (channels + 79) // 80
        assert channels != 192 or bus["contended_cycles"] > 0
        if fault:
            assert text.splitlines().count(f"BATCH400_FAULT_DRAINED fault={fault} output_prefix_packets={3 if fault == 3 else 0}") == 1
        print(f"BATCH400_VERIFIED_CASE fault={fault}", flush=True)
        return {
            "fault": fault, "native_exit_status": child.returncode, "process_group": child.pid,
            "inventory": inventory, "shared_bus": bus, "elapsed_seconds": time.monotonic() - started,
            "log": str(log), "log_sha256": sha256(log),
        }

    with ThreadPoolExecutor(max_workers=5) as pool:
        runs = list(pool.map(run, range(12)))
    assert all(sha256(Path(path)) == digest for path, digest in hashes.items())
    assert not any(path.is_dir() for path in directory.iterdir())
    logs = {Path(run["log"]).name: Path(run["log"]).read_text() for run in runs}
    assert "BATCH400_FAULT fault=4 sign_requests=1 valid_masks=0 abort_masks=0 writes=0" in logs["fault4.log"]
    for fault in (5, 6, 8, 9, 10):
        assert f"BATCH400_FAULT fault={fault} sign_requests=0 valid_masks=0 abort_masks=0 writes=0" in logs[f"fault{fault}.log"]
    assert re.search(r"^BATCH400_FAULT fault=7 sign_requests=\d+ valid_masks=1 abort_masks=1 writes=3$", logs["fault7.log"], re.MULTILINE)
    assert "BATCH400_HELD_SECOND_RETIRED_BEFORE_ABORT" in logs["fault11.log"]
    assert re.search(r"^BATCH400_FAULT fault=11 sign_requests=\d+ valid_masks=2 abort_masks=1 writes=6$", logs["fault11.log"], re.MULTILINE)
    with archive.open("xb") as stream:
        stream.write(gzip.compress(json.dumps(logs, sort_keys=True).encode(), mtime=0))
    assert json.loads(gzip.decompress(archive.read_bytes())) == logs
    report = {
        "state": "raw_residual_to_feedforward_source_and_recovery_verified",
        "batch": int(batch),
        "scope": __doc__,
        "elapsed_seconds": time.monotonic() - began,
        "supervisor_pid": os.getpid(),
        "source_sha256": hashes,
        "bench_sha256": hashlib.sha256(bench_text.encode()).hexdigest(),
        "hierarchy_bench_sha256": hashlib.sha256(hierarchy_text.encode()).hexdigest(),
        "actual_cores": 20,
        "actual_clusters": 5,
        "actual_vendor_memory_models": 602,
        "exact_outputs": sum(run["inventory"]["exact_outputs"] for run in runs),
        "intermediate_bytes_checked": sum(run["inventory"]["intermediate_bytes"] for run in runs),
        "runs": runs,
        "logs_archive_sha256": sha256(archive),
        "temporary_builds_removed": True,
        "trained_joined_frame_verified": False,
        "full_paper_results_matched": False,
    }
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"BATCH400_PREDICTIVE_VERIFIED exact_outputs={report['exact_outputs']} cases={len(runs)}", flush=True)


if __name__ == "__main__":
    main(*sys.argv[1:])
