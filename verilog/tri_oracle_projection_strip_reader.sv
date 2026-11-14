`timescale 1ns/1ps

// A token has 32 projection packets of 64 signed bytes. The backing store
// lays each head's two tokens next to each other. Hold one packet while its
// eight strips retire, and request the next head only after the last strip.
module tri_oracle_projection_strip_reader (
    input logic clk, rst_n,
    input logic start_valid, start_token,
    output logic start_ready,
    output logic request_valid,
    input logic request_ready,
    output logic [5:0] request_packet,
    input logic response_valid,
    output logic response_ready,
    input logic [511:0] response_data,
    output logic out_valid,
    input logic out_ready,
    output logic [7:0] out_strip,
    output logic [63:0] out_codes,
    output logic out_last
);
    typedef enum logic [1:0] {Idle, Request, Receive, Emit} state_t;
    state_t state;
    logic token;
    logic [7:0] strip;
    logic [511:0] packet;

    assign start_ready = rst_n && state == Idle;
    assign request_valid = state == Request;
    assign request_packet = {strip[7:3], token};
    assign response_ready = state == Receive;
    assign out_valid = state == Emit;
    assign out_strip = strip;
    assign out_codes = packet[{strip[2:0], 6'b0} +: 64];
    assign out_last = out_valid && (&strip);

    always_ff @(posedge clk) if (response_valid && response_ready) packet <= response_data;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= Idle;
            token <= 0;
            strip <= 0;
        end else case (state)
            Idle: if (start_valid) begin
                token <= start_token;
                strip <= 0;
                state <= Request;
            end
            Request: if (request_ready) state <= Receive;
            Receive: if (response_valid) state <= Emit;
            Emit: if (out_ready) begin
                if (out_last) state <= Idle;
                else begin
                    strip <= strip + 8'd1;
                    if (&strip[2:0]) state <= Request;
                end
            end
            default: state <= Idle;
        endcase
    end
endmodule
