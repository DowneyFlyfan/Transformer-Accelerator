"""Verify learned activation writes consumed by the joined feedforward fabric."""

from concurrent.futures import ThreadPoolExecutor
import gzip
import hashlib
import json
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time

from prepare_tri_oracle_batch400_bench import hierarchy_bench
from prepare_tri_oracle_batch406_bench import learned_bench
from run_tri_oracle_batch396_masks import GIB, check_memory, sha256
from tri_oracle_process_guard import terminate_process_group


ROOT = Path(__file__).resolve().parents[1]
TOP = "tri_oracle_batched406_learned_tb"
FAULTS = (0, 1, 3, 4, 5, 7, 11, 12, 13, 14, 15, 16)


def source_files():
    backend_path = ROOT / "records/batch393_literal_result.json"
    coordinator_path = ROOT / "records/batch401_predictive_result.json"
    frontend_path = ROOT / "records/batch405_normalize_result.json"
    backend, coordinator, frontend = (
        json.loads(path.read_text()) for path in (backend_path, coordinator_path, frontend_path)
    )
    assert coordinator["state"] == "raw_residual_to_feedforward_source_and_recovery_verified"
    assert frontend["state"] == "shared_normalization_activation_writes_and_trained_masks_verified"
    sources = [Path(path) for path in backend["source_sha256"]
               if path.endswith((".sv", ".v")) and not path.endswith(("_tb.sv", "_hierarchy.sv"))]
    sources.extend(ROOT / "verilog" / (name + ".sv") for name in (
        "tri_oracle_rmsnorm", "tri_oracle_affine_quantizer", "tri_oracle_rms_activation",
        "tri_oracle_sign_fetch", "tri_oracle_strip_predictor", "tri_oracle_batched_outlier_replay404",
        "tri_oracle_batched_normalize405", "tri_oracle_batched_mask_packet399", "tri_oracle_batched_learned406",
    ))
    evidence = [
        backend_path, coordinator_path, frontend_path,
        ROOT / "verilog/tri_oracle_batched393_tb.sv", ROOT / "verilog/tri_oracle_batch357_hierarchy.sv",
        ROOT / "syn/prepare_tri_oracle_batch400_bench.py", ROOT / "syn/prepare_tri_oracle_batch406_bench.py",
        ROOT / "syn/run_tri_oracle_batch396_masks.py", ROOT / "syn/tri_oracle_process_guard.py",
    ]
    for path in (*sources, *evidence):
        for record in (backend, coordinator, frontend):
            expected = record["source_sha256"].get(str(path))
            if expected is not None:
                assert sha256(path) == expected, path
    return sources, evidence


def write_bundle(work, sources, bench_text, hierarchy_text):
    bench = work / "bench.sv"
    hierarchy = work / "hierarchy.sv"
    bundle = work / "bundle.sv"
    bench.write_text(bench_text)
    hierarchy.write_text(hierarchy_text)
    bundle.write_text('`define UNIT_DELAY\n`define TRI_ORACLE_SRAM_CLUSTER_BIND_PUBLIC\n' +
                      "".join(f'`include "{path}"\n' for path in (*sources, bench, hierarchy)))
    return bundle


def native_command(work, bundle, cpus, parameters):
    command = [
        "taskset", "-c", cpus, "/opt/cadence/bin/xrun", "-64bit", "-sv",
        "-xmerror", "RECOME", "-notimingchecks", "-top", TOP, "-top", "tri_oracle_batch357_hierarchy",
        "-xmlibdirname", str(work / "xcelium.d"), "-l", str(work / "native.log"),
        "-history_file", str(work / "history"),
    ]
    for key, value in parameters.items():
        command.extend(("-defparam", f"{TOP}.{key}={value}"))
    return command + [str(bundle)]


def main():
    sources, evidence = source_files()
    hashes = {str(path): sha256(path) for path in (*sources, *evidence, Path(__file__))}
    check_memory(14 * GIB)
    directory = ROOT / ".cache/physical/simulation/batch406_learned"
    output = ROOT / "records/batch406_learned_result.json"
    archive = ROOT / "records/batch406_native_logs.json.gz"
    assert not any(path.exists() for path in (directory, output, archive))
    directory.mkdir()
    bench_text, hierarchy_text = learned_bench(), hierarchy_bench()
    stopped = False
    began = time.monotonic()

    def stop(_number, _frame):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    def run(fault):
        hidden = 160 if fault in (12, 13, 16) else 64
        channels = 192 if fault in (1, 7, 11) else 96
        log = directory / f"fault{fault}.log"
        started = time.monotonic()
        assert not stopped
        with tempfile.TemporaryDirectory(prefix=f"fault{fault}_", dir=directory) as folder:
            work = Path(folder)
            bundle = write_bundle(work, sources, bench_text, hierarchy_text)
            command = native_command(work, bundle, str(8 + FAULTS.index(fault)), {
                "FAULT": fault, "HIDDEN": hidden, "INTERMEDIATE": channels,
            })
            with log.open("x") as stream:
                child = subprocess.Popen(command, cwd=work, stdout=stream, stderr=subprocess.STDOUT,
                                         stdin=subprocess.DEVNULL, start_new_session=True)
                print(f"BATCH406_STARTED fault={fault} group={child.pid}", flush=True)
                try:
                    while child.poll() is None:
                        check_memory(8 * GIB)
                        assert not stopped and time.monotonic() - started < 240, f"Xcelium timed out: {log}"
                        time.sleep(0.5)
                    assert child.returncode == 0, f"Learned frame failed: {log}"
                finally:
                    terminate_process_group(child)
        text = log.read_text()
        assert not re.search(r"\*(?:E|F),|\*ERROR|Simulation terminated via \$fatal", text)
        assert text.splitlines().count("BATCH357_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=602") == 1
        inv, = re.findall(r"^BATCH406_PASS (.+)$", text, re.MULTILINE)
        inventory = {name: int(value) for name, value in (part.split("=") for part in inv.split())}
        assert tuple(inventory[key] for key in ("tokens", "hidden", "intermediate", "outputs", "fault", "trained")) == (
            3, hidden, channels, 173, fault, 0)
        assert (inventory["exact_outputs"], inventory["intermediate_bytes"], inventory["output_packets"]) == (519, 3 * channels, 6)
        activation_bursts = 3 * ((hidden + 127) // 128)
        assert text.splitlines().count(
            f"BATCH406_ACTIVATION_PASS bytes={3 * hidden} bursts={activation_bursts} normalizations=3"
        ) == 1
        if fault:
            assert text.splitlines().count(f"BATCH406_FAULT_DRAINED fault={fault} output_prefix_packets={3 if fault == 3 else 0}") == 1
        expected_fault = {
            5: (0, 0), 12: (0, 1), 13: (448, 6), 14: (0, 0), 15: (0, 0), 16: (128, 1),
        }.get(fault)
        if expected_fault is not None:
            ack, requests = expected_fault
            assert text.splitlines().count(
                f"BATCH406_ACTIVATION_FAULT fault={fault} activation_acks={ack} activation_requests={requests} sign_reads=0"
            ) == 1
        if fault == 11:
            assert text.splitlines().count("BATCH406_HELD_SECOND_RETIRED_BEFORE_ABORT") == 1
        print(f"BATCH406_VERIFIED_CASE fault={fault}", flush=True)
        return {
            "fault": fault, "native_exit_status": child.returncode, "process_group": child.pid,
            "inventory": inventory, "activation_bytes": 3 * hidden, "activation_bursts": activation_bursts,
            "elapsed_seconds": time.monotonic() - started, "log": str(log), "log_sha256": sha256(log),
        }

    with ThreadPoolExecutor(max_workers=6) as pool:
        runs = list(pool.map(run, FAULTS))
    assert all(sha256(Path(path)) == digest for path, digest in hashes.items())
    assert not any(path.is_dir() for path in directory.iterdir())
    logs = {Path(run["log"]).name: Path(run["log"]).read_text() for run in runs}
    with archive.open("xb") as stream:
        stream.write(gzip.compress(json.dumps(logs, sort_keys=True).encode(), mtime=0))
    assert json.loads(gzip.decompress(archive.read_bytes())) == logs
    report = {
        "state": "generated_activations_consumed_by_joined_feedforward_verified",
        "scope": __doc__, "elapsed_seconds": time.monotonic() - began,
        "source_sha256": hashes,
        "generated_bench_sha256": hashlib.sha256(bench_text.encode()).hexdigest(),
        "generated_hierarchy_sha256": hashlib.sha256(hierarchy_text.encode()).hexdigest(),
        "actual_cores": 20, "actual_clusters": 5, "actual_vendor_memory_models": 602,
        "exact_outputs": sum(run["inventory"]["exact_outputs"] for run in runs),
        "intermediate_bytes_checked": sum(run["inventory"]["intermediate_bytes"] for run in runs),
        "generated_activation_bytes_checked": sum(run["activation_bytes"] for run in runs),
        "runs": runs, "logs_archive_sha256": sha256(archive), "temporary_builds_removed": True,
        "trained_learned_frame_verified": False, "full_paper_results_matched": False,
    }
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"BATCH406_LEARNED_VERIFIED exact_outputs={report['exact_outputs']} cases={len(runs)}", flush=True)


if __name__ == "__main__":
    main()
