"""Check autonomous scheduling of a complete trained attention-head prediction."""

from concurrent.futures import ThreadPoolExecutor
import gzip
import json
from pathlib import Path
import re
import subprocess
import tempfile

from run_tri_oracle_batch396_masks import GIB, check_memory, sha256
from tri_oracle_process_guard import terminate_process_group


ROOT = Path(__file__).resolve().parents[1]
TOP = "tri_oracle_attention415_head_tb"
MODULE = "tri_oracle_attention_head_predictor415"


def main():
    check_memory(14 * GIB)
    records = ROOT / "records"
    prior_path = records / "batch413_full_tile_result.json"
    fixture_path = records / "batch412_tiled_attention_fixture.json"
    prior, fixture = (json.loads(path.read_text()) for path in (prior_path, fixture_path))
    assert prior["state"] == "trained_tile_batch_qualified" and prior["mode"] == "full"
    assert prior["inventory"]["live"] == fixture["selected_causal_scores"] == 1312800
    assert prior["inventory"]["heads"] == 32 and prior["inventory"]["rows"] == 16320
    digests = prior["source_and_fixture_sha256"].copy()
    sources = [ROOT / "verilog" / f"tri_oracle_{name}.sv" for name in
               ("pe_array", "sram_memory_compute", "sram_compute_cluster", "compute_fabric", "batched_projection356",
                "batched_tensor390", "batch357_hierarchy", "attention_tile_batch413", "attention_head_classifier410")]
    sources += [Path(path) for path in digests if "/VERILOG/" in path and path.endswith(".v")]
    assert len(sources) == 12 and all(str(path) in digests for path in sources)
    module = ROOT / "verilog" / f"{MODULE}.sv"
    bench = ROOT / "verilog" / f"{TOP}.sv"
    digests.update({str(path): sha256(path) for path in (module, bench, prior_path, Path(__file__))})
    assert all(sha256(Path(path)) == digest for path, digest in digests.items())
    directory = Path(fixture["fixture"])
    counts = bytes.fromhex((directory / "counts.hex").read_text())[:1020]
    queries = bytes.fromhex((directory / "query.hex").read_text())[:510*64]
    assert len(counts) == 1020 and len(queries) == 510*64
    requests = 0
    for batch in fixture["batches"]:
        start, rows, recent = batch["query_first"], batch["queries"], batch["key_starts"][2]
        offset = (start-96)*64
        active_pairs = sum(any(any(queries[offset+row*64+pair*16:offset+row*64+pair*16+16])
                               for row in range(rows)) for pair in range(4))
        requests += rows*4 + (64+start+rows-recent)*active_pairs
    inventory = (f"BATCH415_PASS heads=1 rows=510 batches=32 inner={sum(counts[::2])} "
                 f"recent={sum(counts[1::2])} invalid=6 late_abort=1 ratio=1 requests={requests}")
    output = records / "batch415_head_schedule_result.json"
    archive = records / "batch415_native_logs.json.gz"
    assert not output.exists() and not archive.exists()

    def simulate(work, name, mutated, cpu):
        folder = work / name
        folder.mkdir()
        selected = module
        if mutated:
            selected = folder / module.name
            text = module.read_text()
            advance = "query_addr <= query_addr + (64'(batch_queries) << 6);"
            assert text.count(advance) == 1
            selected.write_text(text.replace(advance, "query_addr <= query_addr;"))
        bundle = folder / "bundle.sv"
        bundle.write_text('`define UNIT_DELAY\n`define TRI_ORACLE_SRAM_CLUSTER_BIND_PUBLIC\n' +
                          "".join(f'`include "{path}"\n' for path in (*sources, selected, bench)))
        command = ["taskset", "-c", str(cpu), "/opt/cadence/bin/xrun", "-64bit", "-sv", "-xmerror", "RECOME",
                   "-notimingchecks", "-top", TOP, "-top", "tri_oracle_batch357_hierarchy", str(bundle),
                   f"+FIXTURE={directory}"]
        log = folder / "console.log"
        with log.open("x") as stream:
            child = subprocess.Popen(command, cwd=folder, stdin=subprocess.DEVNULL, stdout=stream,
                                     stderr=subprocess.STDOUT, start_new_session=True)
            print(f"BATCH415_STARTED case={name} group={child.pid}", flush=True)
            try:
                status = child.wait(timeout=480)
            finally:
                terminate_process_group(child)
        content = log.read_text()
        assert content.splitlines().count("BATCH357_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=600") == 1
        if mutated:
            assert status != 0 and "BATCH415_PASS" not in content, content[-4500:]
            assert content.count("BATCH415_BAD_SCHEDULE position=112 count=16") == 1, content[-4500:]
        else:
            assert status == 0 and content.splitlines().count(inventory) == 1, content[-4500:]
            assert "Simulation complete via $finish" in content and not re.search(r"\*(?:E|F),", content)
        print(f"BATCH415_CHECKED case={name} status={status}", flush=True)
        return name, status, content

    with tempfile.TemporaryDirectory(dir=ROOT / ".cache", prefix="batch415_schedule_") as name:
        work = Path(name)
        lint = subprocess.run(["verilator", "--lint-only", "-Wall", "--top-module", MODULE,
                               *map(str, (module, sources[7], sources[8]))], cwd=work, capture_output=True,
                              text=True, timeout=30)
        assert lint.returncode == 0, lint.stdout + lint.stderr
        with ThreadPoolExecutor(max_workers=2) as pool:
            clean = pool.submit(simulate, work, "trained_head", False, 4)
            corrupt = pool.submit(simulate, work, "stale_query_base", True, 5)
            runs = [clean.result(), corrupt.result()]
    assert not work.exists() and all(sha256(Path(path)) == digest for path, digest in digests.items())
    logs = {name: log for name, _, log in runs} | {"verilator": lint.stdout + lint.stderr}
    with archive.open("xb") as stream:
        stream.write(gzip.compress(json.dumps(logs, sort_keys=True).encode(), mtime=0))
    assert json.loads(gzip.decompress(archive.read_bytes())) == logs
    report = {"state": "complete_trained_head_scheduling_verified", "scope": __doc__, "trained_heads": 1,
              "query_rows": 510, "batches": 32, "actual_cores": 20, "actual_compiled_memories": 600,
              "inner": sum(counts[::2]), "recent": sum(counts[1::2]), "read_requests": requests,
              "invalid_configs": 6, "late_abort_controls": 1, "ratio_controls": 1,
              "native_status_by_run": {name: status for name, status, _ in runs}, "native_logs_sha256": sha256(archive),
              "source_and_fixture_sha256": digests, "full_paper_results_matched": False}
    with output.open("x") as stream:
        stream.write(json.dumps(report, indent=2) + "\n")
    print(inventory, flush=True)


if __name__ == "__main__":
    main()
