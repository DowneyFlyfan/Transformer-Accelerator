`timescale 1ns/1ps

// Consume an existing feed-forward output packet in eight-value strips.
// The producer holds the packet until in_ready. The bypass stream supplies
// one corresponding strip and down_shift, holding both until bypass_ready.
module tri_oracle_decoder_writeback_bridge (
    input logic clk, rst_n,
    input logic in_valid,
    output logic in_ready,
    input logic [31:0] in_tag,
    input logic [3:0] in_token,
    input logic [15:0] in_start,
    input logic [7:0] in_count,
    input logic in_last,
    input logic [5119:0] in_data,
    input logic bypass_valid,
    output logic bypass_ready,
    input logic [231:0] bypass_data,
    input logic [4:0] down_shift,
    output logic out_valid,
    input logic out_ready,
    output logic [31:0] out_tag,
    output logic [3:0] out_token,
    output logic [15:0] out_start,
    output logic [3:0] out_count,
    output logic out_last,
    output logic [127:0] out_data
);
    logic [4:0] strip_index;
    logic [7:0] offset, remaining;
    logic active, final_strip;
    logic [255:0] down_codes;
    logic [127:0] sum_q13;

    assign offset = {strip_index, 3'b000};
    assign active = rst_n && in_valid && in_count <= 8'd160 && offset < in_count;
    assign remaining = active ? in_count - offset : 8'd0;
    assign final_strip = remaining <= 8'd8;
    assign out_count = final_strip ? remaining[3:0] : 4'd8;

    assign out_valid = active && bypass_valid;
    assign bypass_ready = active && out_ready;
    assign in_ready = out_valid && out_ready && final_strip;
    assign out_tag = in_tag;
    assign out_token = in_token;
    assign out_start = in_start + {8'b0, offset};
    assign out_last = out_valid && final_strip && in_last;

    assign down_codes = in_data[{strip_index, 8'b0} +: 256];
    tri_oracle_decoder_residual_writeback add_residual (
        .residual_q26(bypass_data), .down_codes, .down_shift, .result_q13(sum_q13)
    );

    always_comb begin
        for (int lane = 0; lane < 8; lane++)
            out_data[16*lane +: 16] = lane < int'(out_count) ? sum_q13[16*lane +: 16] : 16'd0;
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            strip_index <= 5'd0;
        else if (out_valid && out_ready)
            strip_index <= final_strip ? 5'd0 : strip_index + 5'd1;
    end
endmodule
