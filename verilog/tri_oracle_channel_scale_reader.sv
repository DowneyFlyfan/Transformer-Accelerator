`timescale 1ns/1ps

// Each 64-bit external-memory word holds two strips of eight 3-bit
// decrements. Reuse the last word for the adjacent strip. The frame
// owner invalidates the cache when it replaces the table contents.
module tri_oracle_channel_scale_reader (
    input logic clk, rst_n, invalidate_cache,
    input logic scale_req_valid,
    output logic scale_req_ready,
    input logic [63:0] scale_base,
    input logic [7:0] scale_strip,
    input logic [4:0] base_shift,
    output logic scale_rsp_valid,
    input logic scale_rsp_ready,
    output logic scale_rsp_error,
    output logic [39:0] lane_shifts,
    output logic req_valid,
    input logic req_ready,
    output logic [63:0] req_address,
    output logic [4:0] req_length,
    input logic rsp_valid,
    output logic rsp_ready,
    input logic rsp_last, rsp_error,
    input logic [63:0] rsp_data
);
    typedef enum logic [2:0] {Idle, Request, Receive, Drain, Reply} state_t;
    state_t state;
    logic [64:0] address;
    logic cache_valid, fill_allowed, upper_strip, memory_error;
    logic [63:0] cache_address;
    logic [47:0] cache_word;
    logic [23:0] offsets;
    logic [4:0] saved_shift;
    logic [7:0] underflow;
    logic [39:0] decoded;

    assign address = {1'b0, scale_base} + {55'd0, scale_strip[7:1], 3'd0};
    assign scale_req_ready = rst_n && state == Idle && !invalidate_cache;
    assign req_valid = state == Request;
    assign req_length = 5'd1;
    assign rsp_ready = state == Receive || state == Drain;
    assign scale_rsp_valid = state == Reply;
    assign scale_rsp_error = scale_rsp_valid && (memory_error || (|underflow));
    assign lane_shifts = scale_rsp_valid && !scale_rsp_error ? decoded : '0;

    for (genvar lane = 0; lane < 8; lane++) begin : shifts
        wire [4:0] delta = {2'b00, offsets[3*lane +: 3]};
        assign underflow[lane] = saved_shift < delta;
        assign decoded[5*lane +: 5] = saved_shift - delta;
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= Idle;
            req_address <= '0;
            cache_valid <= 1'b0;
            fill_allowed <= 1'b0;
            upper_strip <= 1'b0;
            memory_error <= 1'b0;
            cache_address <= '0;
            cache_word <= '0;
            offsets <= '0;
            saved_shift <= '0;
        end else begin
            if (invalidate_cache) begin
                cache_valid <= 1'b0;
                fill_allowed <= 1'b0;
            end
            case (state)
                Idle: if (scale_req_valid && scale_req_ready) begin
                    saved_shift <= base_shift;
                    upper_strip <= scale_strip[0];
                    memory_error <= address[64] || (|scale_base[2:0]);
                    if (address[64] || (|scale_base[2:0])) begin
                        state <= Reply;
                    end else if (cache_valid && cache_address == address[63:0]) begin
                        offsets <= scale_strip[0] ? cache_word[47:24] : cache_word[23:0];
                        state <= Reply;
                    end else begin
                        req_address <= address[63:0];
                        fill_allowed <= 1'b1;
                        state <= Request;
                    end
                end
                Request: if (req_ready) state <= Receive;
                Receive: if (rsp_valid) begin
                    if (rsp_error || !rsp_last || (|rsp_data[63:48])) begin
                        memory_error <= 1'b1;
                        state <= rsp_last ? Reply : Drain;
                    end else begin
                        offsets <= upper_strip ? rsp_data[47:24] : rsp_data[23:0];
                        if (fill_allowed && !invalidate_cache) begin
                            cache_address <= req_address;
                            cache_word <= rsp_data[47:0];
                            cache_valid <= 1'b1;
                        end
                        state <= Reply;
                    end
                end
                Drain: if (rsp_valid && rsp_last) state <= Reply;
                Reply: if (scale_rsp_ready) state <= Idle;
                default: state <= Idle;
            endcase
        end
    end
endmodule
