`timescale 1ns/1ps

// A grouped command owns its probability rows through completion, including
// the gap between releasing the normalization ports and acquiring drain ports.
module tri_oracle_residual_bank_arbiter (
    input logic clk, rst_n,
    input logic grouped_accept, grouped_retire,
    output logic grouped_enable,
    input logic residual_request, native_idle, residual_inflight,
    output logic residual_granted
);
    typedef enum logic [1:0] {Idle, Grouped, Residual} state_t;
    state_t state;

    assign grouped_enable = rst_n && state == Idle && !residual_request;
    assign residual_granted = rst_n && state == Residual;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) state <= Idle;
        else case (state)
            Idle: begin
                if (residual_request) begin
                    if (native_idle) state <= Residual;
                end else if (grouped_accept) state <= Grouped;
            end
            Grouped: if (grouped_retire) state <= Idle;
            Residual: if (!residual_request && !residual_inflight) state <= Idle;
            default: state <= Idle;
        endcase
    end
endmodule
