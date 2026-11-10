`timescale 1ns/1ps
// One tensor owner serves projection and attention. Projection slots become
// visible to the caller only when the tagged projection completion succeeds.
module tri_oracle_attention_pipeline430 #(
    parameter bit PERSIST_LAYER_CONTEXT=0,
    parameter bit COMPILED_SIGN_BANK=0
) (
    input logic clk, rst_n,
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

    output logic [9:0] tensor_cfg_feature_words,
    output logic [31:0] tensor_cfg_activation_stride,
    output logic tensor_cfg_valid,
    input logic tensor_cfg_ready,
    output logic [31:0] tensor_cfg_tag,
    output logic [4:0] tensor_cfg_tokens,
    output logic [7:0] tensor_cfg_count,
    output logic [16:0] tensor_cfg_dense_rows,
    output logic [2559:0] tensor_cfg_channels, tensor_cfg_keep,
    output logic [63:0] tensor_cfg_activation_base, tensor_cfg_weight_base,
    input logic tensor_out_valid, tensor_out_last,
    output logic tensor_out_ready,
    input logic [31:0] tensor_out_tag,
    input logic [3:0] tensor_out_token,
    input logic [7:0] tensor_out_count,
    input logic [2559:0] tensor_out_channels,
    input logic [5119:0] tensor_out_data,
    input logic tensor_done_valid, tensor_done_error,
    output logic tensor_done_ready,
    input logic [31:0] tensor_done_tag,

    output logic value_req_valid,
    input logic value_req_ready,
    output logic [9:0] value_req_rank,
    input logic value_rsp_valid, value_rsp_error,
    output logic value_rsp_ready,
    input logic [511:0] value_rsp_data
);
    typedef struct packed {
        logic valid;
        logic [31:0] tag;
        logic [4:0] tokens;
        logic [7:0] count;
        logic [2559:0] channels, keep;
        logic [63:0] activation_base, weight_base;
    } tensor_request_t;

    tensor_request_t projection_request, attention_request;
    logic projection_busy, rejected_projection, projection_start, cache_bounds_ok;
    logic [31:0] rejected_tag;
    logic qkv_ready, store_ready, stored_valid, stored_error;
    logic [31:0] stored_tag;
    logic native_frame_ready, native_restore_ready, native_head_ready, native_row_ready;
    logic projection_out_ready, projection_terminal_ready, attention_out_ready, attention_terminal_ready;
    logic [16:0] attention_dense_rows;
    logic vector_valid, vector_ready, vector_last;
    logic [31:0] vector_tag, qkv_done_tag;
    logic [5:0] vector_head;
    logic [3:0] vector_token;
    logic [511:0] vector_data;
    logic qkv_done_valid, qkv_done_ready, qkv_done_error;

    assign cache_bounds_ok = projection_cache_base[5:0]==0 &&
                             projection_cache_base<=64'hffffffffffffffff-64'd2621439 &&
                             11'(projection_slot)+11'(projection_tokens)<=1024;
    assign projection_ready = !projection_busy && native_frame_ready && qkv_ready && store_ready &&
                              !frame_valid && !(PERSIST_LAYER_CONTEXT && restore_valid) && !head_valid && !row_valid;
    assign projection_start = projection_valid && projection_ready && cache_bounds_ok;
    assign projection_done_valid = projection_busy && (rejected_projection || stored_valid);
    assign projection_done_error = rejected_projection || stored_error;
    assign projection_done_tag = rejected_projection ? rejected_tag : stored_tag;
    assign frame_ready = !projection_busy && native_frame_ready;
    assign restore_ready = !projection_busy && native_restore_ready;
    assign head_ready = !projection_busy && native_head_ready;
    assign row_ready = !projection_busy && native_row_ready;

    assign {tensor_cfg_valid,tensor_cfg_tag,tensor_cfg_tokens,tensor_cfg_count,tensor_cfg_channels,
            tensor_cfg_keep,tensor_cfg_activation_base,tensor_cfg_weight_base}
        = projection_busy ? projection_request : attention_request;
    assign tensor_cfg_feature_words = projection_busy ? 10'd256 : 10'd8;
    assign tensor_cfg_activation_stride = projection_busy ? 32'd2048 : 32'd64;
    assign tensor_cfg_dense_rows = projection_busy ? 17'd2560 : attention_dense_rows;
    assign tensor_out_ready = projection_busy ? projection_out_ready : attention_out_ready;
    assign tensor_done_ready = projection_busy ? projection_terminal_ready : attention_terminal_ready;

    tri_oracle_qkv429 projection (
        .clk,.rst_n,.cfg_valid(projection_start),.cfg_ready(qkv_ready),
        .cfg_tokens(projection_tokens),.cfg_start_head(projection_first_head),.cfg_heads(projection_heads),
        .cfg_tag(projection_tag),.cfg_activation_base(projection_activation_base),.cfg_weight_base(projection_weight_base),
        .cfg_shifts(projection_shifts),.cfg_shift_biases(projection_shift_biases),
        .angle_valid,.angle_last,.angle_ready,.angle_cos,.angle_sin,
        .out_valid(vector_valid),.out_ready(vector_ready),.out_last(vector_last),.out_tag(vector_tag),
        .out_head(vector_head),.out_token(vector_token),.out_data(vector_data),
        .done_valid(qkv_done_valid),.done_ready(qkv_done_ready),.done_error(qkv_done_error),.done_tag(qkv_done_tag),
        .tensor_cfg_valid(projection_request.valid),.tensor_cfg_ready(projection_busy && tensor_cfg_ready),
        .tensor_cfg_tag(projection_request.tag),.tensor_cfg_tokens(projection_request.tokens),
        .tensor_cfg_count(projection_request.count),.tensor_cfg_channels(projection_request.channels),
        .tensor_cfg_keep(projection_request.keep),.tensor_cfg_activation_base(projection_request.activation_base),
        .tensor_cfg_weight_base(projection_request.weight_base),
        .tensor_out_valid(projection_busy && tensor_out_valid),.tensor_out_last,.tensor_out_ready(projection_out_ready),
        .tensor_out_tag,.tensor_out_token,.tensor_out_count,.tensor_out_channels,.tensor_out_data(tensor_out_data[4095:0]),
        .tensor_done_valid(projection_busy && tensor_done_valid),.tensor_done_error,
        .tensor_done_ready(projection_terminal_ready),.tensor_done_tag
    );

    tri_oracle_qkv_store430 cache_writer (
        .clk,.rst_n,.cfg_valid(projection_start),.cfg_ready(store_ready),.cfg_tag(projection_tag),
        .cfg_tokens(projection_tokens),.cfg_first_head(projection_first_head),.cfg_heads(projection_heads),
        .cfg_slot(projection_slot),.cfg_base(projection_cache_base),
        .source_valid(vector_valid),.source_last(vector_last),.source_ready(vector_ready),.source_tag(vector_tag),
        .source_head(vector_head),.source_token(vector_token),.source_data(vector_data),
        .source_done_valid(qkv_done_valid),.source_done_error(qkv_done_error),
        .source_done_ready(qkv_done_ready),.source_done_tag(qkv_done_tag),
        .write_valid(cache_write_valid),.write_ready(cache_write_ready),.write_address(cache_write_address),
        .write_data(cache_write_data),.write_rsp_valid(cache_write_rsp_valid),.write_rsp_error(cache_write_rsp_error),
        .write_rsp_ready(cache_write_rsp_ready),.done_valid(stored_valid),.done_error(stored_error),
        .done_ready(projection_done_ready && projection_busy && !rejected_projection),.done_tag(stored_tag)
    );

    tri_oracle_attention_layer427 #(
        .PERSIST_LAYER_CONTEXT(PERSIST_LAYER_CONTEXT), .COMPILED_SIGN_BANK(COMPILED_SIGN_BANK)
    ) attention (
        .clk,.rst_n,.frame_valid(frame_valid && !projection_busy),.frame_ready(native_frame_ready),
        .frame_new_image,.frame_layer,.frame_minimum_matches,.frame_image_start,
        .sign_valid,.sign_ready,.sign_data,.map_valid,.map_last,.map_ready,.map_index,.map_origin,
        .frame_done_valid,.frame_done_error,.frame_done_ready,
        .restore_valid(restore_valid && !projection_busy),.restore_layer,.restore_ready(native_restore_ready),
        .restore_done_valid,.restore_done_error,.restore_done_ready,
        .head_valid(head_valid && !projection_busy),.head_ready(native_head_ready),
        .head_id,.head_tag,.head_alpha,.head_tokens,.head_ratio_num,.head_ratio_den,.head_query_base,.head_key_base,
        .head_done_valid,.head_done_error,.head_done_streaming,.head_done_ready,.head_done_tag,
        .head_done_id,.head_done_inner,.head_done_recent,
        .row_valid(row_valid && !projection_busy),.row_ready(native_row_ready),.row_head,.row_position,.row_key_count,
        .row_tag,.row_score_shift,.row_query_addr,.row_key_base,.result_valid,.result_error,.result_ready,.result_tag,.result_values,
        .tensor_cfg_valid(attention_request.valid),.tensor_cfg_ready(!projection_busy && tensor_cfg_ready),
        .tensor_cfg_tag(attention_request.tag),.tensor_cfg_tokens(attention_request.tokens),.tensor_cfg_count(attention_request.count),
        .tensor_cfg_dense_rows(attention_dense_rows),.tensor_cfg_channels(attention_request.channels),.tensor_cfg_keep(attention_request.keep),
        .tensor_cfg_activation_base(attention_request.activation_base),.tensor_cfg_weight_base(attention_request.weight_base),
        .tensor_out_valid(!projection_busy && tensor_out_valid),.tensor_out_last,.tensor_out_ready(attention_out_ready),
        .tensor_out_tag,.tensor_out_token,.tensor_out_count,.tensor_out_channels,.tensor_out_data,
        .tensor_done_valid(!projection_busy && tensor_done_valid),.tensor_done_error,
        .tensor_done_ready(attention_terminal_ready),.tensor_done_tag,
        .value_req_valid,.value_req_ready,.value_req_rank,.value_rsp_valid,.value_rsp_error,.value_rsp_ready,.value_rsp_data
    );

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            projection_busy<=0;
            rejected_projection<=0;
            rejected_tag<=0;
        end else if (projection_valid && projection_ready) begin
            projection_busy<=1;
            rejected_projection<=!cache_bounds_ok;
            rejected_tag<=projection_tag;
        end else if (projection_done_valid && projection_done_ready) begin
            projection_busy<=0;
            rejected_projection<=0;
        end
    end
endmodule
