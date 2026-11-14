`timescale 1ns/1ps

// Join the chip read bus to the projection and normalization pipeline.
// A malformed packet is drained by the reader before aborting the token.
module tri_oracle_projection_bus_normalize #(
    parameter logic [63:0] CACHE_BASE = 64'h02000000
) (
    input logic clk, rst_n, lease_granted,
    input logic cfg_valid, cfg_token,
    output logic cfg_ready,
    input logic [31:0] cfg_tag, cfg_epsilon_q16,
    input logic [5:0] cfg_shift,
    output logic req_valid,
    input logic req_ready,
    output logic [63:0] req_address,
    output logic [4:0] req_length,
    input logic rsp_valid,
    output logic rsp_ready,
    input logic rsp_last, rsp_error,
    input logic [63:0] rsp_data,
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
    logic packet_request_valid, packet_request_ready;
    logic packet_response_valid, packet_response_ready, packet_response_error;
    logic [5:0] packet_request_address;
    logic [511:0] packet_response_data;
    logic norm_valid, norm_last, norm_error, norm_cfg_ready;
    logic [31:0] norm_tag, active_tag;
    logic [9:0] norm_index;
    logic [3:0] norm_count;
    logic [127:0] norm_data;
    logic [7:0] norm_mask;
    logic [63:0] activation;
    logic fault_pending, pipeline_rst_n;

    assign pipeline_rst_n = rst_n && !fault_pending;
    assign cfg_ready = !fault_pending && norm_cfg_ready;
    assign out_valid = fault_pending || norm_valid;
    assign out_last = fault_pending || norm_last;
    assign out_error = fault_pending || norm_error;
    assign out_tag = fault_pending ? active_tag : norm_tag;
    assign {out_index, out_count, out_norm_q8, out_outlier_mask, out_activation} =
        fault_pending ? '0 : {norm_index, norm_count, norm_data, norm_mask, activation};

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            fault_pending <= 0;
            active_tag <= '0;
        end else begin
            if (cfg_valid && cfg_ready) active_tag <= cfg_tag;
            if (packet_response_valid && packet_response_ready && packet_response_error)
                fault_pending <= 1;
            else if (out_ready) fault_pending <= 0;
        end
    end

    tri_oracle_projection_packet_dma #(.CACHE_BASE(CACHE_BASE)) bus_reader (.*);
    tri_oracle_projection_normalize normalizer (
        .*, .rst_n(pipeline_rst_n), .cfg_ready(norm_cfg_ready),
        .packet_response_valid(packet_response_valid && !packet_response_error),
        .out_valid(norm_valid), .out_ready(out_ready && !fault_pending),
        .out_last(norm_last), .out_error(norm_error), .out_tag(norm_tag),
        .out_index(norm_index), .out_count(norm_count), .out_norm_q8(norm_data),
        .out_outlier_mask(norm_mask), .out_activation(activation)
    );
endmodule
