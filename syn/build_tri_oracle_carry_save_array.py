"""Generate the tested carry-save array and its cycle-by-cycle comparison bench."""

import argparse
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
RTL = REPO / "verilog/tri_oracle_pe_array.sv"
TB = REPO / "verilog/tri_oracle_pe_array_tb.sv"


TOP_BODY = """    function automatic [2*SUM_W-1:0] compress_three(
        input [SUM_W-1:0] x,
        input [SUM_W-1:0] y,
        input [SUM_W-1:0] z
    );
        reg [SUM_W-1:0] parity;
        reg [SUM_W-1:0] majority;
        begin
            parity = x ^ y ^ z;
            majority = (x & y) | ((x | y) & z);
            compress_three = {majority[SUM_W-2:0], 1'b0, parity};
        end
    endfunction

    function automatic [2*SUM_W-1:0] compress_four(
        input [SUM_W-1:0] x,
        input [SUM_W-1:0] y,
        input [SUM_W-1:0] z,
        input [SUM_W-1:0] w
    );
        reg [2*SUM_W-1:0] partial;
        begin
            partial = compress_three(x, y, z);
            compress_four = compress_three(partial[SUM_W-1:0], partial[2*SUM_W-1:SUM_W], w);
        end
    endfunction

    if (LANES == 8 && STAGES == 3 && SUM_W == 2*DATA_W+3) begin : carry_save
        for (genvar line=0; line<LINES; line=line+1) begin : row
            for (genvar group=0; group<2; group=group+1) begin : compressor
                wire [SUM_W-1:0] terms [0:3];
                for (genvar lane=0; lane<4; lane=lane+1) begin : extend_sign
                    localparam integer INDEX = line*LANES+4*group+lane;
                    assign terms[lane] = {{(SUM_W-2*DATA_W){product[INDEX].value[2*DATA_W-1]}},
                                          product[INDEX].value};
                end
                reg [SUM_W-1:0] sum, carry;
                always @(posedge clk)
                    if (in_ready && valid[0])
                        {carry, sum} <= compress_four(terms[0],terms[1],terms[2],terms[3]);
            end
            reg [SUM_W-1:0] sum, carry;
            always @(posedge clk)
                if (in_ready && valid[1])
                    {carry,sum} <= compress_four(compressor[0].sum,compressor[0].carry,
                                                 compressor[1].sum,compressor[1].carry);
            reg [SUM_W-1:0] value;
            always @(posedge clk)
                if (in_ready && valid[2])
                    value <= sum + carry;
            assign out_sums[line*SUM_W +: SUM_W] = value;
        end
    end else begin : original_reduction
"""
CHECK = """    wire ref_in_ready, ref_out_valid;
    wire [LINES*SUM_W-1:0] ref_out_sums;
    integer checked_edges=0;
    tri_oracle_pe_array_reference reference_array(
        .clk(clk), .rst_n(rst_n), .in_valid(in_valid), .in_ready(ref_in_ready),
        .operand_a(operand_a), .operand_b(operand_b), .lane_enable(lane_enable),
        .out_valid(ref_out_valid), .out_ready(out_ready), .out_sums(ref_out_sums)
    );
    always @(posedge clk) begin
        if ({ref_in_ready,ref_out_valid} !== {in_ready,out_valid})
            $fatal(1,"carry-save changed the cycle-level handshake");
        if (out_valid && ref_out_sums !== out_sums)
            $fatal(1,"carry-save changed data at a valid edge");
        checked_edges = checked_edges + 1;
    end
"""


def generate(output):
    raw = RTL.read_text()
    marker = "    for(genvar level=0;level<STAGES;level=level+1) begin: reduction\n"
    prefix, separator, old = raw.partition(marker)
    module_name = "module tri_oracle_pe_array #("
    if not separator or not old.endswith("endmodule\n") or raw.count(module_name) != 1:
        raise ValueError("The base array structure has changed. Check the carry-save insertion point.")
    fallback = "".join(
        "    " + line for line in (marker + old.removesuffix("endmodule\n")).splitlines(keepends=True)
    )

    tb = TB.read_text()
    dut = "    tri_oracle_pe_array dut (.*);\n"
    finish = "        $finish;\n"
    if tb.count(dut) != 1 or tb.count(finish) != 1:
        raise ValueError("The base testbench has changed. Check the lockstep insertion points.")
    tb = tb.replace(dut, dut + CHECK)
    marker = '        $display("LOCKSTEP_ARRAY_EDGE_PASS mode=%0d edges=%0d", NO_STALL,checked_edges);\n'
    tb = tb.replace(finish, marker + finish)

    output.mkdir(parents=True, exist_ok=True)
    sources = {
        "carry_save.sv": prefix + TOP_BODY + fallback + "    end\nendmodule\n",
        "reference.sv": raw.replace(module_name, "module tri_oracle_pe_array_reference #("),
        "lockstep.sv": tb,
    }
    if existing := [name for name in sources if (output / name).exists()]:
        raise FileExistsError("Output already exists: " + ", ".join(existing))
    for name, content in sources.items():
        with (output / name).open("x") as stream:
            stream.write(content)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="directory for the generated array and testbench")
    generate(parser.parse_args().output)
