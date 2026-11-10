"""Verify batched trained head prediction and exact key reuse in Xcelium."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import gzip
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time

from run_tri_oracle_batch396_masks import GIB, check_memory, sha256
from tri_oracle_process_guard import terminate_process_group


ROOT = Path(__file__).resolve().parents[1]
TOP = "tri_oracle_attention413_tile_tb"
ADAPTER = "tri_oracle_attention_tile_batch413"
HEADS, ROWS, WIDTH, SEQUENCE = 32, 510, 64, 606


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("canary", "full"))
    mode = parser.parse_args().mode
    check_memory(14 * GIB)
    records = ROOT / "records"
    fixture_record = records / "batch412_tiled_attention_fixture.json"
    backend_record = records / "batch393_literal_result.json"
    classifier_record = records / "batch410_classifier_result.json"
    fixture, backend, classifier = (json.loads(path.read_text()) for path in
                                    (fixture_record, backend_record, classifier_record))
    assert fixture["state"] == "trained_causal_tile_rows_cpu_cuda_equal"
    assert (fixture["query_heads"], fixture["queries_per_head"], fixture["head_features"],
            fixture["sequence_tokens"], fixture["first_query_position"], fixture["local_ratio_threshold"]) == (
                HEADS, ROWS, WIDTH, SEQUENCE, 96, 1)
    batches = [{"query_first": start, "queries": min(16, SEQUENCE-start),
                "key_starts": [0, (start//32-2)*32, (start//32)*32]} for start in range(96, SEQUENCE, 16)]
    assert fixture["batches"] == batches
    prior_names = ("pe_array", "sram_memory_compute", "sram_compute_cluster", "compute_fabric",
                   "batched_projection356", "batched_tensor390", "batch357_hierarchy")
    sources = [ROOT / "verilog" / f"tri_oracle_{name}.sv" for name in prior_names]
    models = [Path(path) for path in backend["source_sha256"] if "/VERILOG/" in path and path.endswith(".v")]
    assert len(models) == 3
    classifier_rtl = ROOT / "verilog/tri_oracle_attention_head_classifier410.sv"
    adapter = ROOT / f"verilog/{ADAPTER}.sv"
    bench = ROOT / f"verilog/{TOP}.sv"
    evidence = (adapter, bench, fixture_record, backend_record, classifier_record, Path(__file__),
                ROOT / "syn/run_tri_oracle_batch396_masks.py", ROOT / "syn/tri_oracle_process_guard.py")
    digests = fixture["files_sha256"] | {str(path): backend["source_sha256"][str(path)] for path in sources + models}
    digests[str(classifier_rtl)] = classifier["source_and_fixture_sha256"][str(classifier_rtl)]
    digests.update({str(path): sha256(path) for path in evidence})
    assert all(sha256(Path(path)) == digest for path, digest in digests.items())
    report = records / f"batch413_{mode}_tile_result.json"
    archive = records / f"batch413_{mode}_native_logs.json.gz"
    assert not report.exists() and not archive.exists()
    directory = Path(fixture["fixture"])
    queries, keys, counts = (bytes.fromhex((directory / f"{name}.hex").read_text()) for name in ("query", "key", "counts"))
    assert len(queries) == HEADS*ROWS*WIDTH and len(keys) == 4*SEQUENCE*WIDTH and len(counts) == HEADS*ROWS*2
    if mode == "canary":
        batches = [batches[0], batches[-1]]

    def active_words(head, first, count):
        offset = (head*ROWS+first-96)*WIDTH
        return tuple(any(any(queries[offset+row*WIDTH+8*word:offset+row*WIDTH+8*(word+1)])
                         for row in range(count)) for word in range(8))

    def expected_reads(head, first, count, recent):
        active = active_words(head, first, count)
        keys_used = 64 + first+count-recent
        return count*4 + keys_used*sum(any(active[word:word+2]) for word in range(0, 8, 2)), keys_used*sum(active)

    def inventory(first_head, count):
        data = dict(first=first_head, heads=count, rows=0, live=0, masked=0, streaming=0,
                    errors=5 if first_head == 0 else 0, requests=0, words=0)
        batched = baseline = 0
        for head in range(first_head, first_head+count):
            inner = recent_hits = 0
            for batch in batches:
                first, rows, recent = batch["query_first"], batch["queries"], batch["key_starts"][2]
                requests, key_words = expected_reads(head, first, rows, recent)
                data["requests"] += requests
                data["words"] += rows*8+key_words
                batched += key_words
                for position in range(first, first+rows):
                    key_count = 65+position-recent
                    data["live"] += key_count
                    data["masked"] += 96-key_count
                    baseline += key_count * sum(active_words(head, position, 1))
                    offset = 2*(head*ROWS+position-96)
                    inner += counts[offset]
                    recent_hits += counts[offset+1]
                data["rows"] += rows
            data["streaming"] += int(recent_hits > inner)
        if first_head == 0:
            # Two faults drain after loading operands. A transport error owns just the first query burst.
            fault_requests, fault_keys = expected_reads(0, 96, 3, 96)
            data["requests"] += 2*fault_requests + 1
            data["words"] += 2*(3*8+fault_keys) + 2
        return data, batched, baseline

    def byte_signed(value):
        return value if value < 128 else value-256

    wrong_score = sum(byte_signed(q)*byte_signed(k) for q,k in zip(queries[:WIDTH], keys[97*WIDTH:98*WIDTH]))
    assert wrong_score != 0
    stopped = False

    def stop(_signum, _frame):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    cpus = sorted(os.sched_getaffinity(0))
    assert len(cpus) >= 17
    started = time.monotonic()

    def run(work, first, count, cpu, corrupt=False):
        name = "future_key_control" if corrupt else f"heads_{first:02}"
        folder = work / name
        folder.mkdir()
        chosen_adapter = adapter
        if corrupt:
            chosen_adapter = folder / adapter.name
            text = adapter.read_text()
            bound = "key_position <= 17'(first_query) + 17'(token)"
            assert text.count(bound) == 1
            chosen_adapter.write_text(text.replace(bound, "key_position <= last_query"))
        bundle = folder / "bundle.sv"
        bundle.write_text('`define UNIT_DELAY\n`define TRI_ORACLE_SRAM_CLUSTER_BIND_PUBLIC\n' +
                          "".join(f'`include "{path}"\n' for path in (*sources, *models, classifier_rtl, chosen_adapter, bench)))
        command = ["taskset", "-c", str(cpu), "/opt/cadence/bin/xrun", "-64bit", "-sv", "-xmerror", "RECOME",
                   "-notimingchecks", "-top", TOP, "-top", "tri_oracle_batch357_hierarchy",
                   "-defparam", f"{TOP}.FIRST_HEAD={first}", "-defparam", f"{TOP}.HEAD_COUNT={count}",
                   "-defparam", f"{TOP}.CANARY={int(mode=='canary' or corrupt)}", str(bundle), f"+FIXTURE={directory}"]
        log = folder / "console.log"
        began = time.monotonic()
        with log.open("x") as stream:
            worker = subprocess.Popen(command, cwd=folder, stdout=stream, stderr=subprocess.STDOUT,
                                      stdin=subprocess.DEVNULL, start_new_session=True)
            print(f"BATCH413_STARTED case={name} group={worker.pid} cpu={cpu}", flush=True)
            try:
                while worker.poll() is None:
                    check_memory(8 * GIB)
                    assert not stopped and time.monotonic()-began < 1200, name
                    time.sleep(1)
            finally:
                terminate_process_group(worker)
        content = log.read_text()
        assert content.splitlines().count("BATCH357_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=600") == 1
        matches = re.findall(r"^BATCH413_PASS (.+)$", content, re.M)
        if corrupt:
            marker = f"BATCH413_BAD_SCORE head=0 query=96 region=2 lane=1 expected=00000000 actual={wrong_score & 0xffffffff:08x}"
            assert worker.returncode != 0 and not matches and content.count(marker) == 1, content[-4500:]
            data = {"rejected_future_key": 97, "query": 96, "unexpected_score": wrong_score}
        else:
            assert worker.returncode == 0 and len(matches) == 1, content[-4500:]
            measured = {name: int(value) for name,value in (part.split("=") for part in matches[0].split())}
            expected, batched, baseline = inventory(first, count)
            assert measured.pop("stalls") > 0 and measured == expected, (measured, expected)
            data = measured | {"batched_key_words": batched, "unbatched_key_words_same_rows": baseline}
        print(f"BATCH413_CHECKED case={name} status={worker.returncode}", flush=True)
        return name, {"native_status": worker.returncode, "inventory": data, "log_sha256": sha256(log),
                      "elapsed_seconds": time.monotonic()-began}, content

    with tempfile.TemporaryDirectory(dir=ROOT / ".cache", prefix=f"batch413_{mode}_build_") as name:
        work = Path(name)
        lint = subprocess.run(["verilator", "--lint-only", "-Wall", "--top-module", ADAPTER, str(adapter)],
                              cwd=work, capture_output=True, text=True, timeout=30)
        assert lint.returncode == 0, lint.stdout + lint.stderr
        groups = [(0, 1, cpus[-1])] if mode == "canary" else [(head, 2, cpus[-16+head//2]) for head in range(0, HEADS, 2)]
        with ThreadPoolExecutor(max_workers=len(groups)+1) as pool:
            futures = [pool.submit(run, work, *group) for group in groups]
            futures.append(pool.submit(run, work, 0, 1, cpus[0], True))
            runs = [future.result() for future in futures]
    assert not work.exists() and not stopped and all(sha256(Path(path)) == digest for path,digest in digests.items())
    logs = {name: log for name,_,log in runs} | {"verilator": lint.stdout + lint.stderr}
    with archive.open("xb") as stream:
        stream.write(gzip.compress(json.dumps(logs, sort_keys=True).encode(), mtime=0))
    assert json.loads(gzip.decompress(archive.read_bytes())) == logs
    successful = [record["inventory"] for name,record,_ in runs if name != "future_key_control"]
    total = {key: sum(result[key] for result in successful) for key in successful[0] if key != "first"}
    if mode == "full":
        assert total["live"] == fixture["selected_causal_scores"] and total["masked"] == fixture["masked_score_slots"]
        assert total["streaming"] == fixture["fixed_streaming_heads"]
    result = {"state": "trained_tile_batch_qualified", "scope": __doc__, "mode": mode,
              "elapsed_seconds": time.monotonic()-started, "actual_cores": 20, "compiled_memory_models": 600,
              "inventory": total, "runs": {name: data for name,data,_ in runs}, "source_and_fixture_sha256": digests,
              "native_logs_sha256": sha256(archive), "full_paper_results_matched": False}
    with report.open("x") as stream:
        stream.write(json.dumps(result, indent=2) + "\n")
    print(f"BATCH413_VERIFIED mode={mode} {total}", flush=True)


if __name__ == "__main__":
    main()
