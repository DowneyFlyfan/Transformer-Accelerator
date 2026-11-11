"""Replay the weight-attention core softmax with two compiled input banks."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile

from run_tri_oracle_aggregator_softmax import ARCHIVE, REFERENCE, ROOT, RTL, TOP, require_reference_hash, sha
from run_tri_oracle_softmax_iomem import replace

MEMORY = ROOT / (
    ".cache/physical/sram/activation_cache_banks_01/ts5n28hpcpsvta512x64m4f_130a/VERILOG/"
    "ts5n28hpcpsvta512x64m4f_130a_tt1v25c.v"
)
MODEL = "TS5N28HPCPSVTA512X64M4F"
MODEL_SHA256 = "76ecb4e15b3b132b073e4604ef05565524a5b80820e5396462ac91d44b098e1a"
CORE = "tri_oracle_wac_softmax"
ADAPTER = RTL / "tri_oracle_wac_softmax_imem.sv"
PORTS = """output logic [1:0] mem_ce_n, mem_we_n,
    output logic [8:0] mem_address,
    output logic [1:0][63:0] mem_d,
    input logic [1:0][63:0] mem_q"""
MONITOR = """
    int score_writes, weight_writes, score_reads, weight_reads;
    always @(posedge clk) begin
        if (!rst_n || (cfg_valid && cfg_ready)) begin
            score_writes = 0;
            weight_writes = 0;
            score_reads = 0;
            weight_reads = 0;
        end else begin
            if (!dut.mem_ce_n[0]) begin
                if (dut.mem_we_n[0]) score_reads++;
                else score_writes++;
            end
            if (!dut.mem_ce_n[1]) begin
                if (dut.mem_we_n[1]) weight_reads++;
                else weight_writes++;
            end
            if (out_valid && out_ready && out_last) begin
                int keys;
                keys = int'(dut.simd.last_index) + 1;
                if (score_writes != (keys + 1) / 2 || weight_writes != (keys + 1) / 2 ||
                    score_reads != keys || weight_reads != keys)
                    $fatal(1, "WAC_IMEM_ACCESS_COUNTS keys=%0d sw=%0d ww=%0d sr=%0d wr=%0d",
                           keys, score_writes, weight_writes, score_reads, weight_reads);
            end
        end
    end
"""


def source(text):
    text = replace(text, "module tri_oracle_proportional_softmax (", f"module {CORE} (")
    text = replace(text, "output logic out_last\n);", f"output logic out_last,\n    {PORTS}\n);")
    text = replace(text, "    // Reuse the single port to replace each packed size/score with its weight.\n"
                   "    logic [29:0] scratch [MAX_KEYS];\n", "")
    start = text.index("    always_ff @(posedge clk) begin")
    end = text.index("    always_ff @(posedge clk or negedge rst_n)", start)
    storage = """    tri_oracle_wac_softmax_imem storage (
        .clk, .index, .last_key(index == last_index),
        .load_score(rst_n && state == LOAD && in_valid),
        .read_score(rst_n && state == READ_SCORE),
        .store_weight(rst_n && state == WRITE_WEIGHT),
        .read_weight(rst_n && state == READ_OUTPUT),
        .score({in_size, in_size == 0 ? 16'd0 : in_score}), .weight(weighted),
        .read_data, .mem_ce_n, .mem_we_n, .mem_address, .mem_d, .mem_q
    );

"""
    return text[:start] + storage + text[end:]


def wrapper(text):
    ports = text.split("module tri_oracle_proportional_softmax (", 1)[1].split(");", 1)[0]
    return f"""`timescale 1ns/1ps
module {CORE}_test ({ports});
    logic [1:0] mem_ce_n, mem_we_n;
    logic [8:0] mem_address;
    logic [1:0][63:0] mem_d, mem_q;
    {CORE} simd (.*);
    for (genvar bank = 0; bank < 2; bank++) begin : imem
        {MODEL} memory (
            .CLK(clk), .CEB(mem_ce_n[bank]), .WEB(mem_we_n[bank]),
            .A(mem_address), .D(mem_d[bank]), .Q(mem_q[bank])
        );
    end
endmodule
module wac_imem_probe;
    initial $display("WAC_IMEM_MODEL %m");
endmodule
bind {MODEL} wac_imem_probe probe ();
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--omit-tail", action="store_true", help="Verify rejection of an unwritten odd-length tail.")
    args = parser.parse_args()
    reference = json.loads(REFERENCE.read_text())
    assert sha(ARCHIVE) == reference["native_evidence_sha256"]
    assert sha(MEMORY) == MODEL_SHA256
    original = RTL / "tri_oracle_proportional_softmax.sv"
    bench = RTL / f"{TOP}.sv"
    for path in (original, bench):
        require_reference_hash(path, reference)
    with gzip.open(ARCHIVE, "rt") as stream:
        vectors = json.load(stream)["vectors"]
    assert hashlib.sha256(vectors.encode()).hexdigest() == reference["fixture_sha256"]
    with tempfile.TemporaryDirectory(prefix="wac_softmax_imem_", dir=ROOT / ".cache") as directory:
        work = Path(directory)
        original_text = original.read_text()
        bench_text = replace(bench.read_text(), "tri_oracle_proportional_softmax dut", f"{CORE}_test dut")
        (work / "bench.sv").write_text(replace(bench_text, "endmodule", MONITOR + "endmodule"))
        (work / "simd.sv").write_text(source(original_text))
        (work / "wrapper.sv").write_text(wrapper(original_text))
        (work / "vectors.txt").write_text(vectors)
        adapter = ADAPTER
        if args.omit_tail:
            adapter = work / ADAPTER.name
            adapter.write_text(replace(ADAPTER.read_text(), "index[0] || last_key", "index[0]"))
        run = subprocess.run(["/opt/cadence/bin/xrun", "-64bit", "-sv", "-define", "UNIT_DELAY",
                              "-nospecify", "-notimingchecks", "-sequdp_nba_delay", "-xmerror", "RECOME",
                              "-top", TOP, str(MEMORY), str(adapter), "simd.sv", "wrapper.sv", "bench.sv",
                              "+FIXTURE=vectors.txt"], cwd=work, capture_output=True, text=True, timeout=120)
        log = run.stdout + run.stderr
    if args.omit_tail:
        expected = "SOFTMAX_MISMATCH row=0 key=0 observed=x expected=16384 last=0"
        assert run.returncode == 2 and expected in log and reference["simulation_marker"] not in log, log[-5000:]
        print("WAC_IMEM_UNWRITTEN_TAIL_REJECTED", expected)
        return
    assert run.returncode == 0 and not re.search(r"\*[EF],", log), log[-5000:]
    lines = log.splitlines()
    version = re.search(r"^TOOL:\s+xrun\(64\)\s+(25\.03-\w+): Started", log, re.M)
    assert version, log[:1200]
    assert lines.count(reference["simulation_marker"]) == 1
    assert {line for line in lines if line.startswith("WAC_IMEM_MODEL ")} == {
        f"WAC_IMEM_MODEL {TOP}.dut.imem[{bank}].memory.probe" for bank in range(2)
    }
    print(reference["simulation_marker"])
    print("WAC_IMEM_XCELIUM", version[1], "MODEL_SHA256", MODEL_SHA256)


if __name__ == "__main__":
    main()
