"""Replay the trained softmax fixture and check the five aggregator banks."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
RTL = ROOT / "verilog"
TOP = "tri_oracle_proportional_softmax_tb"
ARCHIVE = ROOT / "records/batch425_proportional_softmax_evidence.json.gz"
REFERENCE = ROOT / "records/batch425_proportional_softmax_result.json"
BANK_MONITOR = """
    int load_count [5], weight_count [5], output_count [5];
    always @(posedge clk) begin
        if (!rst_n || dut.begin_row) begin
            for (int bank = 0; bank < 5; bank++) begin
                load_count[bank] = 0;
                weight_count[bank] = 0;
                output_count[bank] = 0;
            end
        end else begin
            for (int bank = 0; bank < 5; bank++) begin
                if (dut.bank_load[bank]) load_count[bank]++;
                if (dut.bank_weight_write[bank]) weight_count[bank]++;
                if (dut.bank_output_read[bank]) output_count[bank]++;
            end
            if (out_valid && out_ready && out_last)
                for (int bank = 0; bank < 5; bank++) begin
                    int expected_count;
                    expected_count = (int'(dut.last_index) + 5 - bank) / 5;
                    if (load_count[bank] != expected_count || weight_count[bank] != expected_count ||
                        output_count[bank] != expected_count)
                        $fatal(1, "SOFTMAX_BANK_ACTIVITY bank=%0d load=%0d weight=%0d out=%0d expected=%0d",
                               bank, load_count[bank], weight_count[bank], output_count[bank], expected_count);
                end
        end
    end
"""

LATENCY_MONITOR = """
    int elapsed;
    bit output_seen;
    always @(posedge clk) begin
        if (!rst_n || (in_valid && in_ready)) begin
            elapsed = 0;
            output_seen = 0;
        end else if (out_valid) begin
            if (!output_seen && cfg_length == 1024)
                $display("SOFTMAX_LONG_ROW_CYCLES %0d", elapsed + 1);
            output_seen = 1;
        end else if (row_active && inputs_pending == 0 && !output_seen) begin
            elapsed++;
            if (elapsed > 2 * ((int'(cfg_length) + 4) / 5) + 57)
                $fatal(1, "SOFTMAX_AGGREGATOR_WEIGHT_LATENCY length=%0d", cfg_length);
        end
    end
"""


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def require_reference_hash(path, reference):
    expected, = (digest for name, digest in reference["inputs_sha256"].items()
                 if Path(name).name == path.name)
    assert sha(path) == expected, path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy", action="store_true", help="Run the original single-bank control.")
    args = parser.parse_args()
    prior = json.loads(REFERENCE.read_text())
    assert sha(ARCHIVE) == prior["native_evidence_sha256"]
    with gzip.open(ARCHIVE, "rt") as stream:
        vectors = json.load(stream)["vectors"]
    assert hashlib.sha256(vectors.encode()).hexdigest() == prior["fixture_sha256"]
    source = RTL / "tri_oracle_proportional_softmax.sv"
    bench_path = RTL / f"{TOP}.sv"
    for path in (source, bench_path):
        require_reference_hash(path, prior)
    bench = bench_path.read_text()
    assert bench.count("endmodule") == 1
    if args.legacy:
        sources = [source]
        monitor = LATENCY_MONITOR
    else:
        sources = [RTL / "tri_oracle_softmax_bank.sv", RTL / "tri_oracle_aggregator_softmax.sv"]
        assert bench.count("tri_oracle_proportional_softmax dut") == 1
        bench = bench.replace("tri_oracle_proportional_softmax dut", "tri_oracle_aggregator_softmax dut")
        monitor = LATENCY_MONITOR + BANK_MONITOR
    bench = bench.replace("endmodule", monitor + "endmodule")
    with tempfile.TemporaryDirectory(dir=ROOT / ".cache", prefix="aggregator_softmax_") as directory:
        work = Path(directory)
        fixture = work / "vectors.txt"
        testbench = work / f"{TOP}.sv"
        fixture.write_text(vectors)
        testbench.write_text(bench)
        result = subprocess.run([
            "/opt/cadence/bin/xrun", "-64bit", "-sv", "-xmerror", "RECOME", "-top", TOP,
            *map(str, sources), str(testbench), f"+FIXTURE={fixture}",
        ], cwd=work, capture_output=True, text=True, timeout=120)
    log = result.stdout + result.stderr
    if args.legacy:
        assert result.returncode == 2 and "SOFTMAX_AGGREGATOR_WEIGHT_LATENCY" in log, log[-3000:]
        print(next(line for line in log.splitlines() if line.startswith("SOFTMAX_AGGREGATOR_WEIGHT_LATENCY")))
    else:
        assert result.returncode == 0 and log.splitlines().count(prior["simulation_marker"]) == 1, log[-3000:]
        print(prior["simulation_marker"])
        long_rows = [int(line.split()[1]) for line in log.splitlines() if line.startswith("SOFTMAX_LONG_ROW_CYCLES ")]
        assert len(long_rows) == vectors.splitlines().count("1024"), long_rows
        print("SOFTMAX_1024_KEY_FIRST_OUTPUT_CYCLES", min(long_rows), max(long_rows), len(long_rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
