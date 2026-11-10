`timescale 1ns/1ps
// One layer of compact attention. Prediction and value-producing rows share
// the same ordinary tensor owner with eight 64-bit words per operand vector.
// Prediction query memory starts at compact position 96. The caller compacts
// tensors according to the emitted map and retains them across decode rows.
module tri_oracle_attention_layer427 #(parameter bit PERSIST_LAYER_CONTEXT=0) (
    input logic clk, rst_n,
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
    localparam logic [9:0] IMAGE_TOKENS=10'd576;
    typedef enum logic [3:0] {
        Idle, Merge, PadFrame, WaitFrame, FrameResult, RunHead, HeadResult, RunRow, RejectRow,
        RestoreMap, WaitRestore, RestoreResult
    } state_t;
    typedef struct packed {
        logic valid;
        logic [31:0] tag;
        logic [4:0] tokens;
        logic [7:0] count;
        logic [16:0] dense_rows;
        logic [2559:0] channels, keep;
        logic [63:0] activation_base, weight_base;
    } tensor_command_t;

    state_t state;
    tensor_command_t head_command, row_command;
    logic [31:0] known_heads, head_types;
    logic layer_loaded, frame_failed, merge_sequence_valid;
    logic [9:0] map_count, roots, image_start;
    logic [11:0] merge_threshold;
    logic merge_cfg_ready, merge_map_valid, merge_done_valid, merge_done_error, map_transfer;
    logic row_frame_ready, row_frame_error, row_map_valid, row_map_ready;
    logic [9:0] row_map_origin;
    logic predictor_ready, predictor_valid, predictor_error, predictor_streaming;
    logic [31:0] predictor_tag;
    logic [17:0] predictor_inner, predictor_recent;
    logic head_descriptor_ok, use_predictor, row_allowed, native_row_ready;
    logic native_result_valid, native_result_error;
    logic [31:0] native_result_tag, rejected_row_tag;
    logic [2047:0] native_result_values;
    logic head_tensor_out_ready, head_tensor_done_ready, row_tensor_out_ready, row_tensor_done_ready;
    logic [21:0] stored_valid;
    logic [31:0] stored_known[22], stored_types[22];
    logic [9:0] stored_image_start[22], stored_roots[22];
    logic [4:0] resident_layer, next_merge_layer;
    logic frame_descriptor_ok, restore_allowed, frame_start, restore_start;
    logic store_idle, store_save_ready, store_restore_valid, store_restore_last;
    logic [9:0] store_restore_origin;

    assign frame_ready = state==Idle && merge_cfg_ready && row_frame_ready && store_idle;
    assign frame_descriptor_ok = !PERSIST_LAYER_CONTEXT || (frame_layer<22 &&
                                  (frame_new_image ? frame_layer==0 : frame_layer==next_merge_layer));
    assign frame_start = frame_valid && frame_ready && frame_descriptor_ok;
    assign frame_done_valid = state==FrameResult;
    assign frame_done_error = frame_failed;
    assign restore_ready = PERSIST_LAYER_CONTEXT && state==Idle && !frame_valid && store_idle && row_frame_ready;
    assign restore_allowed = restore_layer<22 && stored_valid[restore_layer];
    assign restore_start = restore_valid && restore_ready && restore_allowed;
    assign restore_done_valid = state==RestoreResult;
    // A rejected fresh image must not expose the previous image's merger state.
    assign merge_threshold = frame_new_image || merge_sequence_valid ? frame_minimum_matches : 12'hfff;
    // The internal and external consumers accept each real map word together.
    assign map_valid = state==Merge && merge_map_valid && row_map_ready && store_save_ready;
    assign map_transfer = map_valid && map_ready;
    assign row_map_valid = (state==Merge && merge_map_valid && map_ready && store_save_ready) ||
                           state==PadFrame || (state==RestoreMap && store_restore_valid);
    // If merging terminates early, an invalid origin forces the row loader to
    // drain its fixed-length frame. Padding is internal to the failed frame.
    assign row_map_origin = state==PadFrame ? 10'h3ff : state==RestoreMap ? store_restore_origin : map_origin;

    assign head_descriptor_ok = layer_loaded && head_tokens>=11'(image_start)+11'(roots) &&
                                head_tokens<=1024 && head_ratio_den!=0;
    assign use_predictor = head_descriptor_ok && head_tokens>96;
    assign head_ready = state==Idle && !frame_valid && !(PERSIST_LAYER_CONTEXT && restore_valid) &&
                        (!use_predictor || predictor_ready);
    assign head_done_valid = state==HeadResult;
    assign row_allowed = layer_loaded && known_heads[row_head];
    assign row_ready = state==Idle && !frame_valid && !(PERSIST_LAYER_CONTEXT && restore_valid) && !head_valid &&
                       (!row_allowed || native_row_ready);

    assign result_valid = state==RejectRow || (state==RunRow && native_result_valid);
    assign result_error = state==RejectRow || (state==RunRow && native_result_error);
    assign result_tag = state==RejectRow ? rejected_row_tag : native_result_tag;
    assign result_values = state==RejectRow ? '0 : native_result_values;

    assign {tensor_cfg_valid, tensor_cfg_tag, tensor_cfg_tokens, tensor_cfg_count, tensor_cfg_dense_rows,
            tensor_cfg_channels, tensor_cfg_keep, tensor_cfg_activation_base, tensor_cfg_weight_base}
        = state==RunHead ? head_command : state==RunRow ? row_command : '0;
    assign head_command.count = 8'd96;
    assign row_command.tokens = 5'd1;
    assign tensor_out_ready = (state==RunHead && head_tensor_out_ready) || (state==RunRow && row_tensor_out_ready);
    assign tensor_done_ready = (state==RunHead && head_tensor_done_ready) || (state==RunRow && row_tensor_done_ready);

    if (PERSIST_LAYER_CONTEXT) begin : contexts
        tri_oracle_attention_context428 store (
            .clk, .rst_n, .idle(store_idle), .layer(restore_start ? restore_layer : frame_layer),
            .save_start(frame_start), .save_cancel(state==Merge && merge_done_valid && map_count!=IMAGE_TOKENS),
            .save_valid(map_transfer), .save_ready(store_save_ready), .save_origin(map_origin),
            .restore_start, .restore_ready(state==RestoreMap && row_map_ready),
            .restore_valid(store_restore_valid), .restore_last(store_restore_last), .restore_origin(store_restore_origin)
        );
    end else begin : no_contexts
        assign store_idle = 1;
        assign store_save_ready = 1;
        assign store_restore_valid = 0;
        assign store_restore_last = 0;
        assign store_restore_origin = 0;
    end

    tri_oracle_cumulative_token_merger423 merger (
        .clk, .rst_n, .cfg_valid(frame_start), .cfg_new_image(frame_new_image),
        .cfg_ready(merge_cfg_ready), .cfg_minimum_matches(merge_threshold),
        .sign_valid, .sign_ready, .sign_data, .map_valid(merge_map_valid),
        .map_ready(state==Merge && row_map_ready && map_ready && store_save_ready),
        .map_index, .map_origin, .map_last, .done_valid(merge_done_valid), .done_error(merge_done_error), .done_ready(state==Merge)
    );
    tri_oracle_attention_head_predictor415 predictor (
        .clk, .rst_n, .cfg_valid(head_valid && head_ready && use_predictor), .cfg_ready(predictor_ready),
        .cfg_tag(head_tag), .cfg_alpha(head_alpha), .cfg_tokens(13'(head_tokens)),
        .cfg_ratio_num(head_ratio_num), .cfg_ratio_den(head_ratio_den),
        .cfg_query_base(head_query_base), .cfg_key_base(head_key_base),
        .out_valid(predictor_valid), .out_ready(state==RunHead), .out_error(predictor_error), .out_streaming(predictor_streaming),
        .out_tag(predictor_tag), .out_inner(predictor_inner), .out_outer(predictor_recent),
        .tensor_cfg_valid(head_command.valid), .tensor_cfg_ready(state==RunHead && tensor_cfg_ready),
        .tensor_cfg_tag(head_command.tag), .tensor_cfg_tokens(head_command.tokens), .tensor_cfg_dense_rows(head_command.dense_rows),
        .tensor_cfg_channels(head_command.channels), .tensor_cfg_keep(head_command.keep),
        .tensor_cfg_activation_base(head_command.activation_base), .tensor_cfg_weight_base(head_command.weight_base),
        .tensor_out_valid(state==RunHead && tensor_out_valid), .tensor_out_last, .tensor_out_ready(head_tensor_out_ready),
        .tensor_out_tag, .tensor_out_token, .tensor_out_count, .tensor_out_data(tensor_out_data[3071:0]),
        .tensor_done_valid(state==RunHead && tensor_done_valid), .tensor_done_error,
        .tensor_done_ready(head_tensor_done_ready), .tensor_done_tag
    );
    tri_oracle_attention_row426 attention (
        .clk, .rst_n, .frame_valid(frame_start || restore_start), .frame_ready(row_frame_ready),
        .frame_error(row_frame_error), .frame_image_start(restore_start ? stored_image_start[restore_layer] : frame_image_start),
        .map_valid(row_map_valid), .map_ready(row_map_ready), .map_origin(row_map_origin),
        .row_valid(row_valid && row_ready && row_allowed), .row_ready(native_row_ready),
        .row_tag, .row_position, .row_key_count, .row_streaming(head_types[row_head]),
        .row_score_shift, .row_query_addr, .row_key_base,
        .result_valid(native_result_valid), .result_ready(state==RunRow && result_ready), .result_error(native_result_error),
        .result_tag(native_result_tag), .result_values(native_result_values),
        .tensor_cfg_valid(row_command.valid), .tensor_cfg_ready(state==RunRow && tensor_cfg_ready),
        .tensor_cfg_tag(row_command.tag), .tensor_cfg_count(row_command.count), .tensor_cfg_dense_rows(row_command.dense_rows),
        .tensor_cfg_channels(row_command.channels), .tensor_cfg_keep(row_command.keep),
        .tensor_cfg_activation_base(row_command.activation_base), .tensor_cfg_weight_base(row_command.weight_base),
        .tensor_out_valid(state==RunRow && tensor_out_valid), .tensor_out_last, .tensor_out_ready(row_tensor_out_ready),
        .tensor_out_tag, .tensor_out_token, .tensor_out_count, .tensor_out_channels, .tensor_out_data,
        .tensor_done_valid(state==RunRow && tensor_done_valid), .tensor_done_error,
        .tensor_done_ready(row_tensor_done_ready), .tensor_done_tag,
        .value_req_valid, .value_req_ready, .value_req_rank, .value_rsp_valid, .value_rsp_error, .value_rsp_ready, .value_rsp_data
    );

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= Idle;
            layer_loaded <= 0;
            frame_failed <= 0;
            merge_sequence_valid <= 0;
            map_count <= 0;
            roots <= 0;
            image_start <= 0;
            known_heads <= 0;
            head_types <= 0;
            head_done_tag <= 0;
            head_done_id <= 0;
            head_done_error <= 0;
            head_done_streaming <= 0;
            head_done_inner <= 0;
            head_done_recent <= 0;
            rejected_row_tag <= 0;
            stored_valid <= 0;
            resident_layer <= 0;
            next_merge_layer <= 0;
            restore_done_error <= 0;
        end else case (state)
            Idle: begin
                if (frame_valid && frame_ready) begin
                    layer_loaded <= 0;
                    frame_failed <= !frame_descriptor_ok;
                    known_heads <= 0;
                    // Only an invalid-threshold continuation preserves the prior
                    // committed origins. Any transaction that can modify them
                    // must finish successfully before another continuation.
                    if (frame_new_image || (frame_descriptor_ok && merge_threshold<=12'd2048)) merge_sequence_valid <= 0;
                    map_count <= 0;
                    roots <= 0;
                    image_start <= frame_image_start;
                    if (PERSIST_LAYER_CONTEXT) begin
                        if (frame_new_image) begin
                            stored_valid <= 0;
                            next_merge_layer <= 0;
                        end else if (frame_descriptor_ok) stored_valid[frame_layer] <= 0;
                        resident_layer <= frame_layer;
                    end
                    if (frame_descriptor_ok) state <= Merge;
                    else state <= FrameResult;
                end else if (restore_valid && restore_ready) begin
                    layer_loaded <= 0;
                    known_heads <= 0;
                    restore_done_error <= !restore_allowed;
                    if (restore_allowed) begin
                        resident_layer <= restore_layer;
                        image_start <= stored_image_start[restore_layer];
                        roots <= stored_roots[restore_layer];
                        state <= RestoreMap;
                    end else state <= RestoreResult;
                end else if (head_valid && head_ready) begin
                    head_done_id <= head_id;
                    head_done_tag <= head_tag;
                    head_done_error <= !head_descriptor_ok;
                    head_done_streaming <= 0;
                    head_done_inner <= 0;
                    head_done_recent <= 0;
                    known_heads[head_id] <= head_descriptor_ok && !use_predictor;
                    head_types[head_id] <= 0;
                    if (PERSIST_LAYER_CONTEXT && layer_loaded) begin
                        stored_known[resident_layer][head_id] <= head_descriptor_ok && !use_predictor;
                        stored_types[resident_layer][head_id] <= 0;
                    end
                    if (use_predictor) state <= RunHead;
                    else state <= HeadResult;
                end else if (row_valid && row_ready) begin
                    rejected_row_tag <= row_tag;
                    if (row_allowed) state <= RunRow;
                    else state <= RejectRow;
                end
            end
            Merge: begin
                if (map_transfer) begin
                    map_count <= map_count+1'b1;
                    if (map_index==map_origin) roots <= roots+1'b1;
                    if (map_index!=map_count || map_last!=(map_count==IMAGE_TOKENS-1'b1)) frame_failed <= 1;
                end
                if (merge_done_valid) begin
                    frame_failed <= frame_failed || merge_done_error || map_count!=IMAGE_TOKENS;
                    if (map_count==IMAGE_TOKENS) state <= WaitFrame;
                    else state <= PadFrame;
                end
            end
            PadFrame: if (row_map_ready) begin
                map_count <= map_count+1'b1;
                if (map_count==IMAGE_TOKENS-1'b1) state <= WaitFrame;
            end
            WaitFrame: if (row_frame_ready && store_idle) begin
                frame_failed <= frame_failed || row_frame_error;
                layer_loaded <= !frame_failed && !row_frame_error;
                if (!frame_failed && !row_frame_error) begin
                    merge_sequence_valid <= 1;
                    if (PERSIST_LAYER_CONTEXT) begin
                        stored_valid[resident_layer] <= 1;
                        stored_known[resident_layer] <= 0;
                        stored_types[resident_layer] <= 0;
                        stored_image_start[resident_layer] <= image_start;
                        stored_roots[resident_layer] <= roots;
                        next_merge_layer <= resident_layer+1'b1;
                    end
                end
                state <= FrameResult;
            end
            FrameResult: if (frame_done_ready) state <= Idle;
            RestoreMap: if (store_restore_valid && row_map_ready && store_restore_last) state <= WaitRestore;
            WaitRestore: if (row_frame_ready && store_idle) begin
                restore_done_error <= row_frame_error;
                layer_loaded <= !row_frame_error;
                if (row_frame_error) stored_valid[resident_layer] <= 0;
                else begin
                    known_heads <= stored_known[resident_layer];
                    head_types <= stored_types[resident_layer];
                end
                state <= RestoreResult;
            end
            RestoreResult: if (restore_done_ready) state <= Idle;
            RunHead: if (predictor_valid) begin
                head_done_error <= predictor_error || predictor_tag!=head_done_tag;
                if (!predictor_error && predictor_tag==head_done_tag) begin
                    known_heads[head_done_id] <= 1;
                    head_types[head_done_id] <= predictor_streaming;
                    if (PERSIST_LAYER_CONTEXT) begin
                        stored_known[resident_layer][head_done_id] <= 1;
                        stored_types[resident_layer][head_done_id] <= predictor_streaming;
                    end
                    head_done_streaming <= predictor_streaming;
                    head_done_inner <= predictor_inner;
                    head_done_recent <= predictor_recent;
                end
                state <= HeadResult;
            end
            HeadResult: if (head_done_ready) state <= Idle;
            RunRow: if (native_result_valid && result_ready) state <= Idle;
            RejectRow: if (result_ready) state <= Idle;
            default: begin
                layer_loaded <= 0;
                merge_sequence_valid <= 0;
                known_heads <= 0;
                state <= Idle;
            end
        endcase
    end
endmodule
