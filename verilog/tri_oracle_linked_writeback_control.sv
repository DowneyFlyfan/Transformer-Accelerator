`timescale 1ns/1ps

module tri_oracle_linked_writeback_control (
    input  logic clk, rst_n,
    input  logic command_valid, compute_ready, writer_ready,
    input  logic compute_done, compute_error, packet_error, writer_raw_ready,
    output logic command_ready, compute_cfg_valid, writer_cfg_valid,
    output logic done_error, out_ready, writer_abort
);
    logic writeback_failed;

    assign command_ready = compute_ready && writer_ready;
    assign compute_cfg_valid = command_valid && writer_ready;
    assign writer_cfg_valid = command_valid && compute_ready;
    assign done_error = compute_error || writeback_failed || packet_error;
    assign out_ready = writer_raw_ready || writeback_failed;
    assign writer_abort = compute_done && compute_error;

    // Once a write-back fault is latched, let the compute output drain.
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            writeback_failed <= 1'b0;
        else if (command_valid && command_ready)
            writeback_failed <= 1'b0;
        else if (packet_error)
            writeback_failed <= 1'b1;
    end
endmodule
