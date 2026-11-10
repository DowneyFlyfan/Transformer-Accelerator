`timescale 1ns/1ps
// Attention and learned feed-forward share one tensor fabric and one read bus.
// Attention cache writes and value reads retain their native vector interface.
// At a tensor command boundary, a pending feed-forward frame takes priority.
module tri_oracle_shared_layer437 #(
    parameter bit PERSIST_LAYER_CONTEXT = 0,
    parameter bit COMPILED_SIGN_BANK = 0,
    parameter bit AGGREGATOR_SIGN_BANK = COMPILED_SIGN_BANK,
    parameter bit CORE_STRIP_PREDICTOR = AGGREGATOR_SIGN_BANK,
    parameter bit CORE_HEAD_PREDICTOR = CORE_STRIP_PREDICTOR
) (
    input logic clk, rst_n, cfg_valid,
    output logic cfg_ready,
    input logic [31:0] cfg_tag,
    input logic [4:0] cfg_tokens,
    input logic [15:0] cfg_input_features, cfg_intermediate_features,
    input logic [16:0] cfg_output_features,
    input logic [63:0] cfg_activation_base, cfg_gate_base, cfg_up_base, cfg_down_base, cfg_intermediate_base,
    input logic [31:0] cfg_activation_stride,
    input logic [95:0] cfg_gate_shifts, cfg_up_shifts, cfg_down_shifts, cfg_activation_shifts,
    input logic [63:0] cfg_gate_sign_base, cfg_up_sign_base,
    input logic [31:0] cfg_epsilon_q16,
    output logic [3:0] residual_token,
    input logic stats_valid, stats_last,
    output logic stats_ready,
    input logic [127:0] stats_data,
    input logic replay_valid, replay_last,
    output logic replay_ready,
    input logic [127:0] replay_data, replay_gamma,
    output logic out_valid,
    input logic out_ready,
    output logic [31:0] out_tag,
    output logic [3:0] out_token,
    output logic [15:0] out_start,
    output logic [7:0] out_count,
    output logic out_last,
    output logic [5119:0] out_data,
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
    output logic wr_rsp_ready,

    input logic projection_valid,
    output logic projection_ready,
    input logic [31:0] projection_tag,
    input logic [4:0] projection_tokens,
    input logic [5:0] projection_first_head, projection_heads,
    input logic [9:0] projection_slot,
    input logic [63:0] projection_activation_base, projection_weight_base, projection_cache_base,
    input logic [239:0] projection_shifts,
    input logic [95:0] projection_shift_biases,
    input logic angle_valid, angle_last,
    output logic angle_ready,
    input logic [511:0] angle_cos, angle_sin,
    output logic projection_done_valid, projection_done_error,
    input logic projection_done_ready,
    output logic [31:0] projection_done_tag,

    output logic cache_write_valid,
    input logic cache_write_ready,
    output logic [63:0] cache_write_address,
    output logic [511:0] cache_write_data,
    input logic cache_write_rsp_valid, cache_write_rsp_error,
    output logic cache_write_rsp_ready,

    input logic frame_valid, frame_new_image,
    input logic [4:0] frame_layer,
    output logic frame_ready,
    input logic [11:0] frame_minimum_matches,
    input logic [9:0] frame_image_start,
    input logic sign_valid,
    output logic sign_ready,
    input logic [2047:0] sign_data,
    output logic map_valid, map_last,
    input logic map_ready,
    output logic [9:0] map_index, map_origin,
    output logic frame_done_valid, frame_done_error,
    input logic frame_done_ready,
    input logic restore_valid,
    input logic [4:0] restore_layer,
    output logic restore_ready, restore_done_valid, restore_done_error,
    input logic restore_done_ready,

    input logic head_valid,
    output logic head_ready,
    input logic [4:0] head_id,
    input logic [31:0] head_tag, head_alpha,
    input logic [10:0] head_tokens,
    input logic [7:0] head_ratio_num, head_ratio_den,
    input logic [63:0] head_query_base, head_key_base,
    output logic head_done_valid, head_done_error, head_done_streaming,
    input logic head_done_ready,
    output logic [31:0] head_done_tag,
    output logic [4:0] head_done_id,
    output logic [17:0] head_done_inner, head_done_recent,

    input logic row_valid,
    output logic row_ready,
    input logic [4:0] row_head,
    input logic [10:0] row_position, row_key_count,
    input logic [31:0] row_tag,
    input logic signed [6:0] row_score_shift,
    input logic [63:0] row_query_addr, row_key_base,
    output logic result_valid, result_error,
    input logic result_ready,
    output logic [31:0] result_tag,
    output logic [2047:0] result_values,

    output logic value_req_valid,
    input logic value_req_ready,
    output logic [9:0] value_req_rank,
    input logic value_rsp_valid, value_rsp_error,
    output logic value_rsp_ready,
    input logic [511:0] value_rsp_data
);
    tri_oracle_attention_tensor437 attention();

    logic [12:0] merge_sign_control;
    logic [119:0] merge_sign_counts;
    logic [399:0] head_request;
    logic [72:0] head_response;

    if (AGGREGATOR_SIGN_BANK && !COMPILED_SIGN_BANK) begin : invalid_sign_bank
        initial $fatal(1, "Aggregator sign banks require the compiled read schedule");
    end

    tri_oracle_batched_learned437 #(
        .AGGREGATOR_SIGN_BANK(AGGREGATOR_SIGN_BANK), .CORE_STRIP_PREDICTOR(CORE_STRIP_PREDICTOR),
        .CORE_HEAD_PREDICTOR(CORE_HEAD_PREDICTOR)
    ) feedforward (
        .head_request, .head_response,
        .attention, .merge_sign_data(sign_data), .merge_sign_control, .merge_sign_counts, .*
    );
    tri_oracle_attention_pipeline430 #(
        .PERSIST_LAYER_CONTEXT(PERSIST_LAYER_CONTEXT), .COMPILED_SIGN_BANK(COMPILED_SIGN_BANK),
        .AGGREGATOR_SIGN_BANK(AGGREGATOR_SIGN_BANK), .CORE_HEAD_PREDICTOR(CORE_HEAD_PREDICTOR)
    ) attention_pipeline (
        .head_request, .head_response,
        .merge_sign_control, .merge_sign_counts,
        .tensor_cfg_feature_words(attention.cfg_feature_words),
        .tensor_cfg_activation_stride(attention.cfg_activation_stride),
        .tensor_cfg_valid(attention.cfg_valid),
        .tensor_cfg_ready(attention.cfg_ready),
        .tensor_cfg_tag(attention.cfg_tag),
        .tensor_cfg_tokens(attention.cfg_tokens),
        .tensor_cfg_count(attention.cfg_count),
        .tensor_cfg_dense_rows(attention.cfg_dense_rows),
        .tensor_cfg_channels(attention.cfg_channels),
        .tensor_cfg_keep(attention.cfg_keep),
        .tensor_cfg_activation_base(attention.cfg_activation_base),
        .tensor_cfg_weight_base(attention.cfg_weight_base),
        .tensor_out_valid(attention.out_valid),
        .tensor_out_last(attention.out_last),
        .tensor_out_ready(attention.out_ready),
        .tensor_out_tag(attention.out_tag),
        .tensor_out_token(attention.out_token),
        .tensor_out_count(attention.out_count),
        .tensor_out_channels(attention.out_channels),
        .tensor_out_data(attention.out_data),
        .tensor_done_valid(attention.done_valid),
        .tensor_done_error(attention.done_error),
        .tensor_done_ready(attention.done_ready),
        .tensor_done_tag(attention.done_tag),
        .*
    );
endmodule
