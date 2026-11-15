`timescale 1ns/1ps

// Gate both sides of cluster zero's command handshake. Its terminal handshake
// protects probability rows even when all four native bank ports are idle.
module tri_oracle_residual_bank_command (
    input logic clk, rst_n,
    input logic residual_request,
    input logic [3:0] probability_grant,
    input logic grouped_valid, grouped_core_ready,
    output logic grouped_ready, grouped_core_valid,
    input logic grouped_done_valid, grouped_done_ready,
    input logic projection_cfg_valid, projection_cfg_ready,
    input logic residual_read_valid, residual_read_ready, residual_response_valid,
    input logic writeback_cfg_valid, writeback_cfg_ready, writeback_active,
    output logic residual_granted
);
    logic grouped_enable, residual_inflight;

    assign grouped_ready = grouped_enable && grouped_core_ready;
    assign grouped_core_valid = grouped_enable && grouped_valid;

    // Ready is high between projection transactions. Handshakes can start
    // new work on the same edge that would otherwise return the lease.
    assign residual_inflight = !projection_cfg_ready || projection_cfg_valid ||
        writeback_active || (writeback_cfg_valid && writeback_cfg_ready) ||
        (residual_read_valid && residual_read_ready) || residual_response_valid;

    tri_oracle_residual_bank_arbiter ownership (
        .clk, .rst_n, .residual_request, .residual_granted, .grouped_enable,
        .grouped_accept(grouped_core_valid && grouped_core_ready),
        .grouped_retire(grouped_done_valid && grouped_done_ready),
        .native_idle(&probability_grant), .residual_inflight
    );
endmodule
