"""Run the trained mask sweep in Xcelium and retain per-token evidence."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import time

from tri_oracle_process_guard import terminate_process_group


ROOT = Path(__file__).resolve().parents[1]
TOP = "tri_oracle_batched396_masks_tb"
GIB = 1024**3


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def check_memory(reserve):
    available = next(int(line.split()[1]) * 1024 for line in Path("/proc/meminfo").read_text().splitlines()
                     if line.startswith("MemAvailable:"))
    anonymous = int(dict(line.split() for line in Path("/sys/fs/cgroup/memory.stat").read_text().splitlines())["anon"])
    assert available > reserve and anonymous < 15 * GIB, (available, anonymous)


def main():
    source = ROOT / "records/batch396_mask_fixture.json"
    fixture = json.loads(source.read_text())
    assert fixture["state"] == "trained_residuals_and_weight_signs_match_archived_masks"
    assert (fixture["tokens"], fixture["channels"], fixture["features"]) == (16, 5632, 2048)
    directory = ROOT / ".cache/physical/simulation/batch396_masks"
    output = ROOT / "records/batch396_native_masks.json"
    assert not output.exists() and not directory.exists()
    check_memory(14 * GIB)
    paths = [ROOT / "verilog" / (name + ".sv") for name in (
        "tri_oracle_rmsnorm", "tri_oracle_sign_fetch", "tri_oracle_strip_predictor",
        "tri_oracle_rms_sign_predictor", TOP,
    )]
    hashes = fixture["files_sha256"] | {
        str(path): sha256(path) for path in (*paths, Path(__file__), source, ROOT / "syn/tri_oracle_process_guard.py")
    }
    assert all(sha256(Path(path)) == digest for path, digest in hashes.items())
    words = (Path(fixture["fixture"]) / "branch_masks.hex").read_text().splitlines()
    assert len(words) == 16 * 176
    expected_skips = [
        sum((int(word, 16) & 0xffffffff).bit_count() for word in words[token * 176:(token + 1) * 176])
        for token in range(16)
    ]
    assert sum(expected_skips) == fixture["skipped_channels"] == 5231
    directory.mkdir()
    stopped = False

    def stop(_signal, _frame):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    started = time.monotonic()
    result = {
        "state": "running", "supervisor_pid": os.getpid(), "source_sha256": hashes,
        "runs": [], "full_paper_results_matched": False, "integrated_frame_verified": False,
    }

    def save():
        result["elapsed_seconds"] = time.monotonic() - started
        temporary = output.with_suffix(".tmp")
        temporary.write_text(json.dumps(result, indent=2) + "\n")
        temporary.replace(output)

    def run(token):
        assert not stopped
        work = directory / f"token{token:02d}"
        log = work.with_suffix(".log")
        work.mkdir()
        process = None
        command = [
            "taskset", "-c", "8-19", "/opt/cadence/bin/xrun", "-64bit", "-sv",
            "-top", TOP, "-xmlibdirname", str(work / "xcelium.d"), "-l", str(work / "native.log"),
            "-history_file", str(work / "history"), *map(str, paths),
            f"+FIXTURE={fixture['fixture']}", f"+TOKEN={token}",
        ]
        begin = time.monotonic()
        try:
            check_memory(8 * GIB)
            with log.open("x") as stream:
                process = subprocess.Popen(
                    command, cwd=work, stdin=subprocess.DEVNULL, stdout=stream,
                    stderr=subprocess.STDOUT, start_new_session=True,
                )
                print(f"BATCH396_TOKEN_STARTED token={token} group={process.pid}", flush=True)
                while process.poll() is None:
                    check_memory(8 * GIB)
                    assert not stopped and time.monotonic() - begin < 300, f"Token {token} stopped or timed out"
                    time.sleep(0.5)
            content = log.read_text()
            assert process.returncode == 0, f"Native token {token} failed: {log}"
            assert not re.search(r"\*(?:E|F),|\*ERROR|Simulation terminated via \$fatal", content)
            reads = 176 * 2 * fixture["outlier_pair_counts"][token]
            marker = (f"BATCH396_MASKS_PASS token={token} groups=176 channels=5632 "
                      f"skipped={expected_skips[token]} sign_reads={reads}")
            assert content.splitlines().count(marker) == 1, f"Incorrect native token inventory: {log}"
            return {
                "token": token, "groups": 176, "channels": 5632, "skip_bits_set": expected_skips[token],
                "sign_reads": reads, "native_exit_status": process.returncode, "process_group": process.pid,
                "elapsed_seconds": time.monotonic() - begin, "log": str(log), "log_sha256": sha256(log),
            }
        finally:
            if process is not None:
                terminate_process_group(process)
            shutil.rmtree(work)

    save()
    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(run, token) for token in range(16)]
            try:
                for future in as_completed(futures):
                    receipt = future.result()
                    result["runs"].append(receipt)
                    print(f"BATCH396_TOKEN_VERIFIED token={receipt['token']}", flush=True)
                    save()
            except BaseException:
                stopped = True
                for future in futures:
                    future.cancel()
                raise
        result["runs"].sort(key=lambda run: run["token"])
        assert [run["token"] for run in result["runs"]] == list(range(16))
        assert not any(path.is_dir() for path in directory.iterdir())
        assert all(sha256(Path(path)) == digest for path, digest in hashes.items())
        reads = sum(run["sign_reads"] for run in result["runs"])
        result.update(
            state="complete_trained_layer_masks_and_sign_reads_verified",
            skip_bits_compared=16 * 5632, gate_and_up_bits_compared=2 * 16 * 5632,
            skipped_channels=sum(expected_skips), sign_reads=reads, sign_read_bytes=8 * reads,
            temporary_builds_removed=True,
        )
        save()
        print(f"BATCH396_NATIVE_VERIFIED skip_bits={16 * 5632} sign_reads={reads}", flush=True)
    except BaseException as error:
        result.update(state="failed", exception=repr(error))
        save()
        raise


if __name__ == "__main__":
    main()
