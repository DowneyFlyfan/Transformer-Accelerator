`timescale 1ns/1ps
// Packed sign-plane format is a local choice; each feature has32 channel bits.
// Only pairs containing |normalized code|>768 issue gate/up64-bit reads.
// Every accepted request owns one response through LAST, including fault drain.
// Reset requires the external memory peer to reset its outstanding transaction.
module tri_oracle_sign_fetch (
    input logic clk, rst_n, in_valid,
    output logic in_ready,
    input logic [31:0] in_tag,
    input logic [10:0] in_group,
    input logic [9:0] in_strips, in_index,
    input logic in_last, in_error,
    input logic [127:0] in_norm_q8,
    input logic [63:0] in_gate_base, in_up_base,
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
    output logic [4:0] req_length,
    input logic rsp_valid,
    output logic rsp_ready,
    input logic rsp_last, rsp_error,
    input logic [63:0] rsp_data
);
    typedef enum logic [2:0] {Idle, Scan, Request, Response, Drain, Holding} state_t;
    state_t state;
    logic [63:0] gate_base, up_base, strip_offset;
    logic [7:0] outliers;
    logic [2:0] pair_index;
    logic up_matrix;
    logic [64:0] group_bytes, group_end_offset, unused_gate_end, unused_up_end;
    logic [63:0] incoming_offset;
    logic invalid_input;

    always_comb begin
        group_bytes = 65'(in_strips) << 5;
        group_end_offset = (65'(in_group)+65'd1)*group_bytes-65'd1;
        unused_gate_end = {1'b0,in_gate_base}+group_end_offset;
        unused_up_end = {1'b0,in_up_base}+group_end_offset;
        // Even the unvalidated10/11-bit fields produce an offset below2^26.
        incoming_offset = (64'(in_group)*64'(in_strips)+64'(in_index)) << 5;
        invalid_input = in_strips == 0 || in_strips > 10'd512 ||
            in_index >= in_strips || in_gate_base[2:0] != 0 ||
            in_up_base[2:0] != 0 || unused_gate_end[64] || unused_up_end[64];
        in_ready = state == Idle;
        out_valid = state == Holding;
        req_valid = state == Request;
        req_address = (up_matrix ? up_base : gate_base)+strip_offset+
            (64'(pair_index) << 3);
        req_length = 5'd1;
        rsp_ready = state == Response || state == Drain;
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= Idle;
            gate_base <= '0;
            up_base <= '0;
            strip_offset <= '0;
            outliers <= '0;
            pair_index <= '0;
            up_matrix <= 1'b0;
            out_last <= 1'b0;
            out_error <= 1'b0;
            out_tag <= '0;
            out_group <= '0;
            out_index <= '0;
            out_norm_q8 <= '0;
            out_gate_signs <= '0;
            out_up_signs <= '0;
        end else begin
            case (state)
                Idle: if (in_valid) begin
                    out_tag <= in_tag;
                    out_group <= in_group;
                    out_index <= in_index;
                    out_last <= in_last;
                    gate_base <= in_gate_base;
                    up_base <= in_up_base;
                    strip_offset <= incoming_offset;
                    pair_index <= '0;
                    up_matrix <= 1'b0;
                    out_error <= in_error || invalid_input;
                    out_gate_signs <= '0;
                    out_up_signs <= '0;
                    if (in_error || invalid_input) begin
                        out_norm_q8 <= '0;
                        outliers <= '0;
                        state <= Holding;
                    end else begin
                        out_norm_q8 <= in_norm_q8;
                        for (int lane = 0; lane < 8; lane++) begin
                            outliers[lane] <=
                                $signed(in_norm_q8[lane*16+:16]) > 16'sd768 ||
                                $signed(in_norm_q8[lane*16+:16]) < -16'sd768;
                        end
                        state <= Scan;
                    end
                end
                Scan: begin
                    if (pair_index == 3'd4) state <= Holding;
                    else if (outliers[pair_index*2+:2] == 0)
                        pair_index <= pair_index+3'd1;
                    else state <= Request;
                end
                Request: if (req_ready) state <= Response;
                Response: if (rsp_valid) begin
                    if (rsp_error || !rsp_last) begin
                        out_error <= 1'b1;
                        out_norm_q8 <= '0;
                        out_gate_signs <= '0;
                        out_up_signs <= '0;
                        if (rsp_last) state <= Holding;
                        else state <= Drain;
                    end else begin
                        for (int channel = 0; channel < 32; channel++) begin
                            for (int half = 0; half < 2; half++) begin
                                if (outliers[pair_index*2+half]) begin
                                    if (up_matrix)
                                        out_up_signs[channel*8+pair_index*2+half] <=
                                            rsp_data[channel+half*32];
                                    else
                                        out_gate_signs[channel*8+pair_index*2+half] <=
                                            rsp_data[channel+half*32];
                                end
                            end
                        end
                        if (up_matrix) begin
                            up_matrix <= 1'b0;
                            pair_index <= pair_index+3'd1;
                            state <= Scan;
                        end else begin
                            up_matrix <= 1'b1;
                            state <= Request;
                        end
                    end
                end
                Drain: if (rsp_valid && rsp_last) state <= Holding;
                Holding: if (out_ready) state <= Idle;
                default: state <= Idle;
            endcase
        end
    end
endmodule
