"""Exercise packed softmax storage through the installed aggregator memory model."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile

from run_tri_oracle_aggregator_softmax import ARCHIVE, BANK_MONITOR, LATENCY_MONITOR, REFERENCE, ROOT, RTL, TOP, sha

MEMORY = ROOT / (
    ".cache/physical/sram/core_outputs_01/ts6n28hpcpsvta16x128m2f_130a/VERILOG/"
    "ts6n28hpcpsvta16x128m2f_130a_tt1v25c.v"
)
ACCESS_MONITOR = """
    for (genvar bank = 0; bank < 5; bank++) begin : check_iomem
        int writes, reads;
        bit [63:0] written_lines;
        always @(posedge clk) begin
            if (!rst_n || dut.begin_row) begin
                writes = 0;
                reads = 0;
                written_lines = '0;
            end else begin
                if (dut.aggregator[bank].read_valid) begin
                    if (!written_lines[dut.aggregator[bank].read_line])
                        $fatal(1, "SOFTMAX_IOMEM_UNWRITTEN_READ bank=%0d line=%0d",
                               bank, dut.aggregator[bank].read_line);
                    reads++;
                end
                if (dut.aggregator[bank].write_valid) begin
                    written_lines[dut.aggregator[bank].write_line] = 1;
                    writes++;
                end
                if (out_valid && out_ready && out_last) begin
                    int keys;
                    keys = (int'(dut.last_index) + 5 - bank) / 5;
                    if (writes != keys + (keys + 3) / 4 || reads != 2 * keys)
                        $fatal(1, "SOFTMAX_IOMEM_ACCESS_COUNT bank=%0d keys=%0d writes=%0d reads=%0d",
                               bank, keys, writes, reads);
                end
            end
        end
    end
"""


def replace(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new)


def bank_arithmetic():
    """Retain the checked arithmetic and replace only its scratch-array interface."""
    old = (RTL / "tri_oracle_softmax_bank.sv").read_text()
    text = replace(old, "module tri_oracle_softmax_bank #(\n    parameter int ENTRIES = 205\n) (",
                   "module tri_oracle_softmax_iomem_bank (")
    start = text.index("    logic [29:0] scratch")
    end = text.index("    // round(", start)
    text = text[:start] + text[end:]
    text = replace(text, "    output logic [15:0] probability\n);", """    output logic [15:0] probability,
    input  logic flush,
    output logic write_valid, read_valid,
    output logic [5:0] write_line, read_line,
    output logic [127:0] write_data,
    input  logic [3:0][127:0] memory_q
);
    logic [29:0] read_data;
""")
    start = text.index("    always_ff @(posedge clk) begin")
    end = text.index("    always_ff @(posedge clk or negedge rst_n)", start)
    adapter = """    tri_oracle_softmax_iomem storage (
        .clk, .rst_n, .begin_row, .load, .slot, .in_score, .in_size,
        .read_slot, .write_weight, .weighted, .flush,
        .write_valid, .read_valid, .write_line, .read_line, .write_data, .memory_q, .read_data
    );

"""
    return text[:start] + adapter + text[end:]


def standalone_top(omit_tail):
    """Use the same 16-by-128 macro type as the cluster's result storage."""
    source = (RTL / "tri_oracle_aggregator_softmax.sv").read_text()
    text = replace(source, "module tri_oracle_aggregator_softmax (", "module tri_oracle_aggregator_softmax_iomem (")
    start = text.index("        tri_oracle_softmax_bank #")
    end = text.index("\n    end", start)
    original = text[start:end]
    flush = "state == REDUCE_MAX && bank != 0" if omit_tail else "state == REDUCE_MAX"
    bank = replace(original, "tri_oracle_softmax_bank #(.ENTRIES(ENTRIES))", "tri_oracle_softmax_iomem_bank")
    bank = replace(bank, ".probability(bank_probability[bank])", f""".probability(bank_probability[bank]),
            .flush({flush}), .write_valid, .read_valid, .write_line, .read_line, .write_data, .memory_q""")
    memory = """        logic write_valid, read_valid;
        logic [5:0] write_line, read_line;
        logic [127:0] write_data;
        logic [3:0][127:0] memory_q;
        for (genvar macro = 0; macro < 4; macro++) begin : local_result_memory
            TS6N28HPCPSVTA16X128M2F memory (
                .CLKW(clk), .CLKR(clk),
                .WEB(!(write_valid && write_line[5:4] == 2'(macro))),
                .REB(!(read_valid && read_line[5:4] == 2'(macro))),
                .AA(write_line[3:0]), .AB(read_line[3:0]), .D(write_data), .Q(memory_q[macro])
            );
        end
"""
    text = text[:start] + memory + bank + text[end:]
    return replace(text, "        localparam int ENTRIES = (MAX_KEYS + BANKS - 1 - bank) / BANKS;\n", "")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--omit-tail", action="store_true", help="Exercise rejection of an unwritten partial line.")
    args = parser.parse_args()
    prior = json.loads(REFERENCE.read_text())
    assert sha(ARCHIVE) == prior["native_evidence_sha256"]
    assert sha(MEMORY) == "80450a3b83a12bf99c98cb6b47d56dcd41ac4895cb1f14257081a3cf31b5b450"
    with gzip.open(ARCHIVE, "rt") as stream:
        vectors = json.load(stream)["vectors"]
    assert hashlib.sha256(vectors.encode()).hexdigest() == prior["fixture_sha256"]
    bench = replace((RTL / f"{TOP}.sv").read_text(), "tri_oracle_proportional_softmax dut",
                    "tri_oracle_aggregator_softmax_iomem dut")
    monitor = LATENCY_MONITOR + BANK_MONITOR + ACCESS_MONITOR
    bench = replace(bench, "endmodule", monitor + "endmodule")
    with tempfile.TemporaryDirectory(dir=ROOT / ".cache", prefix="softmax_iomem_") as directory:
        work = Path(directory)
        fixture = work / "vectors.txt"
        fixture.write_text(vectors)
        testbench = work / f"{TOP}.sv"
        testbench.write_text(bench)
        arithmetic = work / "tri_oracle_softmax_iomem_bank.sv"
        arithmetic.write_text(bank_arithmetic())
        top = work / "tri_oracle_aggregator_softmax_iomem.sv"
        top.write_text(standalone_top(args.omit_tail))
        run = subprocess.run([
            "/opt/cadence/bin/xrun", "-64bit", "-sv", "-define", "UNIT_DELAY",
            "-nospecify", "-notimingchecks", "-xmerror", "RECOME", "-top", TOP,
            str(MEMORY), str(RTL / "tri_oracle_softmax_iomem.sv"), str(arithmetic),
            str(top), str(testbench), f"+FIXTURE={fixture}",
        ], cwd=work, capture_output=True, text=True, timeout=120)
    log = run.stdout + run.stderr
    if args.omit_tail:
        expected = "SOFTMAX_IOMEM_UNWRITTEN_READ bank=0 line=0"
        assert run.returncode == 2 and log.splitlines().count(expected) == 1, log[-5000:]
        print(expected)
    else:
        assert run.returncode == 0 and log.splitlines().count(prior["simulation_marker"]) == 1, log[-5000:]
        assert not re.search(r"\*[EF],", log)
        cycles = [int(line.split()[1]) for line in log.splitlines() if line.startswith("SOFTMAX_LONG_ROW_CYCLES ")]
        assert cycles == [463, 463, 463]
        print(prior["simulation_marker"])
        print("SOFTMAX_IOMEM_ACCESS_COUNTS_PASS macros=20 cycles_to_first_output=463")


if __name__ == "__main__":
    main()
