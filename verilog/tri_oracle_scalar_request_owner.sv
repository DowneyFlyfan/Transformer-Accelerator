`timescale 1ns/1ps
module tri_oracle_scalar_request_owner (
    input logic clk, rst_n,
    input logic [1:0] client_valid,
    output logic [1:0] client_ready,
    output logic request_valid,
    input logic request_ready, terminal_transfer,
    output logic owner, active
);
    typedef enum logic [1:0] {Idle, Pending, Active} state_t;
    state_t state;
    logic saved_owner, prefer_context;

    assign active = state == Active;
    assign owner = state != Idle ? saved_owner : client_valid[1] && (!client_valid[0] || prefer_context);
    assign request_valid = !active && client_valid[owner];
    assign client_ready = !active && request_ready ? (owner ? 2'b10 : 2'b01) : '0;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= Idle;
            saved_owner <= 0;
            prefer_context <= 0;
        end else if (active) begin
            if (terminal_transfer) state <= Idle;
        end else if (request_valid && request_ready) begin
            saved_owner <= owner;
            prefer_context <= !owner;
            state <= Active;
        end else if (state == Idle && request_valid) begin
            saved_owner <= owner;
            state <= Pending;
        end
    end
endmodule
