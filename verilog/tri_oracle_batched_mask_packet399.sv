`timescale 1ns/1ps
// Convert original 32-channel skip groups into token-major, 80-channel keep
// packets. Only the upper half of a group can carry across a packet boundary.
// A matching cancellation is the sole exception to holding a pending offer.
// On terminal error, withdraw any unaccepted input before acknowledging done.
// Earlier accepted packets from a failed frame are provisional.
module tri_oracle_batched_mask_packet399 (
    input logic clk, rst_n,
    input logic cfg_valid,
    output logic cfg_ready,
    input logic [31:0] cfg_tag,
    input logic [4:0] cfg_tokens,
    input logic [15:0] cfg_channels,
    input logic in_valid,
    output logic in_ready,
    input logic [31:0] in_tag,
    input logic [7:0] in_group,
    input logic [3:0] in_token,
    input logic in_last,
    input logic [31:0] in_skip_mask,
    input logic cancel_valid,
    input logic [31:0] cancel_tag,
    output logic mask_valid,
    input logic mask_ready,
    output logic [31:0] mask_tag,
    output logic [15:0] mask_start,
    output logic [6:0] mask_count,
    output logic mask_last,
    output logic [1279:0] mask_bits,
    output logic done_valid,
    input logic done_ready,
    output logic done_error,
    output logic [31:0] done_tag
);
    typedef enum logic [1:0] {Idle, Fill, Offer, Done} state_t;
    state_t state;
    logic [31:0] tag;
    logic [4:0] tokens;
    logic [15:0] channels, start_channel, remaining;
    logic [7:0] expected_group;
    logic [3:0] expected_token;
    logic [6:0] fill_offset;
    logic [79:0] packet [0:15];
    logic [15:0] carry [0:15];
    logic [31:0] keep;
    logic [7:0] after_group;
    logic invalid_config, invalid_group, last_token, last_group, split_group, cancelled;

    always_comb begin
        invalid_config = cfg_tokens == 0 || cfg_tokens > 16 || cfg_channels == 0 ||
            cfg_channels > 8160 || cfg_channels[4:0] != 0;
        last_token = {1'b0, expected_token} + 5'd1 == tokens;
        last_group = expected_group == channels[12:5] - 8'd1;
        invalid_group = in_tag != tag || in_group != expected_group || in_token != expected_token ||
            in_last != (last_group && last_token);
        cancelled = cancel_valid && cancel_tag == tag && (state == Fill || state == Offer);

        remaining = channels - start_channel;
        after_group = {1'b0, fill_offset} + 8'd32;
        keep = ~in_skip_mask;
        cfg_ready = state == Idle;
        in_ready = state == Fill && !cancelled;
        mask_valid = state == Offer && !cancelled;
        mask_tag = tag;
        mask_start = start_channel;
        mask_count = remaining > 80 ? 7'd80 : 7'(remaining);
        mask_last = remaining <= 80;
        split_group = after_group > {1'b0, mask_count};
        for (int token = 0; token < 16; token++) mask_bits[token*80 +: 80] = packet[token];
        done_valid = state == Done;
        done_tag = tag;
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= Idle;
            tag <= '0; tokens <= '0; channels <= '0; start_channel <= '0;
            expected_group <= '0; expected_token <= '0; fill_offset <= '0;
            done_error <= 0;
            for (int token = 0; token < 16; token++) begin
                packet[token] <= '0;
                carry[token] <= '0;
            end
        end else if (cancelled) begin
            done_error <= 1;
            state <= Done;
        end else case (state)
            Idle: if (cfg_valid) begin
                tag <= cfg_tag; tokens <= cfg_tokens; channels <= cfg_channels; start_channel <= '0;
                expected_group <= '0; expected_token <= '0; fill_offset <= '0;
                done_error <= invalid_config;
                for (int token = 0; token < 16; token++) begin
                    packet[token] <= '0;
                    carry[token] <= '0;
                end
                if (invalid_config) state <= Done;
                else state <= Fill;
            end
            Fill: if (in_valid) begin
                if (invalid_group) begin
                    done_error <= 1;
                    state <= Done;
                end else begin
                    case (fill_offset)
                        7'd0:  packet[expected_token][31:0] <= keep;
                        7'd16: packet[expected_token][47:16] <= keep;
                        7'd32: packet[expected_token][63:32] <= keep;
                        7'd48: packet[expected_token][79:48] <= keep;
                        7'd64: begin
                            packet[expected_token][79:64] <= keep[15:0];
                            carry[expected_token] <= keep[31:16];
                        end
                        default: begin end
                    endcase
                    if (last_token) begin
                        expected_token <= '0;
                        expected_group <= expected_group + 8'd1;
                        if (after_group >= {1'b0, mask_count}) state <= Offer;
                        else fill_offset <= fill_offset + 7'd32;
                    end else expected_token <= expected_token + 4'd1;
                end
            end
            Offer: if (mask_ready) begin
                if (mask_last) state <= Done;
                else begin
                    start_channel <= start_channel + 16'(mask_count);
                    fill_offset <= split_group ? 7'd16 : 7'd0;
                    for (int token = 0; token < 16; token++)
                        packet[token] <= split_group ? {64'd0, carry[token]} : 80'd0;
                    // A 16-channel final packet may consist entirely of carry.
                    if (split_group && remaining == 96) state <= Offer;
                    else state <= Fill;
                end
            end
            Done: if (done_ready) state <= Idle;
            default: begin done_error <= 1; state <= Done; end
        endcase
    end
endmodule
