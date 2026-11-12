`timescale 1ns/1ps

// One line holds four pairs. Each pair stores the 64 gate sign bits in
// its low half and the 64 up sign bits in its high half.
module tri_oracle_packed_sign_fetch (
    input logic clk, rst_n, in_valid,
    output logic in_ready,
    input logic [31:0] in_tag,
    input logic [10:0] in_group,
    input logic [9:0] in_strips, in_index,
    input logic in_last, in_error,
    input logic [127:0] in_norm_q8,
    input logic [63:0] in_sign_base,
    output logic out_valid,
    input logic out_ready,
    output logic out_last, out_error,
    output logic [31:0] out_tag,
    output logic [10:0] out_group,
    output logic [9:0] out_index,
    output logic [127:0] out_norm_q8,
    output logic [255:0] out_gate_signs, out_up_signs,
    output logic req_valid,
    input logic req_ready,
    output logic [63:0] req_address,
    output logic [5:0] req_length,
    input logic rsp_valid,
    output logic rsp_ready,
    input logic rsp_last, rsp_error,
    input logic [511:0] rsp_data
);
    typedef enum logic [2:0] {Idle, Request, Response, Drain, Holding} state_t;
    state_t state;
    logic [7:0] input_outliers, outliers;
    logic [20:0] first_strip, requested_strip, group_end_strip;
    logic [64:0] group_last_address;
    logic invalid_input;

    assign first_strip = 21'(in_group) * 21'(in_strips);
    assign requested_strip = first_strip + 21'(in_index);
    assign group_end_strip = first_strip + 21'(in_strips);
    assign group_last_address = {1'b0, in_sign_base} + (65'(group_end_strip) << 6) - 65'd1;
    assign invalid_input = in_strips == 0 || in_strips > 10'd512 || in_index >= in_strips ||
                           in_sign_base[5:0] != 0 || group_last_address[64];
    assign in_ready = state == Idle;
    assign out_valid = state == Holding;
    assign req_valid = state == Request;
    assign req_length = 6'd1;
    assign rsp_ready = state == Response || state == Drain;

    always_comb begin
        for (int lane = 0; lane < 8; lane++) begin
            input_outliers[lane] = $signed(in_norm_q8[lane*16+:16]) > 16'sd768 ||
                                  $signed(in_norm_q8[lane*16+:16]) < -16'sd768;
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= Idle;
            outliers <= '0;
            req_address <= '0;
            out_last <= 0;
            out_error <= 0;
            out_tag <= '0;
            out_group <= '0;
            out_index <= '0;
            out_norm_q8 <= '0;
            out_gate_signs <= '0;
            out_up_signs <= '0;
        end else begin
            case (state)
                Idle: if (in_valid) begin
                    req_address <= in_sign_base + (64'(requested_strip) << 6);
                    out_last <= in_last;
                    out_error <= in_error || invalid_input;
                    out_tag <= in_tag;
                    out_group <= in_group;
                    out_index <= in_index;
                    out_norm_q8 <= (in_error || invalid_input) ? '0 : in_norm_q8;
                    out_gate_signs <= '0;
                    out_up_signs <= '0;
                    outliers <= input_outliers;
                    state <= (in_error || invalid_input || !(|input_outliers)) ? Holding : Request;
                end
                Request: if (req_ready) state <= Response;
                Response: if (rsp_valid) begin
                    if (rsp_error || !rsp_last) begin
                        out_error <= 1;
                        out_norm_q8 <= '0;
                        state <= rsp_last ? Holding : Drain;
                    end else begin
                        for (int channel = 0; channel < 32; channel++) begin
                            for (int lane = 0; lane < 8; lane++) begin
                                out_gate_signs[channel*8+lane] <= outliers[lane] &&
                                    rsp_data[(lane/2)*128+(lane%2)*32+channel];
                                out_up_signs[channel*8+lane] <= outliers[lane] &&
                                    rsp_data[(lane/2)*128+64+(lane%2)*32+channel];
                            end
                        end
                        state <= Holding;
                    end
                end
                Drain: if (rsp_valid && rsp_last) state <= Holding;
                Holding: if (out_ready) state <= Idle;
                default: state <= Idle;
            endcase
        end
    end
endmodule
