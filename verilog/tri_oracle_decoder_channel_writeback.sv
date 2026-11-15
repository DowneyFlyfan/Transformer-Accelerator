`timescale 1ns/1ps

// Pair each retained residual strip with its channel scales. The owner
// holds the bank lease until frame_active clears, including abort drainage.
module tri_oracle_decoder_channel_writeback (
    input logic clk, rst_n, lease_granted,
    input logic frame_cfg_valid, frame_abort,
    input logic [9:0] frame_down_shifts,
    input logic [63:0] frame_scale_base,
    output logic frame_cfg_ready, frame_active,
    input logic in_valid,
    output logic in_ready, packet_error,
    input logic [31:0] in_tag,
    input logic [3:0] in_token,
    input logic [15:0] in_start,
    input logic [7:0] in_count,
    input logic in_last,
    input logic [5119:0] in_data,
    output logic bank_read_valid,
    input logic bank_read_ready,
    output logic [8:0] bank_read_row,
    input logic bank_response_valid,
    output logic bank_response_ready,
    input logic [231:0] bank_response_data,
    output logic req_valid,
    input logic req_ready,
    output logic [63:0] req_address,
    output logic [4:0] req_length,
    input logic rsp_valid,
    output logic rsp_ready,
    input logic rsp_last, rsp_error,
    input logic [63:0] rsp_data,
    output logic out_valid,
    input logic out_ready,
    output logic [31:0] out_tag,
    output logic [3:0] out_token,
    output logic [15:0] out_start,
    output logic [3:0] out_count,
    output logic out_last,
    output logic [127:0] out_data
);
    logic armed, bank_pending, scale_pending, scales_valid;
    logic enabled, packet_bounds_ok, packet_valid, frame_start, retire_strip;
    logic packet_ready, scale_req_valid, scale_req_ready, scale_rsp_valid, scale_rsp_error;
    logic [63:0] scale_base;
    logic [9:0] base_shifts;
    logic [4:0] base_shift, strip_offset;
    logic [39:0] lane_shifts, fetched_shifts;
    logic [255:0] down_codes;
    logic [127:0] result_q13;

    assign frame_active = armed || bank_pending || scale_pending;
    assign frame_cfg_ready = rst_n && lease_granted && !frame_abort && !frame_active && !bank_response_valid;
    assign frame_start = frame_cfg_valid && frame_cfg_ready;
    assign enabled = armed && lease_granted && !frame_abort;
    assign packet_bounds_ok = in_token < 4'd2 && in_start[2:0] == 3'd0 &&
                              in_count != 8'd0 && in_count <= 8'd160 &&
                              ({1'b0, in_start} + 17'(in_count)) <= 17'd2048;
    assign packet_error = enabled && in_valid &&
                          (!packet_bounds_ok || (scale_pending && scale_rsp_valid && scale_rsp_error));
    assign packet_valid = enabled && in_valid && !packet_error;
    assign in_ready = packet_ready || packet_error;
    assign retire_strip = out_valid && out_ready;
    assign bank_read_valid = packet_valid && !bank_pending;
    assign bank_read_row = {in_token[0], out_start[10:3]};
    assign bank_response_ready = bank_pending && (!packet_valid || retire_strip);

    assign scale_req_valid = packet_valid && !scale_pending && !scales_valid;
    assign base_shift = in_token[0] ? base_shifts[9:5] : base_shifts[4:0];
    tri_oracle_channel_scale_reader scales (
        .clk, .rst_n, .invalidate_cache(frame_start),
        .scale_req_valid, .scale_req_ready, .scale_base, .scale_strip(out_start[10:3]), .base_shift,
        .scale_rsp_valid, .scale_rsp_ready(scale_pending), .scale_rsp_error, .lane_shifts(fetched_shifts),
        .req_valid, .req_ready, .req_address, .req_length, .rsp_valid, .rsp_ready, .rsp_last, .rsp_error, .rsp_data
    );

    // Reuse the packet and partial-strip sequencing. Its scalar arithmetic
    // is unused here, with constant inputs so synthesis can remove it.
    tri_oracle_decoder_writeback_bridge strip_sequence (
        .clk, .rst_n(rst_n && armed), .in_valid(packet_valid), .in_ready(packet_ready),
        .in_tag, .in_token, .in_start, .in_count, .in_last, .in_data('0),
        .bypass_valid(bank_pending && bank_response_valid && scales_valid),
        .bypass_ready(), .bypass_data('0), .down_shift('0),
        .out_valid, .out_ready, .out_tag, .out_token, .out_start, .out_count, .out_last, .out_data()
    );
    assign strip_offset = out_start[7:3] - in_start[7:3];
    tri_oracle_decoder_residual_writeback_per_lane arithmetic (
        .residual_q26(bank_response_data), .down_codes, .lane_shifts, .result_q13
    );
    for (genvar lane = 0; lane < 8; lane++) begin : valid_lanes
        assign out_data[16*lane +: 16] = out_valid && out_count > 4'(lane) ?
                                      result_q13[16*lane +: 16] : '0;
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            armed <= 1'b0;
            bank_pending <= 1'b0;
            scale_pending <= 1'b0;
            scales_valid <= 1'b0;
            scale_base <= '0;
            base_shifts <= '0;
            lane_shifts <= '0;
            down_codes <= '0;
        end else begin
            if (frame_abort || !lease_granted || packet_error || (retire_strip && out_last))
                armed <= 1'b0;
            else if (frame_start) begin
                armed <= 1'b1;
                scale_base <= frame_scale_base;
                base_shifts <= frame_down_shifts;
            end

            if (bank_read_valid && bank_read_ready) begin
                // Capture the matching accumulator slice as the residual
                // read starts, before either response can retire the strip.
                down_codes <= in_data[{strip_offset,8'b0} +: 256];
                bank_pending <= 1'b1;
            end else if (bank_response_valid && bank_response_ready)
                bank_pending <= 1'b0;

            if (scale_req_valid && scale_req_ready)
                scale_pending <= 1'b1;
            else if (scale_pending && scale_rsp_valid)
                scale_pending <= 1'b0;

            if (!packet_valid || retire_strip)
                scales_valid <= 1'b0;
            else if (scale_pending && scale_rsp_valid) begin
                lane_shifts <= fetched_shifts;
                scales_valid <= 1'b1;
            end
        end
    end
endmodule
