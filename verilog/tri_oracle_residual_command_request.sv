`timescale 1ns/1ps

module tri_oracle_residual_command_request (
    input  logic clk, rst_n,
    input  logic override_request,
    input  logic command_valid, command_ready,
    input  logic done_valid, done_ready,
    output logic residual_request
);
    logic awaiting_completion;

    // The dispatcher asserts command_valid after receiving a complete,
    // well-formed feed-forward descriptor. Request early so writer readiness
    // can participate in accepting that command.
    assign residual_request = rst_n && (override_request || command_valid || awaiting_completion);

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            awaiting_completion <= 1'b0;
        else if (command_valid && command_ready)
            awaiting_completion <= 1'b1;
        else if (done_valid && done_ready)
            awaiting_completion <= 1'b0;
    end
endmodule
