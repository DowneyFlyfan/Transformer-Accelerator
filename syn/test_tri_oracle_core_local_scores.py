"""Check one-core score arithmetic and physical issue across all five clusters."""

import argparse
from collections import Counter
from pathlib import Path
import re
import subprocess
import tempfile

from prepare_tri_oracle_wac_softmax_layer import ROOT, RTL, edit, read, sha, verify

TOP = "tri_oracle_cluster_local_tensor_tb"
PASS = "CORE_TENSOR_PASS clusters=5 score_outputs=42 matrix_commands=40"
WITNESS = """
module core_score_directed_witness (input logic clk, rst_n, cmd_valid, cmd_ready);
    always @(posedge clk) if (rst_n && cmd_valid && cmd_ready)
        $display("CORE_SCORE_DIRECTED %m");
endmodule
bind tri_oracle_sram_strip_core448 core_score_directed_witness core_score_witness (.*);
"""
ISSUE = re.compile(
    rf"CORE_SCORE_DIRECTED {TOP}\.dut\.fabric\.clusters\[([0-4])\]\.unit\.selected_bank([0-4])\.block_instance"
    r"\.source_cluster\.implementation\.cores\[([0-3])\]\.core_score_witness"
)


def bench_text(original):
    text = edit(original, "softmax_request.score_tile = 1;", "softmax_request.score_tile = 1;\n            softmax_request.score_core = 1;")
    text = edit(text, "5'(cluster*4+3)", "5'(cluster*4+(cluster+1)%4)")
    text = edit(text, "issues[cluster] != 2", "issues[cluster] != 8")
    text = edit(text, "query_reads != 4 || key_reads != 4 * int'(cfg_count)", "query_reads != 1 || key_reads != int'(cfg_count)")
    return edit(text, "CLUSTER_TENSOR_PASS clusters=5 score_outputs=42 matrix_commands=10", PASS) + WITNESS


def run(case, log_path, wrong_result_core=False):
    setup = read(case / "receipt.json")
    assert setup["score_tiles"] == "single_core_or_head_cluster"
    inputs = setup["input_sha256"].copy()
    verify(inputs)
    bench = RTL / f"{TOP}.sv"
    inputs[str(bench)] = sha(bench)
    bundle = case / "bundle.sv"
    assert str(bundle) == setup["bundle"] and str(bundle) in inputs
    memory = next(int(line.split()[1]) * 1024 for line in Path("/proc/meminfo").read_text().splitlines()
                  if line.startswith("MemAvailable:"))
    assert memory >= 16 * 2**30
    with tempfile.TemporaryDirectory(dir=ROOT / ".cache", prefix="score_core_directed_") as directory:
        work = Path(directory)
        path = work / "test.sv"
        path.write_text(bench_text(bench.read_text()))
        if wrong_result_core:
            original = case / "tri_oracle_sram_compute_cluster.sv"
            changed = work / original.name
            changed.write_text(edit(original.read_text(), "result_words[1024*int'(selected_core)+row*32+:32]",
                                    "result_words[row*32+:32]"))
            candidate = work / "bundle.sv"
            candidate.write_text(edit(bundle.read_text(), str(original), str(changed)))
            bundle = candidate
        result = subprocess.run([
            "/usr/bin/prlimit", "--as=1342177280", "--", "/opt/cadence/bin/xrun", "-64bit", "-sv",
            "-nospecify", "-notimingchecks", "-sequdp_nba_delay", "-xmerror", "RECOME",
            "-top", TOP, str(bundle), str(path),
        ], cwd=directory, capture_output=True, text=True, timeout=180)
    log = result.stdout + result.stderr
    if log_path is not None:
        with log_path.open("x") as stream:
            stream.write(log)
    if wrong_result_core:
        assert result.returncode == 2 and "CLUSTER_TENSOR_SCORE cluster=0 lane=0" in log and PASS not in log, log[-5000:]
        verify(inputs)
        print("CORE_TENSOR_WRONG_RESULT_CORE_REJECTED")
        return
    assert result.returncode == 0 and not re.search(r"\*[EF],", log), log[-5000:]
    lines = log.splitlines()
    assert lines.count(PASS) == 1
    hits = Counter()
    for line in lines:
        if line.startswith("CORE_SCORE_DIRECTED "):
            match = ISSUE.fullmatch(line)
            assert match, line
            cluster, selected, core = map(int, match.groups())
            assert cluster == selected
            hits[cluster, core] += 1
    assert hits == {(cluster, (cluster + 1) % 4): 8 for cluster in range(5)}, hits
    verify(inputs)
    print(PASS)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", type=Path)
    parser.add_argument("--log", type=Path)
    parser.add_argument("--wrong-result-core", action="store_true")
    args = parser.parse_args()
    run(args.case.resolve(), args.log, args.wrong_result_core)
