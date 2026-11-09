`timescale 1ns/1ps
// Raw-residual prediction, packed sign reads and gate/up/down computation.
// Compute activation memory already contains quantized learned-scale values.
// One memory transaction is outstanding; ownership lasts through actual LAST.
// Faulted tensors drain internally and publish only one terminal error packet.
// Reset requires the external memory peer to reset outstanding transactions too.
module tri_oracle_normalized_feedforward_core (
    input logic clk,rst_n,cfg_valid,
    output logic cfg_ready,
    input logic [31:0] cfg_tag,cfg_epsilon_q16,
    input logic [63:0] cfg_activation_base,cfg_weight_base,cfg_up_weight_base,
    input logic [63:0] cfg_down_weight_base,cfg_gate_sign_base,cfg_up_sign_base,
    input logic [5:0] cfg_gate_shift,cfg_up_shift,cfg_down_shift,
    input logic [9:0] cfg_features,
    input logic [16:0] cfg_dense_features,
    input logic [15:0] cfg_output_start,
    input logic [8:0] cfg_output_count,
    input logic group_valid,
    output logic group_ready,
    input logic [10:0] group_id,
    input logic group_last,stats_valid,
    output logic stats_ready,
    input logic stats_last,
    input logic [127:0] stats_data,
    input logic replay_valid,
    output logic replay_ready,
    input logic replay_last,
    input logic [127:0] replay_data,
    output logic out_valid,
    input logic out_ready,
    output logic out_last,out_fallback,out_error,
    output logic [31:0] out_tag,
    output logic [5:0] out_count,
    output logic [511:0] out_channels,
    output logic [1023:0] out_data,
    output logic req_valid,
    input logic req_ready,
    output logic [63:0] req_address,
    output logic [4:0] req_length,
    input logic rsp_valid,rsp_last,rsp_error,
    output logic rsp_ready,
    input logic [63:0] rsp_data
);
    logic common_cfg_ready,common_group_ready,norm_cfg_ready;
    logic [31:0] tag,epsilon_q16;
    logic [9:0] features;
    logic norm_valid,norm_ready,norm_last,norm_error;
    logic [31:0] unused_norm_tag;
    logic [9:0] norm_index;
    logic [3:0] unused_norm_count;
    logic [127:0] norm_data;
    logic [7:0] unused_norm_outliers;
    always_comb begin
        cfg_ready=common_cfg_ready && norm_cfg_ready;
        group_ready=common_group_ready && norm_cfg_ready;
    end
    tri_oracle_rmsnorm normalizer (
        .clk(clk),.rst_n(rst_n),.cfg_valid(group_valid && group_ready),
        .cfg_ready(norm_cfg_ready),.cfg_tag(tag),.cfg_strips(features),
        .cfg_epsilon_q16(epsilon_q16),.stats_valid(stats_valid),.stats_ready(stats_ready),
        .stats_last(stats_last),.stats_data(stats_data),.replay_valid(replay_valid),
        .replay_ready(replay_ready),.replay_last(replay_last),.replay_data(replay_data),
        .out_valid(norm_valid),.out_ready(norm_ready),.out_last(norm_last),
        .out_error(norm_error),.out_tag(unused_norm_tag),.out_index(norm_index),
        .out_count(unused_norm_count),.out_norm_q8(norm_data),.out_outlier_mask(unused_norm_outliers)
    );
    tri_oracle_prediction_feedforward_core execution (
        .cfg_valid(cfg_valid && norm_cfg_ready),.cfg_ready(common_cfg_ready),
        .group_valid(group_valid && norm_cfg_ready),.group_ready(common_group_ready),.*
    );
    always_ff @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin tag<='0;features<='0;epsilon_q16<='0;end
        else if(cfg_valid && cfg_ready) begin
            tag<=cfg_tag;features<=cfg_features;epsilon_q16<=cfg_epsilon_q16;
        end
    end
endmodule
