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

ONE_HOT_QUEUE = """    wire [RESULT_BITS-1:0] arithmetic_result;
    logic [RESULT_BITS-1:0] completed_results [0:QUEUE_DEPTH-1];
    logic [QUEUE_DEPTH-1:0] read_slot, write_slot;
    logic [QUEUE_DEPTH:0] occupancy_onehot;
    wire buffered = !occupancy_onehot[0];
    wire queue_full = occupancy_onehot[QUEUE_DEPTH];
    wire take_result = out_valid && out_ready;
    wire completion = running_valid[STAGES];
    wire read_buffer = take_result && buffered;
    // An empty queue bypasses on a take. A full queue only writes on a take.
    wire write_buffer = completion && (take_result ? buffered : !queue_full);
    assign hold_result_stage = completion && queue_full && !take_result;

    function automatic [QUEUE_DEPTH-1:0] advance_slot(input [QUEUE_DEPTH-1:0] slot);
        advance_slot = (slot << 1) | QUEUE_DEPTH'(slot[QUEUE_DEPTH-1]);
    endfunction

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            read_slot <= 1;
            write_slot <= 1;
            occupancy_onehot <= 1;
        end else begin
            if (read_buffer)
                read_slot <= advance_slot(read_slot);
            if (write_buffer)
                write_slot <= advance_slot(write_slot);
            case ({write_buffer, read_buffer})
                2'b10: occupancy_onehot <= occupancy_onehot << 1;
                2'b01: occupancy_onehot <= occupancy_onehot >> 1;
                default: ;
            endcase
        end
    end

    wire [RESULT_BITS-1:0] read_data [0:QUEUE_DEPTH];
    assign read_data[0] = '0;
    for (genvar slot=0; slot<QUEUE_DEPTH; slot++) begin : result_slot
        assign read_data[slot+1] = read_data[slot] |
            ({RESULT_BITS{read_slot[slot]}} & completed_results[slot]);
        always @(posedge clk)
            if (write_buffer && write_slot[slot])
                completed_results[slot] <= arithmetic_result;
    end
    assign out_sums = buffered ? read_data[QUEUE_DEPTH] : arithmetic_result;
"""


def reuse_result_stage(text: str) -> str:
    """Retain a completion in the final stage while the smaller queue is full."""
    changes = {
        "    localparam int INDEX_BITS = PIPE_DEPTH > 1 ? $clog2(PIPE_DEPTH) : 1;":
            "    localparam int QUEUE_DEPTH = PIPE_DEPTH - 1;\n"
            "    localparam int INDEX_BITS = QUEUE_DEPTH > 1 ? $clog2(QUEUE_DEPTH) : 1;",
        "$clog2(PIPE_DEPTH + 1)": "$clog2(QUEUE_DEPTH + 1)",
        "completed_results [0:PIPE_DEPTH-1]": "completed_results [0:QUEUE_DEPTH-1]",
        "    wire accept = in_ready && in_valid;":
            "    wire accept = in_ready && in_valid;\n"
            "    wire hold_result_stage;",
        "(running_valid << 1) | PIPE_DEPTH'(accept);":
            "(running_valid << 1) | PIPE_DEPTH'(accept) |\n"
            "                             (PIPE_DEPTH'(hold_result_stage) << STAGES);",
        "    wire write_buffer = running_valid[STAGES] && (buffered || !take_result);":
            "    // At capacity, a held completion is the only payload left in the datapath.\n"
            "    assign hold_result_stage = running_valid[STAGES] &&\n"
            "                               buffered_count == COUNT_BITS'(QUEUE_DEPTH) && !read_buffer;\n"
            "    wire write_buffer = running_valid[STAGES] && (buffered || !take_result) &&\n"
            "                        !hold_result_stage;",
        "                    value <= sum + carry;":
            "                if (!hold_result_stage)\n"
            "                    value <= sum + carry;",
    }
    for before, after in changes.items():
        if text.count(before) != 1:
            raise ValueError(f"Cannot identify the final-stage insertion point: {before}")
        text = text.replace(before, after)
    if text.count("INDEX_BITS'(PIPE_DEPTH-1)") != 2:
        raise ValueError("Cannot identify queue pointer limits")
    text = text.replace("INDEX_BITS'(PIPE_DEPTH-1)", "INDEX_BITS'(QUEUE_DEPTH-1)")
    text, counts = re.subn(
        r"(?m)(^ +)(value <= \$signed\(\{(?:product|reduction)\[)",
        r"\1if (level != STAGES - 1 || !hold_result_stage)\n\1    \2",
        text,
    )
    if counts != 2:
        raise ValueError("Cannot identify the last register in the fallback reduction tree")
    return text


def onehot_queue(text: str) -> str:
    """Keep the final-stage reuse but replace the FIFO's binary state."""
    begin = "    wire [RESULT_BITS-1:0] arithmetic_result;\n"
    product = "    for(genvar p=0;p<LINES*LANES;p=p+1) begin: product\n"
    if text.count(begin) != 1 or text.count(product) != 1:
        raise ValueError("Cannot find the result queue boundaries")
    prefix, _, suffix = text.partition(begin)
    _, _, arithmetic = suffix.partition(product)
    prefix = prefix.replace("    localparam int INDEX_BITS = QUEUE_DEPTH > 1 ? $clog2(QUEUE_DEPTH) : 1;\n", "")
    prefix = prefix.replace("    localparam int COUNT_BITS = $clog2(QUEUE_DEPTH + 1);\n", "")
    return prefix + ONE_HOT_QUEUE + product + arithmetic


def generate(source: Path, output: Path, module: str, reuse_final=False, onehot=False) -> None:
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
    if reuse_final:
        text = reuse_result_stage(text)
    if onehot:
        if not reuse_final:
            raise ValueError("One-hot control requires final-stage reuse")
        text = onehot_queue(text)
    with output.open("x") as stream:
        stream.write(text)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="carry_save.sv from build_tri_oracle_carry_save_array.py")
    parser.add_argument("output", type=Path)
    parser.add_argument("--simulation", action="store_true", help="rename the trial for lockstep simulation")
    parser.add_argument("--reuse-result-stage", action="store_true",
                        help="use the final arithmetic register as one queue slot, with at least two lanes")
    parser.add_argument("--onehot-queue", action="store_true", help="store queue positions and occupancy as one-hot flags")
    args = parser.parse_args()
    if args.onehot_queue and not args.reuse_result_stage:
        parser.error("--onehot-queue requires --reuse-result-stage")
    top = "tri_oracle_pe_array_decoupled" if args.simulation else "tri_oracle_pe_array"
    generate(args.source, args.output, top, reuse_final=args.reuse_result_stage, onehot=args.onehot_queue)
