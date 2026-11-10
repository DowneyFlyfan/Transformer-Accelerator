"""Check all trained merge maps and causal prefixes in Cadence Xcelium."""

from bisect import bisect_right
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
from tri_oracle_token_merging_reference import merge_signs


ROOT = Path(__file__).resolve().parents[1]
TOP = "tri_oracle_trained420_merger_tb"
TOKENS, LAYERS, FEATURES, GRID = 576, 22, 2048, 24
REVISIT = (288, 0, 575, 23, 575)


def main():
    check_memory(14*GIB)
    records = ROOT / "records"
    prior = records / "batch419_trained_merger_fixture.json"
    fixture = json.loads(prior.read_text())
    assert fixture["state"] == "trained_image_token_merge_maps_cpu_cuda_equal_on_anchor"
    assert (fixture["image_width"], fixture["image_height"], fixture["tokens_per_image_layer"],
            fixture["layers_per_image"], fixture["sign_features"], fixture["anchor_cpu_cuda_map_comparisons"]) == (
                GRID, GRID, TOKENS, LAYERS, FEATURES, 6*LAYERS*TOKENS)
    thresholds = fixture["minimum_matches_inclusive"]
    assert thresholds == [1332, 1434, 1536, 1639, 1741, 1844]
    directory = Path(fixture["fixture"])
    consumed = {directory / "signs.hex", *(directory / f"map_{threshold}.hex" for threshold in thresholds)}
    assert set(fixture["files_sha256"]) == {str(path) for path in consumed}
    merger, causal, bench = [ROOT / "verilog" / f"tri_oracle_{name}.sv" for name in
                           ("token_merger", "causal_token_size", "trained420_merger_tb")]
    digests = fixture["files_sha256"].copy()
    for path in (merger, causal, bench, prior, Path(__file__), ROOT / "syn/tri_oracle_token_merging_reference.py",
                 ROOT / "syn/tri_oracle_process_guard.py", ROOT / "syn/run_tri_oracle_batch396_masks.py"):
        digest = sha256(path)
        assert fixture["source_sha256"].get(str(path), digest) == digest
        digests[str(path)] = digest
    assert all(sha256(Path(path)) == digest for path, digest in digests.items())
    words = [int(value, 16) for value in (directory / "signs.hex").read_text().splitlines()]
    assert len(words) == LAYERS*TOKENS and all(word.bit_length() <= FEATURES for word in words)
    maps = {}
    for threshold in thresholds:
        encoded = [int(value, 16) for value in (directory / f"map_{threshold}.hex").read_text().splitlines()]
        assert len(encoded) == LAYERS*TOKENS
        maps[threshold] = [encoded[start:start+TOKENS] for start in range(0, len(encoded), TOKENS)]
        for layer, expected in enumerate(maps[threshold]):
            roots, kinds = merge_signs(words[layer*TOKENS:(layer+1)*TOKENS], GRID, FEATURES, threshold)
            assert [(kind << 10) | root for root, kind in zip(roots, kinds, strict=True)] == expected

    def expectation(threshold, first, count):
        result = {"threshold": threshold, "first": first, "layers": count, "maps": count*TOKENS,
                  "left": 0, "up": 0, "global": 0, "rows": count*(TOKENS+len(REVISIT)), "sizes": 0}
        for mapping in maps[threshold][first:first+count]:
            kinds = [value >> 10 for value in mapping]
            roots = [index for index, kind in enumerate(kinds) if kind == 0]
            result["left"] += kinds.count(1)
            result["up"] += kinds.count(2)
            result["global"] += len(roots)
            # Each root is visible in every forward query at or after its original position.
            result["sizes"] += sum(TOKENS-root for root in roots) + sum(bisect_right(roots, position) for position in REVISIT)
        return result

    control_threshold = 1536
    control = None
    for layer, expected in enumerate(maps[control_threshold]):
        roots, kinds = merge_signs(words[layer*TOKENS:(layer+1)*TOKENS], GRID, FEATURES, control_threshold+1)
        strict = [(kind << 10) | root for root, kind in zip(roots, kinds, strict=True)]
        first_change = next((index for index, (a,b) in enumerate(zip(expected, strict, strict=True)) if a != b), None)
        if first_change is not None:
            control = (layer, first_change, expected[first_change], strict[first_change])
            break
    assert control is not None
    report = records / "batch420_trained_merger_result.json"
    archive = records / "batch420_native_logs.json.gz"
    assert not report.exists() and not archive.exists()
    cpus = sorted(os.sched_getaffinity(0))
    jobs = [(threshold, first, min(8, LAYERS-first)) for threshold in thresholds for first in range(0, LAYERS, 8)]
    assert len(cpus) >= len(jobs)+1
    started = time.monotonic()
    stopped = False

    def stop(_signal, _frame):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    def simulate(work, cpu, threshold, first, count, strict_threshold=False):
        name = "exclusive_threshold_control" if strict_threshold else f"threshold_{threshold}_layers_{first:02}"
        folder = work / name
        folder.mkdir()
        source = merger
        if strict_threshold:
            source = folder / merger.name
            text = merger.read_text()
            assert text.count(">= THRESHOLD_W") == 2
            source.write_text(text.replace(">= THRESHOLD_W", "> THRESHOLD_W"))
        command = ["taskset", "-c", str(cpu), "/opt/cadence/bin/xrun", "-64bit", "-sv", "-xmerror", "RECOME", "-top", TOP,
                   "-defparam", f"{TOP}.THRESHOLD={threshold}", "-defparam", f"{TOP}.FIRST_LAYER={first}",
                   "-defparam", f"{TOP}.LAYERS={count}", str(source), str(causal), str(bench), f"+FIXTURE={directory}"]
        log = folder / "console.log"
        start = time.monotonic()
        with log.open("x") as stream:
            worker = subprocess.Popen(command, cwd=folder, stdout=stream, stderr=subprocess.STDOUT,
                                      stdin=subprocess.DEVNULL, start_new_session=True)
            print(f"BATCH420_STARTED case={name} group={worker.pid} cpu={cpu}", flush=True)
            try:
                while worker.poll() is None:
                    check_memory(8*GIB)
                    assert not stopped and time.monotonic()-start < 300, name
                    time.sleep(0.5)
            finally:
                terminate_process_group(worker)
        content = log.read_text()
        if strict_threshold:
            layer, token, expected, actual = control
            marker = f"BATCH420_WRONG_MAP layer={layer} token={token} got={actual:03x} expected={expected:03x}"
            assert worker.returncode != 0 and content.count(marker) == 1 and "BATCH420_PASS" not in content, content[-4000:]
            inventory = {"layer": layer, "token": token, "inclusive": expected, "exclusive": actual}
        else:
            markers = re.findall(r"^BATCH420_PASS (.+)$", content, re.M)
            assert worker.returncode == 0 and len(markers) == 1 and not re.search(r"\*(?:E|F),", content), content[-4000:]
            inventory = {key: int(value) for key,value in (word.split("=") for word in markers[0].split())}
            stalls = inventory.pop("stalls")
            assert stalls > 0 and inventory == expectation(threshold, first, count), (inventory, expectation(threshold, first, count))
            inventory["stalls"] = stalls
        print(f"BATCH420_CHECKED case={name} status={worker.returncode}", flush=True)
        return name, {"native_status": worker.returncode, "inventory": inventory,
                      "elapsed_seconds": time.monotonic()-start, "log_sha256": sha256(log)}, content

    with tempfile.TemporaryDirectory(dir=ROOT / ".cache", prefix="batch420_build_") as name:
        work = Path(name)
        with ThreadPoolExecutor(max_workers=len(jobs)+1) as pool:
            futures = [pool.submit(simulate, work, cpu, *job) for cpu,job in zip(cpus, jobs)]
            futures.append(pool.submit(simulate, work, cpus[len(jobs)], control_threshold, control[0], 1, True))
            runs = [future.result() for future in futures]
    assert not work.exists() and not stopped
    assert all(sha256(Path(path)) == digest for path, digest in digests.items())
    logs = {name: content for name,_,content in runs}
    with archive.open("xb") as stream:
        stream.write(gzip.compress(json.dumps(logs, sort_keys=True).encode(), mtime=0))
    assert json.loads(gzip.decompress(archive.read_bytes())) == logs
    inventories = [entry["inventory"] for name,entry,_ in runs if name != "exclusive_threshold_control"]
    total = {key: sum(item[key] for item in inventories) for key in
             ("layers", "maps", "left", "up", "global", "rows", "sizes", "stalls")}
    assert total["layers"] == LAYERS*len(thresholds) and total["maps"] == fixture["anchor_cpu_cuda_map_comparisons"]
    result = {"state": "trained_image_token_merger_and_causal_prefixes_verified", "scope": __doc__,
              "anchor_question_id": fixture["anchor_question_id"], "image_tokens": TOKENS, "sign_features": FEATURES,
              "layers": LAYERS, "thresholds": thresholds, "inventory": total, "elapsed_seconds": time.monotonic()-started,
              "runs": {name: entry for name,entry,_ in runs}, "source_and_fixture_sha256": digests,
              "native_logs_sha256": sha256(archive), "full_paper_results_matched": False}
    with report.open("x") as stream:
        stream.write(json.dumps(result, indent=2) + "\n")
    print(f"BATCH420_VERIFIED {total}", flush=True)


if __name__ == "__main__":
    main()
