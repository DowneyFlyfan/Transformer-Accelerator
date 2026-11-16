"""Generate the free-running arithmetic trial from the carry-save array."""

import argparse
from pathlib import Path
import re


STALL_CONTROL = """    reg [STAGES:0] valid;
    assign out_valid=valid[STAGES];
    assign in_ready=!valid[STAGES] || out_ready;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) valid <= {(STAGES+1){1'b0}};
        else if(in_ready) valid <= {valid[STAGES-1:0],in_valid};
    end
"""

TRIAL_CONTROL = """    localparam int PIPE_DEPTH = STAGES + 1;
    localparam int RESULT_BITS = LINES * SUM_W;
    localparam int INDEX_BITS = PIPE_DEPTH > 1 ? $clog2(PIPE_DEPTH) : 1;
    localparam int COUNT_BITS = $clog2(PIPE_DEPTH + 1);

    // The shadow pipeline retains the original externally visible stall schedule.
    logic [STAGES:0] shadow_valid, running_valid;
    assign out_valid = shadow_valid[STAGES];
    assign in_ready = !out_valid || out_ready;
    wire accept = in_ready && in_valid;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            shadow_valid <= '0;
            running_valid <= '0;
        end else begin
            if (in_ready)
                shadow_valid <= (shadow_valid << 1) | PIPE_DEPTH'(in_valid);
            running_valid <= (running_valid << 1) | PIPE_DEPTH'(accept);
        end
    end

    wire [RESULT_BITS-1:0] arithmetic_result;
    logic [RESULT_BITS-1:0] completed_results [0:PIPE_DEPTH-1];
    logic [INDEX_BITS-1:0] read_index, write_index;
    logic [COUNT_BITS-1:0] buffered_count;
    wire buffered = buffered_count != '0;
    wire take_result = out_valid && out_ready;
    wire read_buffer = take_result && buffered;
    // A completion bypasses an empty queue if the consumer takes it this cycle.
    wire write_buffer = running_valid[STAGES] && (buffered || !take_result);
    assign out_sums = buffered ? completed_results[read_index] : arithmetic_result;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            read_index <= '0;
            write_index <= '0;
            buffered_count <= '0;
        end else begin
            if (read_buffer)
                read_index <= read_index == INDEX_BITS'(PIPE_DEPTH-1) ? '0 : read_index + 1'b1;
            if (write_buffer)
                write_index <= write_index == INDEX_BITS'(PIPE_DEPTH-1) ? '0 : write_index + 1'b1;
            case ({write_buffer, read_buffer})
                2'b10: buffered_count <= buffered_count + 1'b1;
                2'b01: buffered_count <= buffered_count - 1'b1;
                default: ;
            endcase
        end
    end

    always @(posedge clk)
        if (write_buffer)
            completed_results[write_index] <= arithmetic_result;
"""


def generate(source: Path, output: Path, module: str) -> None:
    text = source.read_text()
    declaration = "module tri_oracle_pe_array #("
    if text.count(STALL_CONTROL) != 1 or text.count(declaration) != 1:
        raise ValueError("Expected the generated carry-save array and its original stall control")
    text = text.replace(STALL_CONTROL, TRIAL_CONTROL)
    product = "        always @(posedge clk)\n            if(in_ready && in_valid) begin\n"
    if text.count(product) != 1:
        raise ValueError("Unexpected product register structure")
    text = text.replace(product, "        always @(posedge clk) begin\n")
    text, removed = re.subn(
        r"(?m)^ +if ?\(in_ready && valid\[(?:[012]|level)\]\) *\n",
        "",
        text,
    )
    if removed != 5 or text.count("assign out_sums[") != 2:
        raise ValueError("Unexpected arithmetic register or output structure")
    text = text.replace("assign out_sums[", "assign arithmetic_result[")
    text = text.replace(declaration, f"module {module} #(")
    with output.open("x") as stream:
        stream.write(text)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="carry_save.sv from build_tri_oracle_carry_save_array.py")
    parser.add_argument("output", type=Path)
    parser.add_argument("--simulation", action="store_true", help="rename the trial for lockstep simulation")
    args = parser.parse_args()
    top = "tri_oracle_pe_array_decoupled" if args.simulation else "tri_oracle_pe_array"
    generate(args.source, args.output, top)
