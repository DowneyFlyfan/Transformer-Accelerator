`timescale 1ns/1ps
// One32-output prediction group from raw residual strips and packed sign memory.
// Statistics/replay precision follows tri_oracle_rmsnorm. Learned gamma is excluded.
// Any normalization/sign-memory error rejects all masks after the raw frame drains.
module tri_oracle_rms_sign_predictor (
    input logic clk, rst_n, cfg_valid,
    output logic cfg_ready,
    input logic [31:0] cfg_tag,
    input logic [10:0] cfg_group,
    input logic [9:0] cfg_strips,
    input logic [31:0] cfg_epsilon_q16,
    input logic [63:0] cfg_gate_sign_base, cfg_up_sign_base,
    input logic stats_valid,
    output logic stats_ready,
    input logic stats_last,
    input logic [127:0] stats_data,
    input logic replay_valid,
    output logic replay_ready,
    input logic replay_last,
    input logic [127:0] replay_data,
    output logic out_valid,
    input logic out_ready,
    output logic out_error,
    output logic [31:0] out_tag, gate_nearzero_mask, up_nearzero_mask, skip_mask,
    output logic [12:0] outlier_count,
    output logic req_valid,
    input logic req_ready,
    output logic [63:0] req_address,
    output logic [4:0] req_length,
    input logic rsp_valid,
    output logic rsp_ready,
    input logic rsp_last, rsp_error,
    input logic [63:0] rsp_data
);
    typedef enum logic [1:0] {Idle, Run, Wait, Holding} state_t;
    state_t state;
    logic [31:0] tag;
    logic [10:0] group_id;
    logic [9:0] strips;
    logic [63:0] gate_base, up_base;
    logic frame_fault;
    logic norm_cfg_ready, norm_stats_ready, norm_replay_ready;
    logic norm_valid, norm_ready, norm_last, norm_error;
    logic [31:0] unused_norm_tag;
    logic [9:0] norm_index;
    logic [3:0] unused_norm_count;
    logic [127:0] norm_data;
    logic [7:0] unused_norm_outliers;
    logic fetch_in_ready, fetch_valid, fetch_ready, fetch_last, fetch_error;
    logic [31:0] unused_fetch_tag;
    logic [10:0] unused_fetch_group;
    logic [9:0] unused_fetch_index;
    logic [127:0] fetch_data;
    logic [255:0] gate_signs, up_signs;
    logic pred_in_ready, pred_valid, pred_ready, pred_error;
    logic [31:0] pred_gate, pred_up, pred_skip;
    logic [12:0] pred_outliers;

    always_comb begin
        cfg_ready = state == Idle && norm_cfg_ready;
        stats_ready = state == Run && norm_stats_ready;
        replay_ready = state == Run && norm_replay_ready;
        norm_ready = state == Run && fetch_in_ready;
        fetch_ready = state == Run && pred_in_ready;
        pred_ready = state == Wait;
        out_valid = state == Holding;
        out_tag = tag;
    end

    tri_oracle_rmsnorm normalizer (
        .clk(clk), .rst_n(rst_n),
        .cfg_valid(state == Idle && cfg_valid), .cfg_ready(norm_cfg_ready),
        .cfg_tag(cfg_tag), .cfg_strips(cfg_strips), .cfg_epsilon_q16(cfg_epsilon_q16),
        .stats_valid(state == Run && stats_valid), .stats_ready(norm_stats_ready),
        .stats_last(stats_last), .stats_data(stats_data),
        .replay_valid(state == Run && replay_valid), .replay_ready(norm_replay_ready),
        .replay_last(replay_last), .replay_data(replay_data),
        .out_valid(norm_valid), .out_ready(norm_ready), .out_last(norm_last),
        .out_error(norm_error), .out_tag(unused_norm_tag), .out_index(norm_index),
        .out_count(unused_norm_count), .out_norm_q8(norm_data),
        .out_outlier_mask(unused_norm_outliers)
    );

    tri_oracle_sign_fetch signs (
        .clk(clk), .rst_n(rst_n),
        .in_valid(state == Run && norm_valid), .in_ready(fetch_in_ready),
        .in_tag(tag), .in_group(group_id), .in_strips(strips), .in_index(norm_index),
        .in_last(norm_last), .in_error(norm_error || frame_fault), .in_norm_q8(norm_data),
        .in_gate_base(gate_base), .in_up_base(up_base),
        .out_valid(fetch_valid), .out_ready(fetch_ready),
        .out_last(fetch_last), .out_error(fetch_error), .out_tag(unused_fetch_tag),
        .out_group(unused_fetch_group), .out_index(unused_fetch_index),
        .out_norm_q8(fetch_data), .out_gate_signs(gate_signs), .out_up_signs(up_signs),
        .req_valid(req_valid), .req_ready(req_ready), .req_address(req_address),
        .req_length(req_length), .rsp_valid(rsp_valid), .rsp_ready(rsp_ready),
        .rsp_last(rsp_last), .rsp_error(rsp_error), .rsp_data(rsp_data)
    );

    tri_oracle_strip_predictor predictor (
        .clk(clk), .rst_n(rst_n),
        .in_valid(state == Run && fetch_valid), .in_last(fetch_last),
        .out_ready(pred_ready), .norm_activations(fetch_data),
        .gate_weight_signs(gate_signs), .up_weight_signs(up_signs),
        .in_ready(pred_in_ready), .out_valid(pred_valid), .out_error(pred_error),
        .gate_nearzero_mask(pred_gate), .up_nearzero_mask(pred_up),
        .skip_mask(pred_skip), .outlier_count(pred_outliers)
    );

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= Idle;
            tag <= '0;
            group_id <= '0;
            strips <= '0;
            gate_base <= '0;
            up_base <= '0;
            frame_fault <= 1'b0;
            out_error <= 1'b0;
            gate_nearzero_mask <= '0;
            up_nearzero_mask <= '0;
            skip_mask <= '0;
            outlier_count <= '0;
        end else begin
            case (state)
                Idle: if (cfg_valid && cfg_ready) begin
                    tag <= cfg_tag;
                    group_id <= cfg_group;
                    strips <= cfg_strips;
                    gate_base <= cfg_gate_sign_base;
                    up_base <= cfg_up_sign_base;
                    frame_fault <= 1'b0;
                    out_error <= 1'b0;
                    state <= Run;
                end
                Run: if (fetch_valid && fetch_ready) begin
                    frame_fault <= frame_fault || fetch_error;
                    if (fetch_last) state <= Wait;
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
