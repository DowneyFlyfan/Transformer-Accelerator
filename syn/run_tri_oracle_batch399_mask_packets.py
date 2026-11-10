"""Verify packet boundaries and join the adapter to the trained predictor."""

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
TOP = "tri_oracle_batched399_mask_packet_tb"


def main():
    receipt = ROOT / "records/batch396_mask_fixture.json"
    fixture = json.loads(receipt.read_text())
    predictor_path = ROOT / "records/batch398_outlier_result.json"
    predictor = json.loads(predictor_path.read_text())
    assert predictor["state"] == "trained_weight_masks_verified_with_one_normalization_per_token"
    assert predictor["source_sha256"][str(receipt)] == sha256(receipt)
    model, = (Path(path) for path in predictor["source_sha256"] if path.endswith("512x64m4f_130a_tt1v25c.v"))
    directory = ROOT / ".cache/physical/simulation/batch399_mask_packets"
    output = ROOT / "records/batch399_mask_packet_result.json"
    archive = ROOT / "records/batch399_native_logs.json.gz"
    assert not directory.exists() and not output.exists() and not archive.exists()
    check_memory(14 * GIB)
    adapter = ROOT / "verilog/tri_oracle_batched_mask_packet399.sv"
    bench = ROOT / "verilog" / (TOP + ".sv")
    sources = [ROOT / "verilog" / (name + ".sv") for name in (
        "tri_oracle_rmsnorm", "tri_oracle_sign_fetch", "tri_oracle_strip_predictor",
        "tri_oracle_batched_outliers398",
    )]
    hashes = fixture["files_sha256"] | {
        str(path): sha256(path) for path in (
            receipt, predictor_path, model, *sources, adapter, bench, Path(__file__),
            ROOT / "syn/run_tri_oracle_batch396_masks.py", ROOT / "syn/tri_oracle_process_guard.py",
        )
    }
    for path in (model, *sources):
        assert hashes[str(path)] == predictor["source_sha256"][str(path)]
    assert all(sha256(Path(path)) == digest for path, digest in hashes.items())
    directory.mkdir()
    began = time.monotonic()

    def run_native():
        log = directory / "joined_xcelium.log"
        with tempfile.TemporaryDirectory(prefix="joined_", dir=directory) as folder:
            work = Path(folder)
            command = [
                "taskset", "-c", "9", "/opt/cadence/bin/xrun", "-64bit", "-sv", "+define+UNIT_DELAY",
                "-top", TOP, "-defparam", TOP + ".NATIVE=1",
                "-xmlibdirname", str(work / "xcelium.d"), "-l", str(work / "native.log"),
                "-history_file", str(work / "history"), *map(str, sources), str(adapter),
                str(bench), str(model), f"+FIXTURE={fixture['fixture']}",
            ]
            with log.open("x") as stream:
                child = subprocess.Popen(
                    command, cwd=work, stdin=subprocess.DEVNULL, stdout=stream,
                    stderr=subprocess.STDOUT, start_new_session=True,
                )
                started = time.monotonic()
                try:
                    while child.poll() is None:
                        check_memory(8 * GIB)
                        assert time.monotonic() - started < 120
                        time.sleep(0.5)
                    assert child.returncode == 0, f"Joined native simulation failed: {log}"
                finally:
                    terminate_process_group(child)
        return log, child.pid

    def run_literal(discard_carry=False):
        log = directory / ("discard_carry.log" if discard_carry else "literal_iverilog.log")
        with tempfile.TemporaryDirectory(prefix="literal_", dir=directory) as folder:
            work = Path(folder)
            source = adapter
            if discard_carry:
                old = "{64'd0, carry[token]}"
                text = adapter.read_text()
                assert text.count(old) == 1
                source = work / adapter.name
                source.write_text(text.replace(old, "80'd0"))
            binary = work / "test.vvp"
            compiled = subprocess.run(
                ["iverilog", "-g2012", "-s", TOP, "-o", str(binary), str(source), str(bench)],
                cwd=work, text=True, capture_output=True, timeout=30,
            )
            assert compiled.returncode == 0, compiled.stderr
            result = subprocess.run(
                ["taskset", "-c", "10" if discard_carry else "11", "vvp", str(binary)],
                cwd=work, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30,
            )
            log.write_text(result.stdout)
            assert result.returncode == int(discard_carry), result.stdout
        return log

    with ThreadPoolExecutor(max_workers=3) as pool:
        native_future = pool.submit(run_native)
        literal_future = pool.submit(run_literal)
        control_future = pool.submit(run_literal, True)
        native_log, group = native_future.result()
        literal_log = literal_future.result()
        control_log = control_future.result()
    assert not any(path.is_dir() for path in directory.iterdir())
    assert all(sha256(Path(path)) == digest for path, digest in hashes.items())
    logs = {path.name: path.read_text() for path in (native_log, literal_log, control_log)}
    assert not re.search(r"\*(?:E|F),|\*ERROR|Simulation terminated via \$fatal", logs[native_log.name])
    native_pass = "BATCH399_PASS native=1 packets=71 mask_bits=90112 padding_bits=768 sign_reads=55616"
    assert logs[native_log.name].splitlines().count(native_pass) == 1
    cases = [(1, 32), (2, 64), (3, 96), (9, 128), (16, 160), (3, 192), (16, 8160), (3, 96)]
    packet_total = sum((channels + 79) // 80 for _, channels in cases)
    bit_total = sum(tokens * channels for tokens, channels in cases)
    literal_pass = (f"BATCH399_PASS native=0 packets={packet_total} mask_bits={bit_total} "
                    f"padding_bits={1280 * packet_total - bit_total} sign_reads=0")
    assert logs[literal_log.name].splitlines().count(literal_pass) == 1
    assert logs[literal_log.name].splitlines().count("BATCH399_HELD_PACKET_CANCELLED") == 1
    assert "BATCH399_PACKET_MISMATCH tokens=3 channels=96 start=80 count=16" in logs[control_log.name]
    assert "BATCH399_PASS" not in logs[control_log.name]
    red = subprocess.run(
        ["iverilog", "-g2012", "-s", TOP, "-o", "/dev/null", str(bench)],
        cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30,
    )
    assert red.returncode == 2 and "Unknown module type: tri_oracle_batched_mask_packet399" in red.stdout
    logs["missing_packetizer.log"] = red.stdout
    with archive.open("xb") as stream:
        stream.write(gzip.compress(json.dumps(logs, sort_keys=True).encode(), mtime=0))
    assert json.loads(gzip.decompress(archive.read_bytes())) == logs
    report = {
        "state": "trained_predictor_to_keep_packets_verified",
        "scope": __doc__,
        "elapsed_seconds": time.monotonic() - began,
        "source_sha256": hashes,
        "native_process_group": group,
        "native_exit_status": 0,
        "trained_packets": 71,
        "trained_mask_bits": 90112,
        "trained_padding_bits": 768,
        "trained_sign_reads": 55616,
        "literal_cases": cases,
        "literal_packets": packet_total,
        "literal_mask_bits": bit_total,
        "held_packet_cancellation_verified": True,
        "missing_carry_counterfactual_rejected": True,
        "logs_archive_sha256": sha256(archive),
        "temporary_builds_removed": True,
        "shared_compute_frame_verified": False,
        "full_paper_results_matched": False,
    }
    output.write_text(json.dumps(report, indent=2) + "\n")
    print("BATCH399_VERIFIED trained_packets=71 mask_bits=90112 sign_reads=55616", flush=True)


if __name__ == "__main__":
    main()
