"""Verify shared outlier metadata across all trained channel groups."""

from concurrent.futures import ThreadPoolExecutor
import gzip
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

from run_tri_oracle_batch396_masks import GIB, check_memory, sha256
from tri_oracle_process_guard import terminate_process_group


ROOT = Path(__file__).resolve().parents[1]
TOP = "tri_oracle_batched398_outliers_tb"


def main():
    receipt = ROOT / "records/batch396_mask_fixture.json"
    fixture = json.loads(receipt.read_text())
    assert (fixture["tokens"], fixture["features"], fixture["channels"], fixture["epsilon_q16"]) == (16, 2048, 5632, 43980465)
    reference_path = ROOT / "records/batch396_native_masks.json"
    reference = json.loads(reference_path.read_text())
    assert reference["state"] == "complete_trained_layer_masks_and_sign_reads_verified"
    assert sha256(receipt) == reference["source_sha256"][str(receipt)]
    checkpoint = json.loads((ROOT / "records/batch393_literal_result.json").read_text())
    model, = (Path(path) for path in checkpoint["source_sha256"] if path.endswith("512x64m4f_130a_tt1v25c.v"))
    assert sha256(model) == checkpoint["source_sha256"][str(model)]
    directory = ROOT / ".cache/physical/simulation/batch398_outliers"
    output = ROOT / "records/batch398_outlier_result.json"
    archive = ROOT / "records/batch398_native_logs.json.gz"
    assert not directory.exists() and not output.exists() and not archive.exists()
    check_memory(14 * GIB)
    sources = [ROOT / "verilog" / (name + ".sv") for name in (
        "tri_oracle_rmsnorm", "tri_oracle_sign_fetch", "tri_oracle_strip_predictor",
        "tri_oracle_batched_outliers398", TOP,
    )]
    hashes = fixture["files_sha256"] | {
        str(path): sha256(path) for path in (
            receipt, reference_path, model, *sources, Path(__file__),
            ROOT / "syn/run_tri_oracle_batch396_masks.py", ROOT / "syn/tri_oracle_process_guard.py",
        )
    }
    assert all(sha256(Path(path)) == digest for path, digest in hashes.items())
    branch_words = (Path(fixture["fixture"]) / "branch_masks.hex").read_text().splitlines()
    assert len(branch_words) == 16 * 176
    directory.mkdir()
    began = time.monotonic()

    def run(fault):
        limit = 176 if fault == 0 else 2
        work = directory / f"fault{fault}"
        work.mkdir()
        log = work.with_suffix(".log")
        command = [
            "taskset", "-c", str(9 + fault), "/opt/cadence/bin/xrun", "-64bit", "-sv", "+define+UNIT_DELAY",
            "-top", TOP, "-xmlibdirname", str(work / "xcelium.d"), "-l", str(work / "native.log"),
            "-history_file", str(work / "history"), *map(str, sources), str(model),
            f"+FIXTURE={fixture['fixture']}", f"+GROUP_LIMIT={limit}", f"+FAULT={fault}",
        ]
        process = None
        started = time.monotonic()
        try:
            with log.open("x") as stream:
                process = subprocess.Popen(
                    command, cwd=work, stdin=subprocess.DEVNULL, stdout=stream,
                    stderr=subprocess.STDOUT, start_new_session=True,
                )
                while process.poll() is None:
                    check_memory(8 * GIB)
                    assert time.monotonic() - started < 240, f"Outlier replay timed out: {log}"
                    time.sleep(0.5)
            text = log.read_text()
            assert process.returncode == 0, f"Outlier replay failed: {log}"
            assert not re.search(r"\*(?:E|F),|\*ERROR|Simulation terminated via \$fatal", text)
            skips = sum((int(branch_words[token * 176 + group], 16) & 0xffffffff).bit_count()
                        for token in range(16) for group in range(limit))
            reads = limit * 2 * sum(fixture["outlier_pair_counts"])
            lines = text.splitlines()
            assert lines.count(
                f"BATCH398_PASS tokens=16 groups={limit} normalizations=16 "
                f"mask_bits={limit * 512} skipped={skips} sign_reads={reads} fault={fault}"
            ) == 1
            assert lines.count(
                f"BATCH398_MACROS lower_writes=512 upper_writes=512 lower_reads={limit * 512} upper_reads={limit * 512}"
            ) == 1
            if fault:
                assert lines.count(
                    f"BATCH398_FAULT_RECOVERED fault={fault} drained={int(fault in (1, 4))} "
                    f"provisional_groups={19 if fault == 4 else 0}"
                ) == 1
            if fault == 3:
                assert lines.count("BATCH398_RESIDUAL_OFFERS_CANCELLED streams=2") == 1
                assert lines.count("BATCH398_SHORT_ZERO_PASS tokens=9 strips=5 sign_reads=0") == 1
            return {
                "fault": fault, "groups": limit, "normalizations": 16, "skip_bits": limit * 512,
                "sign_reads": reads, "skipped_channels": skips, "native_exit_status": process.returncode,
                "process_group": process.pid, "elapsed_seconds": time.monotonic() - started,
                "log": str(log), "log_sha256": sha256(log),
            }
        finally:
            if process is not None:
                terminate_process_group(process)
            shutil.rmtree(work)

    with ThreadPoolExecutor(max_workers=5) as pool:
        runs = list(pool.map(run, range(5)))
    assert not any(path.is_dir() for path in directory.iterdir())
    assert all(sha256(Path(path)) == digest for path, digest in hashes.items())
    assert (runs[0]["skip_bits"], runs[0]["skipped_channels"], runs[0]["sign_reads"]) == (
        reference["skip_bits_compared"], reference["skipped_channels"], reference["sign_reads"]
    )
    logs = {Path(run["log"]).name: Path(run["log"]).read_text() for run in runs}
    red = subprocess.run(
        ["iverilog", "-g2012", "-s", TOP, "-o", "/dev/null", str(sources[-1])],
        cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30,
    )
    assert red.returncode == 2 and "Unknown module type: tri_oracle_batched_outliers398" in red.stdout
    logs["missing_outlier_store.log"] = red.stdout
    with archive.open("xb") as stream:
        stream.write(gzip.compress(json.dumps(logs, sort_keys=True).encode(), mtime=0))
    assert json.loads(gzip.decompress(archive.read_bytes())) == logs
    report = {
        "state": "trained_weight_masks_verified_with_one_normalization_per_token",
        "scope": __doc__,
        "supervisor_pid": os.getpid(),
        "elapsed_seconds": time.monotonic() - began,
        "source_sha256": hashes,
        "runs": runs,
        "metadata_macros": 2,
        "metadata_capacity_bytes": 8192,
        "full_metadata_read_words": 180224,
        "full_metadata_write_words": 1024,
        "temporary_builds_removed": True,
        "logs_archive_sha256": sha256(archive),
        "integrated_frame_verified": False,
        "full_paper_results_matched": False,
    }
    output.write_text(json.dumps(report, indent=2) + "\n")
    print("BATCH398_VERIFIED normalizations=16 skip_bits=90112 sign_reads=55616", flush=True)


if __name__ == "__main__":
    main()
