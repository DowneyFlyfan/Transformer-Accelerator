`timescale 1ns/1ps

// One attention strip feeds a residual-bank write and a normalization input.
// Each output retires independently while the input slot holds both results.
module tri_oracle_attention_residual_store (
    input logic clk, rst_n,
    input logic in_valid,
    output logic in_ready,
    input logic [8:0] in_row,
    input logic [279:0] residual_q32,
    input logic [63:0] projection_codes,
    input logic [4:0] projection_shift,
    output logic write_valid,
    input logic write_ready,
    output logic [8:0] write_row,
    output logic [231:0] write_data,
    output logic norm_valid,
    input logic norm_ready,
    output logic [8:0] norm_row,
    output logic [127:0] norm_data
);
    logic [231:0] bypass_q26;
    logic [127:0] result_q13;
    logic [8:0] pending_row;

    tri_oracle_attention_residual_precision add_projection (
        .residual_q32, .projection_codes, .projection_shift, .bypass_q26, .result_q13
    );

    assign in_ready = rst_n && (!write_valid || write_ready) && (!norm_valid || norm_ready);
    assign write_row = pending_row;
    assign norm_row = pending_row;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            write_valid <= 0;
            norm_valid <= 0;
        end else if (in_valid && in_ready) begin
            write_valid <= 1;
            norm_valid <= 1;
        end else begin
            if (write_ready) write_valid <= 0;
            if (norm_ready) norm_valid <= 0;
        end
    end

    always_ff @(posedge clk) begin
        if (in_valid && in_ready) begin
            pending_row <= in_row;
            write_data <= bypass_q26;
            norm_data <= result_q13;
        end
    end
endmodule
