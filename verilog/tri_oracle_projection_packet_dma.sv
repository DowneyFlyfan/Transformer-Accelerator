`timescale 1ns/1ps

// Each head has a 64 KiB region containing the two 64-byte token packets.
// Translate a packet request to one eight-beat read on the chip memory bus.
module tri_oracle_projection_packet_dma #(
    parameter logic [63:0] CACHE_BASE = 64'h02000000
) (
    input logic clk, rst_n,
    input logic packet_request_valid,
    output logic packet_request_ready,
    input logic [5:0] packet_request_address,
    output logic packet_response_valid,
    input logic packet_response_ready,
    output logic packet_response_error,
    output logic [511:0] packet_response_data,
    output logic req_valid,
    input logic req_ready,
    output logic [63:0] req_address,
    output logic [4:0] req_length,
    input logic rsp_valid,
    output logic rsp_ready,
    input logic rsp_last, rsp_error,
    input logic [63:0] rsp_data
);
    typedef enum logic [2:0] {Idle, Request, Receive, Drain, Response} state_t;
    state_t state;
    logic [2:0] beat;
    logic [511:0] packet;
    logic bad_beat;

    assign packet_request_ready = rst_n && state == Idle;
    assign req_valid = state == Request;
    assign req_length = 5'd8;
    assign rsp_ready = state == Receive || state == Drain;
    assign bad_beat = rsp_error || rsp_last != (&beat);
    assign packet_response_valid = state == Response;
    assign packet_response_data = packet_response_valid && !packet_response_error ? packet : '0;

    always_ff @(posedge clk) begin
        if (rsp_valid && state == Receive && !bad_beat)
            packet[{beat, 6'b0} +: 64] <= rsp_data;
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= Idle;
            req_address <= '0;
            packet_response_error <= 0;
            beat <= 0;
        end else case (state)
            Idle: if (packet_request_valid) begin
                req_address <= CACHE_BASE + {43'd0, packet_request_address[5:1], 9'd0,
                                            packet_request_address[0], 6'd0};
                beat <= 0;
                packet_response_error <= 0;
                state <= Request;
            end
            Request: if (req_ready) state <= Receive;
            Receive: if (rsp_valid) begin
                if (bad_beat) begin
                    packet_response_error <= 1;
                    state <= rsp_last ? Response : Drain;
                end else if (rsp_last) begin
                    state <= Response;
                end else begin
                    beat <= beat + 3'd1;
                end
            end
            Drain: if (rsp_valid && rsp_last) state <= Response;
            Response: if (packet_response_ready) state <= Idle;
            default: state <= Idle;
        endcase
    end
endmodule
