`timescale 1ns/1ps
// Root-mean-square normalization, learned scale and signed8 activation generation.
// Learned coefficients accompany replay handshakes; prediction remains pre-scale.
// Earlier words are provisional until the terminal non-error result is consumed.
module tri_oracle_rms_activation (
    input logic clk,rst_n,cfg_valid,
    output logic cfg_ready,
    input logic [31:0] cfg_tag,cfg_epsilon_q16,
    input logic [9:0] cfg_strips,
    input logic [5:0] cfg_shift,
    input logic stats_valid,
    output logic stats_ready,
    input logic stats_last,
    input logic [127:0] stats_data,
    input logic replay_valid,
    output logic replay_ready,
    input logic replay_last,
    input logic [127:0] replay_data,replay_gamma,
    output logic out_valid,
    input logic out_ready,
    output logic out_last,out_error,
    output logic [31:0] out_tag,
    output logic [9:0] out_index,
    output logic [3:0] out_count,
    output logic [127:0] out_norm_q8,
    output logic [7:0] out_outlier_mask,
    output logic [63:0] out_activation
);
    logic active;
    logic [5:0] shift;
    logic [127:0] gamma;
    logic norm_cfg_ready,norm_stats_ready,norm_replay_ready;
    logic norm_valid,norm_ready,norm_last,norm_error,quant_ready;
    logic [31:0] norm_tag;
    logic [9:0] norm_index;
    logic [3:0] norm_count;
    logic [127:0] norm_data;
    logic [7:0] norm_outliers;
    always_comb begin
        cfg_ready=!active && norm_cfg_ready;
        stats_ready=active && norm_stats_ready;
        replay_ready=active && norm_replay_ready;
        norm_ready=active && quant_ready;
    end
    tri_oracle_rmsnorm normalizer (
        .clk(clk),.rst_n(rst_n),.cfg_valid(cfg_valid && cfg_ready),
        .cfg_ready(norm_cfg_ready),.cfg_tag(cfg_tag),.cfg_strips(cfg_strips),
        .cfg_epsilon_q16(cfg_epsilon_q16),
        .stats_valid(active && stats_valid),.stats_ready(norm_stats_ready),
        .stats_last(stats_last),.stats_data(stats_data),
        .replay_valid(active && replay_valid),.replay_ready(norm_replay_ready),
        .replay_last(replay_last),.replay_data(replay_data),
        .out_valid(norm_valid),.out_ready(norm_ready),.out_last(norm_last),
        .out_error(norm_error),.out_tag(norm_tag),.out_index(norm_index),
        .out_count(norm_count),.out_norm_q8(norm_data),.out_outlier_mask(norm_outliers)
    );
    tri_oracle_affine_quantizer quantizer (
        .clk(clk),.rst_n(rst_n),.in_valid(active && norm_valid),.in_ready(quant_ready),
        .in_last(norm_last),.in_error(norm_error),.in_tag(norm_tag),.in_index(norm_index),
        .in_count(norm_count),.in_norm_q8(norm_data),.in_gamma(gamma),.in_shift(shift),
        .in_outlier_mask(norm_outliers),.out_valid(out_valid),.out_ready(out_ready),
        .out_last(out_last),.out_error(out_error),.out_tag(out_tag),.out_index(out_index),
        .out_count(out_count),.out_norm_q8(out_norm_q8),.out_outlier_mask(out_outlier_mask),
        .out_activation(out_activation)
    );
    always_ff @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin active<=0;shift<='0;gamma<='0;end
        else begin
            if(cfg_valid && cfg_ready) begin active<=1;shift<=cfg_shift;end
            if(replay_valid && replay_ready) gamma<=replay_gamma;
            if(out_valid && out_ready && out_last) active<=0;
        end
    end
endmodule
