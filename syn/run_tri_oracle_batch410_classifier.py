"""Qualify the attention-head classifier on frozen trained scores and boundaries."""

from concurrent.futures import ThreadPoolExecutor
import gzip
import json
from pathlib import Path
import subprocess
import tempfile

from run_tri_oracle_batch396_masks import GIB, check_memory, sha256
from tri_oracle_process_guard import terminate_process_group


ROOT = Path(__file__).resolve().parents[1]
TOP = "tri_oracle_attention410_classifier_tb"
MODULE = "tri_oracle_attention_head_classifier410"
PASS = "BATCH410_PASS heads=32 rows=480 scores=46080 streaming=4 max_rows=4096 fault_controls=3 cutoff_controls=4"
CONTROLS = {
    "inclusive_cutoff": ("}) > cutoff", "}) >= cutoff", "got=3/4 streaming=0 error=0"),
    "inclusive_ratio": ("outer_product > inner_product", "outer_product >= inner_product",
                        "got=2/3 streaming=1 error=0"),
    "unweighted_ratio": ("outer_product > inner_product", "total_outer > total_inner",
                         "got=2/3 streaming=1 error=0"),
}


def simulate(work, name, text, bench, fixture):
    directory = work / name
    directory.mkdir()
    source = directory / f"{MODULE}.sv"
    source.write_text(text)
    log = directory / "console.log"
    command = ["/opt/cadence/bin/xrun", "-64bit", "-sv", "-top", TOP,
               str(source), str(bench), f"+FIXTURE={fixture}"]
    with log.open("x") as stream:
        process = subprocess.Popen(command, cwd=directory, stdout=stream, stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL, start_new_session=True)
        try:
            status = process.wait(timeout=45)
        finally:
            terminate_process_group(process)
    content = log.read_text()
    if name == "trained_and_directed":
        assert status == 0 and content.splitlines().count(PASS) == 1, content
        assert "BATCH410_HEAD expected=" not in content, content
    else:
        expected = f"BATCH410_HEAD expected=2/3 {CONTROLS[name][2]}"
        assert status != 0 and content.count(expected) == 1 and PASS not in content, content
    return name, status, content


def main():
    check_memory(12 * GIB)
    fixture_record = ROOT / "records/batch409_attention_fixture.json"
    fixture = json.loads(fixture_record.read_text())
    assert fixture["state"] == "trained_rotary_attention_fixture_cpu_cuda_equal"
    assert (fixture["query_heads"], len(fixture["query_positions"]), fixture["tile_keys"],
            fixture["exact_precomputed_tile_scores"], fixture["fixed_streaming_heads"]) == (32, 15, 32, 46080, 4)
    directory = Path(fixture["fixture"])
    paths = [directory / f"{name}.hex" for name in ("scores", "alpha", "counts", "streaming")]
    digests = {str(path): fixture["files_sha256"][str(path)] for path in paths}
    source = ROOT / f"verilog/{MODULE}.sv"
    bench = ROOT / f"verilog/{TOP}.sv"
    dependencies = [source, bench, fixture_record, Path(__file__),
                    ROOT / "syn/run_tri_oracle_batch396_masks.py", ROOT / "syn/tri_oracle_process_guard.py"]
    digests.update({str(path): sha256(path) for path in dependencies})
    assert all(sha256(Path(path)) == digest for path, digest in digests.items())
    report = ROOT / "records/batch410_classifier_result.json"
    archive = ROOT / "records/batch410_native_logs.json.gz"
    assert not report.exists() and not archive.exists()
    text = source.read_text()
    cases = {"trained_and_directed": text}
    for name, (old, new, _) in CONTROLS.items():
        assert text.count(old) == 1, old
        cases[name] = text.replace(old, new)

    with tempfile.TemporaryDirectory(dir=ROOT / ".cache", prefix="batch410_qualification_") as temp:
        work = Path(temp)
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(simulate, work, name, rtl, bench, directory) for name, rtl in cases.items()]
            runs = [future.result() for future in futures]
        lint = subprocess.run(["verilator", "--lint-only", "-Wall", "--top-module", MODULE, str(source)],
                              cwd=work, capture_output=True, text=True, timeout=30)
        assert lint.returncode == 0, lint.stdout + lint.stderr
    assert not work.exists()
    assert all(sha256(Path(path)) == digest for path, digest in digests.items())
    logs = {name: content for name, _, content in runs} | {"verilator": lint.stdout + lint.stderr}
    with archive.open("xb") as stream:
        stream.write(gzip.compress(json.dumps(logs, sort_keys=True).encode(), mtime=0))
    assert json.loads(gzip.decompress(archive.read_bytes())) == logs
    result = {
        "state": "trained_attention_classification_from_precomputed_scores_verified",
        "scope": __doc__, "trained_heads": 32, "trained_rows": 480, "compared_input_scores": 46080,
        "streaming_heads": 4, "maximum_rows_tested": 4096, "fault_controls": 3, "cutoff_controls": 4,
        "exit_status_by_run": {name: status for name, status, _ in runs} | {"verilator": lint.returncode},
        "source_and_fixture_sha256": digests, "native_logs_sha256": sha256(archive),
        "hardware_score_generation_verified": False, "full_paper_results_matched": False,
    }
    with report.open("x") as stream:
        stream.write(json.dumps(result, indent=2) + "\n")
    print(PASS, flush=True)


if __name__ == "__main__":
    main()
