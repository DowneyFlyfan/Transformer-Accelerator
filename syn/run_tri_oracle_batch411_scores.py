"""Check the paper's selected score path from trained query/key bytes through head decisions."""

from concurrent.futures import ThreadPoolExecutor
import gzip
import json
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time

from run_tri_oracle_batch396_masks import GIB, check_memory, sha256
from tri_oracle_process_guard import terminate_process_group


ROOT = Path(__file__).resolve().parents[1]
TOP = "tri_oracle_attention411_score_tb"
ADAPTER = "tri_oracle_attention_score_adapter411"
HIERARCHY = "BATCH357_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=600"
HEADS, ROWS, WIDTH, SHARD = 32, 15, 64, 4


def main():
    check_memory(14 * GIB)
    records = ROOT / "records"
    backend_path = records / "batch393_literal_result.json"
    fixture_path = records / "batch409_attention_fixture.json"
    classifier_path = records / "batch410_classifier_result.json"
    backend, fixture, classifier = (json.loads(path.read_text())
                                    for path in (backend_path, fixture_path, classifier_path))
    assert fixture["state"] == "trained_rotary_attention_fixture_cpu_cuda_equal"
    assert classifier["state"] == "trained_attention_classification_from_precomputed_scores_verified"
    assert fixture["query_heads"] == HEADS and fixture["head_features"] == WIDTH
    assert fixture["sequence_tokens"] == 606 and fixture["key_value_heads"] == 4
    assert fixture["query_positions"] == [127 + row * 32 for row in range(ROWS)]
    assert fixture["tile_positions"] == [[list(range(start, start + 32)) for start in (0, (row+1)*32, (row+3)*32)]
                                         for row in range(ROWS)]
    assert fixture["local_ratio_threshold"] == 1
    names = ("pe_array", "sram_memory_compute", "sram_compute_cluster", "compute_fabric",
             "batched_projection356", "batched_tensor390", "batch357_hierarchy")
    sources = [ROOT / "verilog" / f"tri_oracle_{name}.sv" for name in names]
    models = [Path(path) for path in backend["source_sha256"] if "/VERILOG/" in path and path.endswith(".v")]
    assert len(models) == 3
    verified_classifier = ROOT / "verilog/tri_oracle_attention_head_classifier410.sv"
    adapter = ROOT / f"verilog/{ADAPTER}.sv"
    bench = ROOT / f"verilog/{TOP}.sv"
    digests = fixture["files_sha256"] | {str(path): backend["source_sha256"][str(path)] for path in sources + models}
    digests[str(verified_classifier)] = classifier["source_and_fixture_sha256"][str(verified_classifier)]
    evidence = (adapter, bench, backend_path, fixture_path, classifier_path, Path(__file__),
                ROOT / "syn/tri_oracle_process_guard.py", ROOT / "syn/run_tri_oracle_batch396_masks.py")
    digests.update({str(path): sha256(path) for path in evidence})
    assert all(sha256(Path(path)) == digest for path, digest in digests.items())
    report = records / "batch411_attention_score_result.json"
    archive = records / "batch411_native_logs.json.gz"
    assert not report.exists() and not archive.exists()
    fixture_directory = Path(fixture["fixture"])
    queries = bytes.fromhex((fixture_directory / "query.hex").read_text())
    streaming = bytes.fromhex((fixture_directory / "streaming.hex").read_text())
    assert len(queries) == HEADS * ROWS * WIDTH and len(streaming) == HEADS
    stopped = False
    started = time.monotonic()

    def stop(_signum, _frame):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    def reads_for(row, key_count):
        query = queries[row*WIDTH:(row+1)*WIDTH]
        return 4 + key_count * sum(any(query[start:start+16]) for start in range(0, WIDTH, 16))

    def run(work, first, count, corrupted=False):
        name = "wrong_score" if corrupted else f"heads_{first:02}"
        directory = work / name
        directory.mkdir()
        selected_adapter = adapter
        if corrupted:
            selected_adapter = directory / adapter.name
            text = adapter.read_text()
            original = "saved_scores[int'(score_beat)*256 +: 256]"
            assert text.count(original) == 1
            selected_adapter.write_text(text.replace(original, f"({original} ^ 256'd1)"))
        paths = [*sources, *models, verified_classifier, selected_adapter, bench]
        bundle = directory / "bundle.sv"
        bundle.write_text('`define UNIT_DELAY\n`define TRI_ORACLE_SRAM_CLUSTER_BIND_PUBLIC\n' +
                          "".join(f'`include "{path}"\n' for path in paths))
        log = directory / "console.log"
        cpu = 16 if corrupted else 8 + first // SHARD
        command = ["taskset", "-c", str(cpu), "/opt/cadence/bin/xrun", "-64bit", "-sv", "-xmerror", "RECOME",
                   "-notimingchecks", "-top", TOP, "-top", "tri_oracle_batch357_hierarchy",
                   "-defparam", f"{TOP}.FIRST_HEAD={first}", "-defparam", f"{TOP}.HEAD_COUNT={count}",
                   str(bundle), f"+FIXTURE={fixture_directory}"]
        began = time.monotonic()
        with log.open("x") as stream:
            process = subprocess.Popen(command, cwd=directory, stdout=stream, stderr=subprocess.STDOUT,
                                       stdin=subprocess.DEVNULL, start_new_session=True)
            print(f"BATCH411_STARTED case={name} group={process.pid}", flush=True)
            try:
                while process.poll() is None:
                    check_memory(8 * GIB)
                    assert not stopped and time.monotonic() - began < 600, name
                    time.sleep(1)
            finally:
                terminate_process_group(process)
        content = log.read_text()
        assert content.splitlines().count(HIERARCHY) == 1, content[-3500:]
        if corrupted:
            with (fixture_directory / "scores.hex").open() as expected_scores:
                expected = int(expected_scores.readline(), 16)
            marker = ("BATCH411_WRONG_SCORE head=0 row=0 region=0 lane=0 "
                      f"expected={expected:08x} actual={expected ^ 1:08x}")
            assert process.returncode != 0 and content.count(marker) == 1 and "BATCH411_PASS" not in content, content[-3500:]
            inventory = {"rejected_wrong_score": True, "expected": expected, "actual": expected ^ 1}
        else:
            matches = re.findall(r"^BATCH411_PASS (.+)$", content, re.MULTILINE)
            assert process.returncode == 0 and len(matches) == 1, content[-3500:]
            inventory = {name: int(value) for name, value in (part.split("=") for part in matches[0].split())}
            reads = sum(reads_for(row, 96) for row in range(first*ROWS, (first+count)*ROWS))
            if first == 0:
                reads += reads_for(0, 58) + 1
            assert inventory == dict(first=first, heads=count, rows=count*ROWS, scores=count*ROWS*96,
                                     streaming=sum(streaming[first:first+count]), partial_scores=58 if first == 0 else 0,
                                     errors=4 if first == 0 else 0, reads=reads, stalls=inventory["stalls"])
            assert inventory["stalls"] > 0
        print(f"BATCH411_CHECKED case={name} status={process.returncode}", flush=True)
        return name, {"native_status": process.returncode, "inventory": inventory,
                      "elapsed_seconds": time.monotonic()-began, "log_sha256": sha256(log)}, content

    with tempfile.TemporaryDirectory(dir=ROOT / ".cache", prefix="batch411_scores_") as temp:
        work = Path(temp)
        lint = subprocess.run(["verilator", "--lint-only", "-Wall", "--top-module", ADAPTER, str(adapter)],
                              cwd=work, capture_output=True, text=True, timeout=30)
        assert lint.returncode == 0, lint.stdout + lint.stderr
        with ThreadPoolExecutor(max_workers=9) as pool:
            futures = [pool.submit(run, work, first, SHARD) for first in range(0, HEADS, SHARD)]
            futures.append(pool.submit(run, work, 0, 1, True))
            runs = [future.result() for future in futures]
    assert not work.exists() and not stopped
    assert all(sha256(Path(path)) == digest for path, digest in digests.items())
    logs = {name: content for name, _, content in runs} | {"verilator": lint.stdout + lint.stderr}
    with archive.open("xb") as stream:
        stream.write(gzip.compress(json.dumps(logs, sort_keys=True).encode(), mtime=0))
    assert json.loads(gzip.decompress(archive.read_bytes())) == logs
    inventories = [entry["inventory"] for name, entry, _ in runs if name != "wrong_score"]
    totals = {key: sum(inventory[key] for inventory in inventories)
              for key in ("heads", "rows", "scores", "streaming", "partial_scores", "errors", "reads", "stalls")}
    assert (totals["heads"], totals["rows"], totals["scores"], totals["streaming"]) == (32, 480, 46080, 4)
    result = {
        "state": "trained_selected_scores_to_attention_head_decisions_verified",
        "scope": __doc__, "elapsed_seconds": time.monotonic()-started, "actual_cores": 20,
        "actual_clusters": 5, "compiled_memory_models": 600, "inventory": totals,
        "runs": {name: entry for name, entry, _ in runs}, "source_and_fixture_sha256": digests,
        "native_logs_sha256": sha256(archive), "full_paper_results_matched": False,
    }
    with report.open("x") as stream:
        stream.write(json.dumps(result, indent=2) + "\n")
    print(f"BATCH411_VERIFIED {totals}", flush=True)


if __name__ == "__main__":
    main()
