`timescale 1ns/1ps

// Join token-ordered projection reads with residual and scale operands.
// The operand source holds data and scale until operand_valid && operand_ready.
module tri_oracle_projection_normalize (
    input logic clk, rst_n, lease_granted,
    input logic cfg_valid, cfg_token,
    output logic cfg_ready,
    input logic [31:0] cfg_tag, cfg_epsilon_q16,
    input logic [5:0] cfg_shift,
    output logic packet_request_valid,
    input logic packet_request_ready,
    output logic [5:0] packet_request_address,
    input logic packet_response_valid,
    output logic packet_response_ready,
    input logic [511:0] packet_response_data,
    output logic operand_ready, operand_token,
    output logic [7:0] operand_strip,
    input logic operand_valid,
    input logic [279:0] residual_q32,
    input logic [4:0] projection_shift,
    input logic gamma_valid,
    output logic gamma_ready,
    output logic [7:0] gamma_strip,
    input logic [127:0] gamma_data,
    output logic out_valid,
    input logic out_ready,
    output logic out_last, out_error,
    output logic [31:0] out_tag,
    output logic [9:0] out_index,
    output logic [3:0] out_count,
    output logic [127:0] out_norm_q8,
    output logic [7:0] out_outlier_mask,
    output logic [63:0] out_activation,
    input logic read_valid,
    output logic read_ready,
    input logic [8:0] read_row,
    output logic response_valid,
    input logic response_ready,
    output logic [231:0] response_data,
    output logic bank_ce_n, bank_we_n,
    output logic [8:0] bank_addr,
    output logic [255:0] bank_d,
    input logic [255:0] bank_q
);
    logic reader_ready, normalizer_ready, projected_valid, projected_ready, strip_ready;
    logic start;
    logic [63:0] projected_codes;

    assign cfg_ready = reader_ready && normalizer_ready;
    assign start = cfg_valid && cfg_ready;
    assign projected_ready = operand_valid && strip_ready;
    assign operand_ready = projected_valid && strip_ready;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) operand_token <= 0;
        else if (start) operand_token <= cfg_token;
    end

    tri_oracle_projection_strip_reader reader (
        .clk, .rst_n, .start_valid(start), .start_token(cfg_token), .start_ready(reader_ready),
        .request_valid(packet_request_valid), .request_ready(packet_request_ready),
        .request_packet(packet_request_address), .response_valid(packet_response_valid),
        .response_ready(packet_response_ready), .response_data(packet_response_data),
        .out_valid(projected_valid), .out_ready(projected_ready), .out_strip(operand_strip),
        .out_codes(projected_codes), .out_last()
    );
    tri_oracle_residual_normalize_bank normalizer (
        .clk, .rst_n, .lease_granted, .cfg_valid(cfg_valid && reader_ready), .cfg_token,
        .cfg_ready(normalizer_ready), .cfg_tag, .cfg_epsilon_q16, .cfg_shift,
        .in_valid(projected_valid && operand_valid), .in_ready(strip_ready),
        .residual_q32, .projection_codes(projected_codes), .projection_shift,
        .gamma_valid, .gamma_ready, .gamma_strip, .gamma_data,
        .out_valid, .out_ready, .out_last, .out_error, .out_tag, .out_index, .out_count,
        .out_norm_q8, .out_outlier_mask, .out_activation,
        .read_valid, .read_ready, .read_row, .response_valid, .response_ready, .response_data,
        .bank_ce_n, .bank_we_n, .bank_addr, .bank_d, .bank_q
    );
endmodule
