"""Verify shared normalization, acknowledged activation writes, and sign replay."""

from concurrent.futures import ThreadPoolExecutor
import gzip
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time

from run_tri_oracle_batch396_masks import GIB, check_memory, sha256
from tri_oracle_process_guard import terminate_process_group


ROOT = Path(__file__).resolve().parents[1]
TOP = "tri_oracle_batched405_normalize_tb"
PREOFFER = "tri_oracle_batched404_preoffer_tb"


def main():
    input_path = ROOT / "records/batch396_mask_fixture.json"
    expected_path = ROOT / "records/batch403_activation_precision.json"
    native_path = ROOT / "records/batch403_native_activation.json"
    replay_path = ROOT / "records/batch398_outlier_result.json"
    inputs, expected, native, replay = [
        json.loads(path.read_text()) for path in (input_path, expected_path, native_path, replay_path)
    ]
    assert expected["source_sha256"][str(input_path)] == sha256(input_path)
    assert native["source_sha256"][str(expected_path)] == sha256(expected_path)
    assert native["state"] == "trained_native_learned_activation_matches_fixed_point_reference"
    assert replay["state"] == "trained_weight_masks_verified_with_one_normalization_per_token"
    assert expected["epsilon_q16"] == inputs["epsilon_q16"] == 43980465
    model, = (Path(path) for path in replay["source_sha256"] if path.endswith("512x64m4f_130a_tt1v25c.v"))
    sources = [ROOT / "verilog" / (name + ".sv") for name in (
        "tri_oracle_rmsnorm", "tri_oracle_affine_quantizer", "tri_oracle_rms_activation",
        "tri_oracle_sign_fetch", "tri_oracle_strip_predictor", "tri_oracle_batched_outlier_replay404",
        "tri_oracle_batched_normalize405", TOP,
    )]
    preoffer = ROOT / "verilog" / (PREOFFER + ".sv")
    prior = native["source_sha256"] | replay["source_sha256"]
    hashes = inputs["files_sha256"] | expected["files_sha256"] | {
        str(path): sha256(path) for path in (*sources, preoffer, model, input_path, expected_path, native_path,
            replay_path, Path(__file__), ROOT / "syn/run_tri_oracle_batch396_masks.py", ROOT / "syn/tri_oracle_process_guard.py")
    }
    assert all(prior[path] == digest for path, digest in hashes.items() if path in prior)
    assert all(sha256(Path(path)) == digest for path, digest in hashes.items())
    check_memory(14 * GIB)
    directory = ROOT / ".cache/physical/simulation/batch405_normalize"
    output = ROOT / "records/batch405_normalize_result.json"
    archive = ROOT / "records/batch405_native_logs.json.gz"
    assert not directory.exists() and not output.exists() and not archive.exists()
    directory.mkdir()
    began = time.monotonic()

    def run(fault):
        log = directory / f"fault{fault}.log"
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix=f"fault{fault}_", dir=directory) as folder:
            work = Path(folder)
            command = [
                "taskset", "-c", str(8 + fault), "/opt/cadence/bin/xrun", "-64bit", "-sv",
                "+define+UNIT_DELAY", "-top", TOP, "-xmlibdirname", str(work / "xcelium.d"),
                "-l", str(work / "native.log"), "-history_file", str(work / "history"),
                *map(str, sources), str(model), f"+INPUT={inputs['fixture']}",
                f"+EXPECTED={expected['fixture']}", f"+FAULT={fault}",
            ]
            with log.open("x") as stream:
                child = subprocess.Popen(command, cwd=work, stdout=stream, stderr=subprocess.STDOUT,
                                         stdin=subprocess.DEVNULL, start_new_session=True)
                try:
                    while child.poll() is None:
                        check_memory(8 * GIB)
                        assert time.monotonic() - started < 120, f"Shared normalization timed out: {log}"
                        time.sleep(0.5)
                    assert child.returncode == 0, f"Shared normalization failed: {log}"
                finally:
                    terminate_process_group(child)
        content = log.read_text()
        assert not re.search(r"\*(?:E|F),|\*ERROR|Simulation terminated via \$fatal", content)
        groups = 2 if fault else 176
        reads = 0 if fault == 4 else 2 * groups * sum(inputs["outlier_pair_counts"])
        tokens, activation_bytes, writes = (2, 272, 4) if fault == 4 else (16, 32768, 256)
        marker = (f"BATCH405_PASS fault={fault} normalizations={tokens} activation_bytes={activation_bytes} "
                  f"writes={writes} mask_bits={tokens * 32 * groups} sign_reads={reads}")
        assert content.splitlines().count(marker) == 1
        if 0 < fault < 4:
            committed = {1: 0, 2: 4080, 3: 240}[fault]
            assert content.splitlines().count(
                f"BATCH405_FAULT_DRAINED fault={fault} committed_words={committed} sign_reads=0"
            ) == 1
        return {
            "fault": fault, "mask_bits": tokens * 32 * groups, "sign_reads": reads,
            "process_group": child.pid, "native_exit_status": child.returncode,
            "log": str(log), "log_sha256": sha256(log), "elapsed_seconds": time.monotonic() - started,
        }

    def run_preoffer(stale_control):
        log = directory / ("preoffer_stale_control.log" if stale_control else "preoffer_recovery.log")
        replay_source = sources[5]
        with tempfile.TemporaryDirectory(prefix="preoffer_", dir=directory) as folder:
            work = Path(folder)
            if stale_control:
                source = replay_source.read_text()
                assignment = "    assign meta_ready = state == Fill && !abort_fill;\n\n"
                insertion = "        cfg_ready = state == Idle;\n"
                assert source.count(assignment) == source.count(insertion) == 1
                replay_source = work / replay_source.name
                replay_source.write_text(source.replace(assignment, "").replace(
                    insertion, insertion + "        meta_ready = state == Fill && !abort_fill;\n"))
            command = [
                "taskset", "-c", str(13 + int(stale_control)), "/opt/cadence/bin/xrun", "-64bit", "-sv",
                "+define+UNIT_DELAY", "-top", PREOFFER, "-xmlibdirname", str(work / "xcelium.d"),
                "-l", str(work / "native.log"), "-history_file", str(work / "history"),
                *map(str, (sources[3], sources[4], replay_source, preoffer, model)),
            ]
            with log.open("x") as stream:
                child = subprocess.Popen(command, cwd=work, stdout=stream, stderr=subprocess.STDOUT,
                                         stdin=subprocess.DEVNULL, start_new_session=True)
                try:
                    child.wait(timeout=30)
                finally:
                    terminate_process_group(child)
        content = log.read_text()
        if stale_control:
            assert child.returncode == 2 and "BATCH404_STALE_OR_MISPLACED_METADATA lane=6 address=0000000100001008" in content
            assert "BATCH404_PREOFFER_PASS" not in content
        else:
            assert child.returncode == 0 and content.splitlines().count("BATCH404_PREOFFER_PASS same_address=1 strips=1") == 1
        return {"stale_control": stale_control, "process_group": child.pid, "native_exit_status": child.returncode,
                "log": str(log), "log_sha256": sha256(log)}

    with ThreadPoolExecutor(max_workers=7) as pool:
        normal = [pool.submit(run, fault) for fault in range(5)]
        preoffers = [pool.submit(run_preoffer, stale) for stale in (False, True)]
        runs = [future.result() for future in normal]
        preoffer_runs = [future.result() for future in preoffers]
    assert all(sha256(Path(path)) == digest for path, digest in hashes.items())
    assert not any(path.is_dir() for path in directory.iterdir())
    logs = {Path(run["log"]).name: Path(run["log"]).read_text() for run in (*runs, *preoffer_runs)}
    red = subprocess.run(
        ["iverilog", "-g2012", "-s", TOP, "-o", "/dev/null", str(sources[-1])],
        cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30,
    )
    assert red.returncode == 2 and "Unknown module type: tri_oracle_batched_normalize405" in red.stdout
    logs["missing_normalization_top.log"] = red.stdout
    with archive.open("xb") as stream:
        stream.write(gzip.compress(json.dumps(logs, sort_keys=True).encode(), mtime=0))
    assert json.loads(gzip.decompress(archive.read_bytes())) == logs
    result = {
        "state": "shared_normalization_activation_writes_and_trained_masks_verified",
        "scope": __doc__,
        "elapsed_seconds": time.monotonic() - began,
        "source_sha256": hashes,
        "runs": runs,
        "preoffer_runs": preoffer_runs,
        "normalizations_per_complete_frame": 16,
        "activation_bytes_checked_per_complete_frame": 32768,
        "acknowledged_writes_per_complete_frame": 256,
        "trained_mask_bits": 90112,
        "trained_sign_reads": 55616,
        "metadata_capacity_bytes": 8192,
        "activation_burst_buffer_bytes": 128,
        "logs_archive_sha256": sha256(archive),
        "temporary_builds_removed": True,
        "joined_compute_frame_verified": False,
        "full_paper_results_matched": False,
    }
    output.write_text(json.dumps(result, indent=2) + "\n")
    print("BATCH405_VERIFIED activations=32768 mask_bits=90112 normalizations=16", flush=True)


if __name__ == "__main__":
    main()
