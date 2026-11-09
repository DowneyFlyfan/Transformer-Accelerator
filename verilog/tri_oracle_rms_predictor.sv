`timescale 1ns/1ps
// Root-mean-square normalization followed by the paper-aligned strip predictor.
// Local fixed-point format and replay protocol are specified by tri_oracle_rmsnorm.
module tri_oracle_rms_predictor (
    input logic clk,
    input logic rst_n,
    input logic cfg_valid,
    output logic cfg_ready,
    input logic [31:0] cfg_tag,
    input logic [9:0] cfg_strips,
    input logic [31:0] cfg_epsilon_q16,
    input logic stats_valid,
    output logic stats_ready,
    input logic stats_last,
    input logic [127:0] stats_data,
    input logic replay_valid,
    output logic replay_ready,
    input logic replay_last,
    input logic [127:0] replay_data,
    input logic [255:0] replay_gate_signs,
    input logic [255:0] replay_up_signs,
    output logic out_valid,
    input logic out_ready,
    output logic out_error,
    output logic [31:0] out_tag,
    output logic [31:0] gate_nearzero_mask,
    output logic [31:0] up_nearzero_mask,
    output logic [31:0] skip_mask,
    output logic [12:0] outlier_count
);
    // One output-channel group. Sign fetching and reuse across groups remain upstream.
    typedef enum logic [1:0] {Idle, Run, Wait, Holding} state_t;
    state_t state;
    logic [31:0] tag;
    logic frame_fault;
    logic norm_cfg_ready, norm_stats_ready, norm_replay_ready;
    logic norm_valid, norm_ready, norm_last, norm_error;
    logic [31:0] unused_norm_tag;
    logic [9:0] unused_norm_index;
    logic [3:0] unused_norm_count;
    logic [127:0] norm_data;
    logic [7:0] unused_norm_outliers;
    logic [255:0] gate_signs, up_signs;
    logic pred_in_ready, pred_valid, pred_ready, pred_error;
    logic [31:0] pred_gate, pred_up, pred_skip;
    logic [12:0] pred_outliers;

    always_comb begin
        cfg_ready = state == Idle && norm_cfg_ready;
        stats_ready = state == Run && norm_stats_ready;
        replay_ready = state == Run && norm_replay_ready;
        norm_ready = state == Run && pred_in_ready;
        pred_ready = state == Wait;
        out_valid = state == Holding;
        out_tag = tag;
    end

    tri_oracle_rmsnorm normalizer (
        .clk(clk),
        .rst_n(rst_n),
        .cfg_valid(state == Idle && cfg_valid),
        .cfg_ready(norm_cfg_ready),
        .cfg_tag(cfg_tag),
        .cfg_strips(cfg_strips),
        .cfg_epsilon_q16(cfg_epsilon_q16),
        .stats_valid(state == Run && stats_valid),
        .stats_ready(norm_stats_ready),
        .stats_last(stats_last),
        .stats_data(stats_data),
        .replay_valid(state == Run && replay_valid),
        .replay_ready(norm_replay_ready),
        .replay_last(replay_last),
        .replay_data(replay_data),
        .out_valid(norm_valid),
        .out_ready(norm_ready),
        .out_last(norm_last),
        .out_error(norm_error),
        .out_tag(unused_norm_tag),
        .out_index(unused_norm_index),
        .out_count(unused_norm_count),
        .out_norm_q8(norm_data),
        .out_outlier_mask(unused_norm_outliers)
    );

    // A terminal error sends exactly one zero-valued LAST strip. It clears
    // the existing predictor's frame, while frame_fault overrides its result.
    tri_oracle_strip_predictor predictor (
        .clk(clk),
        .rst_n(rst_n),
        .in_valid(state == Run && norm_valid),
        .in_last(norm_last || norm_error),
        .out_ready(pred_ready),
        .norm_activations(norm_error ? 128'b0 : norm_data),
        .gate_weight_signs(gate_signs),
        .up_weight_signs(up_signs),
        .in_ready(pred_in_ready),
        .out_valid(pred_valid),
        .out_error(pred_error),
        .gate_nearzero_mask(pred_gate),
        .up_nearzero_mask(pred_up),
        .skip_mask(pred_skip),
        .outlier_count(pred_outliers)
    );

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= Idle;
            tag <= '0;
            frame_fault <= 1'b0;
            gate_signs <= '0;
            up_signs <= '0;
            out_error <= 1'b0;
            gate_nearzero_mask <= '0;
            up_nearzero_mask <= '0;
            skip_mask <= '0;
            outlier_count <= '0;
        end else begin
            if (replay_valid && replay_ready) begin
                gate_signs <= replay_gate_signs;
                up_signs <= replay_up_signs;
            end
            case (state)
                Idle: if (cfg_valid && cfg_ready) begin
                    tag <= cfg_tag;
                    frame_fault <= 1'b0;
                    out_error <= 1'b0;
                    state <= Run;
                end
                Run: if (norm_valid && norm_ready && (norm_last || norm_error)) begin
                    frame_fault <= norm_error;
                    state <= Wait;
                end
                Wait: if (pred_valid) begin
                    out_error <= frame_fault || pred_error;
                    if (frame_fault || pred_error) begin
                        gate_nearzero_mask <= '0;
                        up_nearzero_mask <= '0;
                        skip_mask <= '0;
                        outlier_count <= '0;
                    end else begin
                        gate_nearzero_mask <= pred_gate;
                        up_nearzero_mask <= pred_up;
                        skip_mask <= pred_skip;
                        outlier_count <= pred_outliers;
                    end
                    state <= Holding;
                end
                Holding: if (out_ready) state <= Idle;
                default: state <= Idle;
            endcase
        end
    end
endmodule
