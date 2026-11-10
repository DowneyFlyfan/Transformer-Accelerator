`timescale 1ns/1ps
// Share one learned normalization pass between signed8 activation writes
// and pre-scale prediction metadata. A complete burst is buffered before
// issue, and prediction starts only after the final write acknowledgment.
// An error invalidates the caller-owned activation allocation. The producer
// finishes a token that has already started, then withdraws any unaccepted
// residual offers before acknowledging terminal error. Reset resets both peers.
module tri_oracle_batched_normalize405 (
    input logic clk, rst_n, cfg_valid,
    output logic cfg_ready,
    input logic [31:0] cfg_tag,
    input logic [4:0] cfg_tokens,
    input logic [9:0] cfg_strips,
    input logic [7:0] cfg_groups,
    input logic [31:0] cfg_epsilon_q16, cfg_activation_stride,
    input logic [95:0] cfg_activation_shifts,
    input logic [63:0] cfg_gate_sign_base, cfg_up_sign_base, cfg_activation_base,
    output logic [3:0] residual_token,
    input logic stats_valid, stats_last,
    output logic stats_ready,
    input logic [127:0] stats_data,
    input logic replay_valid, replay_last,
    output logic replay_ready,
    input logic [127:0] replay_data, replay_gamma,
    output logic out_valid,
    input logic out_ready,
    output logic out_last,
    output logic [31:0] out_tag,
    output logic [7:0] out_group,
    output logic [3:0] out_token,
    output logic [31:0] gate_nearzero_mask, up_nearzero_mask, skip_mask,
    output logic [12:0] outlier_count,
    output logic done_valid,
    input logic done_ready,
    output logic done_error,
    output logic [31:0] done_tag,
    output logic req_valid,
    input logic req_ready,
    output logic [63:0] req_address,
    output logic [4:0] req_length,
    input logic rsp_valid,
    output logic rsp_ready,
    input logic rsp_last, rsp_error,
    input logic [63:0] rsp_data,
    output logic wr_req_valid,
    input logic wr_req_ready,
    output logic [63:0] wr_address,
    output logic [4:0] wr_length,
    output logic wr_data_valid,
    input logic wr_data_ready,
    output logic [63:0] wr_data,
    output logic [7:0] wr_strobe,
    output logic wr_data_last,
    input logic wr_rsp_valid, wr_rsp_error,
    output logic wr_rsp_ready
);
    typedef enum logic [3:0] {
        Idle, LaunchToken, Collect, WriteRequest, WriteData, WriteResponse,
        DrainToken, CommitMetadata, AbortMetadata, Predict, Done
    } state_t;
    state_t state;
    logic [31:0] tag, epsilon, activation_stride;
    logic [4:0] tokens;
    logic [9:0] strips, words_seen;
    logic [95:0] activation_shifts;
    logic [3:0] token_index, burst_fill, burst_beat;
    logic [4:0] burst_length;
    logic burst_token_last, last_token;
    logic [63:0] token_base, write_address;
    logic [63:0] burst_words [0:15];
    logic invalid_config, take_cfg, residual_open;
    logic [64:0] activation_end, gate_sign_end, up_sign_end, sign_bytes;
    logic [31:0] activation_bytes_per_token;

    logic norm_cfg_ready, norm_stats_ready, norm_replay_ready;
    logic norm_valid, norm_ready, norm_last, norm_error, norm_bad;
    logic [31:0] norm_tag;
    logic [9:0] norm_index;
    logic [3:0] norm_count;
    logic [127:0] unused_norm_magnitudes;
    logic [7:0] norm_outliers, norm_negative;
    logic [63:0] activation_data;
    logic metadata_ready, metadata_commit_ready, replay_cfg_ready;
    logic replay_done, replay_error, replay_failed;
    logic [31:0] unused_replay_tag;

    always_comb begin
        activation_bytes_per_token = 32'(cfg_strips) << 3;
        activation_end = {1'b0, cfg_activation_base} +
            (65'(cfg_tokens) - 65'd1) * 65'(cfg_activation_stride) + 65'(activation_bytes_per_token) - 65'd1;
        sign_bytes = (65'(cfg_groups) * 65'(cfg_strips)) << 5;
        gate_sign_end = {1'b0, cfg_gate_sign_base} + sign_bytes - 65'd1;
        up_sign_end = {1'b0, cfg_up_sign_base} + sign_bytes - 65'd1;
        invalid_config = cfg_tokens == 0 || cfg_tokens > 16 || cfg_strips == 0 || cfg_strips > 256 ||
            cfg_groups == 0 || cfg_activation_stride < activation_bytes_per_token ||
            cfg_activation_stride[2:0] != 0 || cfg_activation_base[2:0] != 0 ||
            cfg_gate_sign_base[2:0] != 0 || cfg_up_sign_base[2:0] != 0 ||
            activation_end[64] || gate_sign_end[64] || up_sign_end[64] ||
            ({1'b0, cfg_activation_base} <= gate_sign_end && {1'b0, cfg_gate_sign_base} <= activation_end) ||
            ({1'b0, cfg_activation_base} <= up_sign_end && {1'b0, cfg_up_sign_base} <= activation_end);
    end

    assign cfg_ready = state == Idle && norm_cfg_ready && replay_cfg_ready;
    assign take_cfg = cfg_valid && cfg_ready && !invalid_config;
    assign residual_open = state == Collect || state == WriteRequest || state == WriteData ||
        state == WriteResponse || state == DrainToken;
    assign residual_token = token_index;
    assign stats_ready = residual_open && norm_stats_ready;
    assign replay_ready = residual_open && norm_replay_ready;
    assign replay_failed = replay_done && replay_error;
    assign norm_bad = norm_error || norm_tag != tag || norm_count != 8 ||
        norm_index != words_seen || norm_last != (words_seen + 10'd1 == strips);
    assign norm_ready = state == DrainToken ||
        (state == Collect && (norm_bad || replay_failed || metadata_ready));
    assign last_token = {1'b0, token_index} + 5'd1 == tokens;
    assign wr_req_valid = state == WriteRequest;
    assign wr_address = write_address;
    assign wr_length = burst_length;
    assign wr_data_valid = state == WriteData;
    assign wr_data = wr_data_valid ? burst_words[burst_beat] : '0;
    assign wr_strobe = 8'hff;
    assign wr_data_last = {1'b0, burst_beat} + 5'd1 == burst_length;
    assign wr_rsp_ready = state == WriteResponse;
    assign done_valid = state == Done;
    assign done_tag = tag;

    for (genvar lane = 0; lane < 8; lane++) begin : signs
        assign norm_negative[lane] = unused_norm_magnitudes[16*lane + 15];
    end

    tri_oracle_rms_activation activation_path (
        .clk(clk), .rst_n(rst_n), .cfg_valid(state == LaunchToken), .cfg_ready(norm_cfg_ready),
        .cfg_tag(tag), .cfg_epsilon_q16(epsilon), .cfg_strips(strips),
        .cfg_shift(activation_shifts[6*token_index +: 6]),
        .stats_valid(residual_open && stats_valid), .stats_ready(norm_stats_ready),
        .stats_last(stats_last), .stats_data(stats_data),
        .replay_valid(residual_open && replay_valid), .replay_ready(norm_replay_ready),
        .replay_last(replay_last), .replay_data(replay_data), .replay_gamma(replay_gamma),
        .out_valid(norm_valid), .out_ready(norm_ready), .out_last(norm_last), .out_error(norm_error),
        .out_tag(norm_tag), .out_index(norm_index), .out_count(norm_count), .out_norm_q8(unused_norm_magnitudes),
        .out_outlier_mask(norm_outliers), .out_activation(activation_data)
    );

    tri_oracle_batched_outlier_replay404 replay_table (
        .clk(clk), .rst_n(rst_n), .cfg_valid(take_cfg), .cfg_ready(replay_cfg_ready),
        .cfg_tag(cfg_tag), .cfg_tokens(cfg_tokens), .cfg_strips(cfg_strips), .cfg_groups(cfg_groups),
        .cfg_gate_sign_base(cfg_gate_sign_base), .cfg_up_sign_base(cfg_up_sign_base),
        .meta_valid(state == Collect && norm_valid && !norm_bad && !replay_failed), .meta_ready(metadata_ready),
        .meta_last(norm_last), .meta_tag(norm_tag), .meta_token(token_index), .meta_index(norm_index),
        .meta_outliers(norm_outliers), .meta_negative(norm_negative),
        .commit_valid(state == CommitMetadata), .commit_ready(metadata_commit_ready), .abort_fill(state == AbortMetadata),
        .out_valid(out_valid), .out_ready(out_ready), .out_last(out_last), .out_tag(out_tag),
        .out_group(out_group), .out_token(out_token), .gate_nearzero_mask(gate_nearzero_mask),
        .up_nearzero_mask(up_nearzero_mask), .skip_mask(skip_mask), .outlier_count(outlier_count),
        .done_valid(replay_done), .done_ready(done_valid && done_ready), .done_error(replay_error),
        .done_tag(unused_replay_tag), .req_valid(req_valid), .req_ready(req_ready),
        .req_address(req_address), .req_length(req_length), .rsp_valid(rsp_valid),
        .rsp_ready(rsp_ready), .rsp_last(rsp_last), .rsp_error(rsp_error), .rsp_data(rsp_data)
    );

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= Idle;
            tag <= '0; epsilon <= '0; activation_stride <= '0;
            activation_shifts <= '0; tokens <= '0; strips <= '0;
            words_seen <= '0; token_index <= '0;
            token_base <= '0; write_address <= '0;
            burst_fill <= '0; burst_beat <= '0; burst_length <= '0;
            burst_token_last <= 0; done_error <= 0;
        end else case (state)
            Idle: if (cfg_valid && cfg_ready) begin
                tag <= cfg_tag; epsilon <= cfg_epsilon_q16; activation_stride <= cfg_activation_stride;
                activation_shifts <= cfg_activation_shifts; tokens <= cfg_tokens; strips <= cfg_strips;
                token_base <= cfg_activation_base; write_address <= cfg_activation_base;
                words_seen <= '0; token_index <= '0; burst_fill <= '0;
                done_error <= invalid_config;
                if (invalid_config) state <= Done;
                else state <= LaunchToken;
            end
            LaunchToken: if (norm_cfg_ready) state <= Collect;
            Collect: begin
                if (norm_valid && norm_ready) begin
                    if (norm_bad || replay_failed) begin
                        done_error <= 1;
                        if (norm_last) state <= AbortMetadata;
                        else state <= DrainToken;
                    end else begin
                        burst_words[burst_fill] <= activation_data;
                        words_seen <= words_seen + 10'd1;
                        if (burst_fill == 15 || norm_last) begin
                            burst_length <= {1'b0, burst_fill} + 5'd1;
                            burst_token_last <= norm_last;
                            burst_beat <= '0;
                            state <= WriteRequest;
                        end else burst_fill <= burst_fill + 4'd1;
                    end
                end
            end
            WriteRequest: if (wr_req_ready) state <= WriteData;
            WriteData: if (wr_data_ready) begin
                if (wr_data_last) state <= WriteResponse;
                else burst_beat <= burst_beat + 4'd1;
            end
            WriteResponse: if (wr_rsp_valid) begin
                if (wr_rsp_error || replay_failed) begin
                    done_error <= 1;
                    if (burst_token_last) state <= AbortMetadata;
                    else state <= DrainToken;
                end else begin
                    burst_fill <= '0;
                    if (burst_token_last) begin
                        if (last_token) state <= CommitMetadata;
                        else begin
                            token_index <= token_index + 4'd1;
                            token_base <= token_base + 64'(activation_stride);
                            write_address <= token_base + 64'(activation_stride);
                            words_seen <= '0;
                            state <= LaunchToken;
                        end
                    end else begin
                        write_address <= write_address + (64'(burst_length) << 3);
                        state <= Collect;
                    end
                end
            end
            DrainToken: if (norm_valid && norm_last) state <= AbortMetadata;
            CommitMetadata: begin
                if (replay_done) begin done_error <= 1; state <= Done; end
                else if (metadata_commit_ready) state <= Predict;
            end
            AbortMetadata: if (replay_done) state <= Done;
            Predict: if (replay_done) begin
                done_error <= replay_error;
                state <= Done;
            end
            Done: if (done_ready) state <= Idle;
            default: begin done_error <= 1; state <= Done; end
        endcase
    end
endmodule
