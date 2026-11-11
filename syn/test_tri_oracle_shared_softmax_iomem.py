"""Verify that compute drains before softmax takes the shared memory."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import tempfile

from run_tri_oracle_softmax_iomem import ROOT, RTL, replace, sha

TOP = "tri_oracle_compute_cluster_tb"
CONTENTION = """
    // Keep a compute request presented while the full result queue drains.
    softmax_command.reserve = 1;
    cmd_valid = 1;
    repeat (3) begin
      @(negedge clk);
      if (cmd_ready !== 0 || softmax_response.granted !== 0 || out_valid !== 1)
        $fatal(1, "SOFTMAX_RESERVE_WITH_HELD_COMPUTE_RESULT");
    end
    target = accepted;
    require_full_rate = 1;
    ready_mode = 1;
    while (retired < target) @(negedge clk);
    require_full_rate = 0;
    if (softmax_response.granted !== 1 || cmd_ready !== 0 || accepted != target)
      $fatal(1, "SOFTMAX_EXCLUSIVE_GRANT");

    softmax_command.begin_row = 1;
    @(negedge clk);
    softmax_command.begin_row = 0;
    softmax_command.load = 1;
    softmax_command.slot = 0;
    softmax_command.in_score = 0;
    softmax_command.in_size = 1;
    @(negedge clk);
    softmax_command.load = 0;
    softmax_command.flush = 1;
    @(negedge clk);
    softmax_command.flush = 0;
    softmax_command.read_slot = 1;
    @(negedge clk);
    softmax_command.read_slot = 0;
    softmax_command.write_weight = 1;
    @(negedge clk);
    softmax_command.write_weight = 0;
    softmax_command.reciprocal = 29'(1 << 28);
    softmax_command.read_slot = 1;
    @(negedge clk);
    softmax_command.read_slot = 0;
    if (softmax_response.probability !== 16'hffff || cmd_ready !== 0 || accepted != target)
      $fatal(1, "SOFTMAX_SHARED_WORD_CORRUPTED");
    $display("SOFTMAX_IOMEM_CONTENTION_PASS drained=%0d probability=%0d", target, softmax_response.probability);
    cmd_valid = 0;
    softmax_command = '0;
    #2;
    if (cmd_ready !== 1 || softmax_response.granted !== 0)
      $fatal(1, "SOFTMAX_COMPUTE_GRANT_DID_NOT_RETURN");
"""


def bench_text():
    source = (RTL / "tri_oracle_sram_cluster_tb.sv").read_text()
    source = source.replace("dut.reduce_four", "dut.implementation.reduce_four")
    source = source.replace("dut.aggregate_memory", "dut.implementation.aggregate_memory")
    source = replace(source, "  tri_oracle_compute_cluster dut (", """  tri_oracle_softmax_bank_types::command_t softmax_command = '0;
  tri_oracle_softmax_bank_types::response_t softmax_response;
  tri_oracle_compute_cluster dut (
    .token_size_bank_command('0), .token_size_bank_result(),
    .merge_range_command('0), .merge_range_result(), .global_merge_word('0), .global_sign_counts('0),
    """)
    old = """    target = accepted;
    require_full_rate = 1;
    ready_mode = 1;
    while (retired < target) @(negedge clk);
    require_full_rate = 0;"""
    return replace(source, old, CONTENTION.rstrip())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", type=Path)
    parser.add_argument("--ignore-drain", action="store_true", help="Check that an early grant is rejected.")
    args = parser.parse_args()
    case = args.case.resolve()
    bundle = case / "bundle.sv"
    prepared = json.loads((case / "receipt.json").read_text())
    assert prepared["softmax"] == "shared_aggregator_iomem" and prepared["memory_models"] == "vendor"
    assert prepared["bundle"] == str(bundle)
    assert all(sha(Path(path)) == expected for path, expected in prepared["input_sha256"].items())
    with tempfile.TemporaryDirectory(dir=ROOT / ".cache", prefix="softmax_iomem_contention_") as folder:
        work = Path(folder)
        bench = work / f"{TOP}.sv"
        bench.write_text(bench_text())
        if args.ignore_drain:
            cluster = case / "tri_oracle_sram_compute_cluster.sv"
            mutated = work / cluster.name
            mutated.write_text(replace(cluster.read_text(),
                                       "softmax_command.reserve && count == 0 && !out_valid",
                                       "softmax_command.reserve"))
            content = replace(bundle.read_text(), str(cluster), str(mutated))
            bundle = work / "bundle.sv"
            bundle.write_text(content)
        run = subprocess.run([
            "/opt/cadence/bin/xrun", "-64bit", "-sv", "-nospecify", "-notimingchecks",
            "-xmerror", "RECOME", "-define", "TRI_ORACLE_CHECK_CLUSTER_MEMORY", "-top", TOP,
            str(bundle), str(bench),
        ], cwd=work, capture_output=True, text=True, timeout=120)
    log = run.stdout + run.stderr
    if args.ignore_drain:
        expected = "SOFTMAX_RESERVE_WITH_HELD_COMPUTE_RESULT"
        assert run.returncode == 2 and log.splitlines().count(expected) == 1, log[-7000:]
        print(expected)
        return
    assert run.returncode == 0 and not re.search(r"\*[EF],", log), log[-7000:]
    markers = [line for line in log.splitlines() if line.startswith(
        ("SOFTMAX_IOMEM_CONTENTION_PASS", "SRAM_CLUSTER_PASS"))]
    assert len(markers) == 2 and markers[0] == "SOFTMAX_IOMEM_CONTENTION_PASS drained=16 probability=65535", markers
    assert markers[1].startswith("SRAM_CLUSTER_PASS outputs=36 ")
    print("\n".join(markers))


if __name__ == "__main__":
    main()
