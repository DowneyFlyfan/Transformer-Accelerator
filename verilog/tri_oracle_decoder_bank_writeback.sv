`timescale 1ns/1ps

// Retire one two-token decoder frame through the leased residual banks.
// The caller holds the lease through frame completion or abort drainage.
module tri_oracle_decoder_bank_writeback (
    input logic clk, rst_n, lease_granted,
    input logic frame_cfg_valid, frame_abort,
    input logic [9:0] frame_down_shifts,
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
    output logic out_valid,
    input logic out_ready,
    output logic [31:0] out_tag,
    output logic [3:0] out_token,
    output logic [15:0] out_start,
    output logic [3:0] out_count,
    output logic out_last,
    output logic [127:0] out_data
);
    logic armed, read_pending, enabled, packet_valid;
    logic packet_bounds_ok, bridge_in_ready, bridge_bypass_ready;
    logic [9:0] shifts;
    logic [4:0] down_shift;

    assign enabled = armed && lease_granted && !frame_abort;
    assign frame_active = armed || read_pending;
    assign frame_cfg_ready = rst_n && lease_granted && !frame_abort && !frame_active && !bank_response_valid;
    assign packet_bounds_ok = in_token < 4'd2 && in_start[2:0] == 3'd0 &&
                              in_count != 8'd0 && in_count <= 8'd160 &&
                              ({1'b0, in_start} + 17'(in_count)) <= 17'd2048;
    assign packet_error = enabled && in_valid && !packet_bounds_ok;
    assign packet_valid = enabled && in_valid && packet_bounds_ok;
    assign in_ready = bridge_in_ready || packet_error;

    assign bank_read_valid = packet_valid && !read_pending;
    assign bank_read_row = {in_token[0], out_start[10:3]};
    assign bank_response_ready = read_pending && (!packet_valid || bridge_bypass_ready);

    tri_oracle_decoder_writeback_bridge strips (
        .clk, .rst_n(rst_n && armed), .in_valid(packet_valid), .in_ready(bridge_in_ready),
        .in_tag, .in_token, .in_start, .in_count, .in_last, .in_data,
        .bypass_valid(read_pending && bank_response_valid),
        .bypass_ready(bridge_bypass_ready), .bypass_data(bank_response_data),
        .down_shift, .out_valid, .out_ready, .out_tag, .out_token, .out_start,
        .out_count, .out_last, .out_data
    );

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            armed <= 1'b0;
            shifts <= '0;
            down_shift <= '0;
            read_pending <= 1'b0;
        end else begin
            if (frame_abort || !lease_granted || packet_error || (out_valid && out_ready && out_last))
                armed <= 1'b0;
            else if (frame_cfg_valid && frame_cfg_ready) begin
                armed <= 1'b1;
                shifts <= frame_down_shifts;
            end

            if (bank_read_valid && bank_read_ready) begin
                // Select the scale as the memory read launches. The result
                // already waits for the corresponding bank response.
                down_shift <= in_token[0] ? shifts[9:5] : shifts[4:0];
                read_pending <= 1'b1;
            end else if (bank_response_valid && bank_response_ready)
                read_pending <= 1'b0;
        end
    end
endmodule
