`timescale 1ns/1ps

// Convert a held 64-lane attention result to eight ordered projection words.
// The upstream producer must retain data, shift, and destination until in_ready.
// The final accepted output word also retires the input row.
module tri_oracle_attention_projection_stream (
    input logic clk, rst_n, in_valid,
    output logic in_ready,
    input logic [2047:0] in_data,
    input logic [4:0] in_shift,
    input logic [5:0] in_row,
    output logic out_valid,
    input logic out_ready,
    output logic out_last,
    output logic [5:0] out_row,
    output logic [2:0] out_word,
    output logic [63:0] out_data
);
    logic [2:0] word_index;
    logic [255:0] active_accumulators;

    assign out_valid = rst_n && in_valid;
    assign out_last = word_index == 3'd7;
    assign out_row = in_row;
    assign out_word = word_index;
    assign in_ready = out_valid && out_last && out_ready;
    assign active_accumulators = in_data[256*word_index +: 256];

    for (genvar lane = 0; lane < 8; lane++) begin : scales
        tri_oracle_attention_projection_scale scale_lane (
            .accumulator(active_accumulators[32*lane +: 32]),
            .scale_shift(in_shift),
            .projection_code(out_data[8*lane +: 8])
        );
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            word_index <= '0;
        else if (out_valid && out_ready)
            word_index <= word_index + 3'd1;
    end
endmodule
