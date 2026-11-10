`timescale 1ns/1ps
// Generate learned activations and prediction masks from one residual pass
// per token. Compute starts after the frontend commits its activation writes.
// The two write phases share one port; each read burst keeps its owner until
// its last response beat. Terminal error invalidates this frame's writes and
// outputs. Complete an already-started residual token and withdraw any held
// offers before acknowledging an error. Reset also resets both bus peers.
module tri_oracle_batched_learned406 (
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
    output logic wr_rsp_ready
);
  tri_oracle_attention_tensor437 unused_attention();
  assign {unused_attention.cfg_valid, unused_attention.cfg_tag, unused_attention.cfg_activation_stride,
          unused_attention.cfg_tokens, unused_attention.cfg_feature_words, unused_attention.cfg_dense_rows,
          unused_attention.cfg_count, unused_attention.cfg_channels, unused_attention.cfg_keep,
          unused_attention.cfg_activation_base, unused_attention.cfg_weight_base,
          unused_attention.out_ready, unused_attention.done_ready} = '0;
  tri_oracle_batched_learned437 implementation (.attention(unused_attention), .merge_sign_data('0), .merge_sign_control('0), .merge_sign_counts(), .*);
endmodule

module tri_oracle_batched_learned437 #(
  parameter bit AGGREGATOR_SIGN_BANK=0,
  parameter bit CORE_STRIP_PREDICTOR=AGGREGATOR_SIGN_BANK
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
    tri_oracle_attention_tensor437.server attention,
    input logic [2047:0] merge_sign_data,
    input logic [12:0] merge_sign_control,
    output logic [119:0] merge_sign_counts
);
    typedef enum logic [1:0] {Idle, Active, Reject} frame_state_t;
    typedef enum logic [1:0] {PickRead, OfferRead, WaitRead} read_state_t;
    typedef struct packed {
        logic [4:0] tokens;
        logic [15:0] input_features, intermediate_features;
        logic [16:0] output_features;
        logic [63:0] activation_base, gate_base, up_base, down_base, intermediate_base;
        logic [31:0] activation_stride;
        logic [95:0] gate_shifts, up_shifts, down_shifts;
    } compute_descriptor_t;
    frame_state_t state;
    read_state_t read_state;
    compute_descriptor_t saved;
    logic [31:0] tag;
    logic compute_started, owner_compute, take_cfg, config_bad;
    logic [64:0] weight_bytes, sign_bytes, gate_sign_end, up_sign_end, scratch_end;
    logic [64:0] activation_end, gate_end, up_end, down_end;
    logic predict_ready, packet_ready, compute_ready, launch_compute, retire;
    logic predict_done, packet_done, compute_done;
    logic predict_error, packet_error, compute_error;
    logic predict_failed, packet_failed, compute_failed, cancel_packet, drop_predictions, abort_mask;
    logic [31:0] unused_predict_done_tag, unused_packet_done_tag, unused_compute_done_tag;
    logic prediction_valid, prediction_ready, prediction_last;
    logic [31:0] prediction_tag, prediction_skip, unused_gate_mask, unused_up_mask;
    logic [7:0] prediction_group;
    logic [3:0] prediction_token;
    logic [12:0] unused_outlier_count;
    logic packet_in_ready, packet_mask_valid, packet_mask_ready, packet_mask_last;
    logic [31:0] packet_mask_tag;
    logic [15:0] packet_mask_start;
    logic [6:0] packet_mask_count, compute_mask_count;
    logic [1279:0] packet_mask_bits;
    logic compute_mask_valid, compute_mask_ready;
    logic predict_req_valid, predict_req_ready, predict_rsp_valid, predict_rsp_ready;
    logic compute_req_valid, compute_req_ready, compute_rsp_valid, compute_rsp_ready;
    logic [63:0] predict_req_address, compute_req_address;
    logic [4:0] predict_req_length, compute_req_length;
    logic predict_wr_req_valid, predict_wr_data_valid, predict_wr_data_last, predict_wr_rsp_ready;
    logic compute_wr_req_valid, compute_wr_data_valid, compute_wr_data_last, compute_wr_rsp_ready;
    logic [63:0] predict_wr_address, predict_wr_data, compute_wr_address, compute_wr_data;
    logic [4:0] predict_wr_length, compute_wr_length;
    logic [7:0] predict_wr_strobe, compute_wr_strobe;

    function automatic logic overlaps_scratch(input logic [63:0] base_address, input logic [64:0] end_address);
        return {1'b0, cfg_intermediate_base} <= end_address && {1'b0, base_address} <= scratch_end;
    endfunction

    function automatic logic overlaps_activation(input logic [63:0] base_address, input logic [64:0] end_address);
        return {1'b0, cfg_activation_base} <= end_address && {1'b0, base_address} <= activation_end;
    endfunction

    always_comb begin
        // Each sign plane has one bit per weight, packed by channel group.
        weight_bytes = 65'(cfg_input_features) * 65'(cfg_intermediate_features);
        sign_bytes = weight_bytes >> 3;
        activation_end = {1'b0, cfg_activation_base} +
            (65'(cfg_tokens) - 65'd1) * 65'(cfg_activation_stride) + 65'(cfg_input_features) - 65'd1;
        gate_end = {1'b0, cfg_gate_base} + weight_bytes - 65'd1;
        up_end = {1'b0, cfg_up_base} + weight_bytes - 65'd1;
        down_end = {1'b0, cfg_down_base} + 65'(cfg_output_features) * 65'(cfg_intermediate_features) - 65'd1;
        gate_sign_end = {1'b0, cfg_gate_sign_base} + sign_bytes - 65'd1;
        up_sign_end = {1'b0, cfg_up_sign_base} + sign_bytes - 65'd1;
        scratch_end = {1'b0, cfg_intermediate_base} + 65'(cfg_tokens) * 65'(cfg_intermediate_features) - 65'd1;
        // Reject invalid compute descriptors before consuming residuals or
        // issuing sign traffic. The compute block also validates its input.
        config_bad = cfg_tokens == 0 || cfg_tokens > 16 || cfg_input_features < 32 ||
            cfg_input_features > 2048 || cfg_input_features[4:0] != 0 ||
            cfg_intermediate_features < 32 || cfg_intermediate_features > 8160 ||
            cfg_intermediate_features[4:0] != 0 || cfg_output_features == 0 || cfg_output_features > 65536 ||
            cfg_activation_base[2:0] != 0 || cfg_gate_base[2:0] != 0 || cfg_up_base[2:0] != 0 ||
            cfg_down_base[2:0] != 0 || cfg_intermediate_base[2:0] != 0 || cfg_activation_stride[2:0] != 0 ||
            cfg_activation_stride < 32'(cfg_input_features) ||
            cfg_gate_sign_base[2:0] != 0 || cfg_up_sign_base[2:0] != 0 ||
            activation_end[64] || gate_end[64] || up_end[64] || down_end[64] ||
            gate_sign_end[64] || up_sign_end[64] || scratch_end[64] ||
            overlaps_scratch(cfg_activation_base, activation_end) || overlaps_scratch(cfg_gate_base, gate_end) ||
            overlaps_scratch(cfg_up_base, up_end) || overlaps_scratch(cfg_down_base, down_end) ||
            overlaps_scratch(cfg_gate_sign_base, gate_sign_end) || overlaps_scratch(cfg_up_sign_base, up_sign_end) ||
            overlaps_activation(cfg_gate_base, gate_end) || overlaps_activation(cfg_up_base, up_end) ||
            overlaps_activation(cfg_down_base, down_end) ||
            overlaps_activation(cfg_gate_sign_base, gate_sign_end) || overlaps_activation(cfg_up_sign_base, up_sign_end);
    end

    assign cfg_ready = state == Idle && predict_ready && packet_ready && compute_ready;
    assign take_cfg = cfg_valid && cfg_ready && !config_bad;
    assign predict_failed = predict_done && predict_error;
    assign packet_failed = packet_done && packet_error;
    assign compute_failed = compute_done && compute_error;

    // Launch only after normalization and the first complete packet. On a
    // compute failure, the predictor can drain without more residual input.
    assign launch_compute = state == Active && !compute_started && compute_ready &&
        packet_mask_valid && !predict_failed && !packet_failed &&
        !predict_wr_req_valid && !predict_wr_data_valid && !predict_wr_rsp_ready;
    assign cancel_packet = compute_failed || (!compute_started && predict_failed);
    assign drop_predictions = packet_done || compute_failed;
    assign prediction_ready = drop_predictions || packet_in_ready;
    assign packet_mask_ready = compute_started && compute_mask_ready;

    // Keep any already offered valid packet stable. Once it transfers,
    // a zero-count packet tells the compute frame to reject its next tile.
    assign abort_mask = compute_started && !compute_done && !packet_mask_valid &&
        (predict_failed || packet_failed);
    assign compute_mask_valid = compute_started && (packet_mask_valid || abort_mask);
    assign compute_mask_count = abort_mask ? 7'd0 : packet_mask_count;
    assign done_valid = state == Reject ||
        (state == Active && predict_done && packet_done && (!compute_started || compute_done) &&
         read_state == PickRead);
    assign done_error = state == Reject || predict_failed || packet_failed || compute_failed;
    assign done_tag = tag;
    assign retire = done_valid && done_ready && state == Active;

    assign req_valid = read_state == OfferRead && (owner_compute ? compute_req_valid : predict_req_valid);
    assign req_address = owner_compute ? compute_req_address : predict_req_address;
    assign req_length = owner_compute ? compute_req_length : predict_req_length;
    assign compute_req_ready = read_state == OfferRead && owner_compute && req_ready;
    assign predict_req_ready = read_state == OfferRead && !owner_compute && req_ready;
    assign compute_rsp_valid = read_state == WaitRead && owner_compute && rsp_valid;
    assign predict_rsp_valid = read_state == WaitRead && !owner_compute && rsp_valid;
    assign rsp_ready = read_state == WaitRead && (owner_compute ? compute_rsp_ready : predict_rsp_ready);

    // The first prediction mask is possible only after the activation writer
    // accepts its final response, so switching ownership never splits a burst.
    assign wr_req_valid = compute_started ? compute_wr_req_valid : predict_wr_req_valid;
    assign wr_address = compute_started ? compute_wr_address : predict_wr_address;
    assign wr_length = compute_started ? compute_wr_length : predict_wr_length;
    assign wr_data_valid = compute_started ? compute_wr_data_valid : predict_wr_data_valid;
    assign wr_data = compute_started ? compute_wr_data : predict_wr_data;
    assign wr_strobe = compute_started ? compute_wr_strobe : predict_wr_strobe;
    assign wr_data_last = compute_started ? compute_wr_data_last : predict_wr_data_last;
    assign wr_rsp_ready = compute_started ? compute_wr_rsp_ready : predict_wr_rsp_ready;

    logic [533:0] strip_request;
    logic [111:0] strip_response;
    tri_oracle_batched_normalize405 #(.CORE_STRIP_PREDICTOR(CORE_STRIP_PREDICTOR)) predictor (
        .strip_request, .strip_response,
        .clk(clk), .rst_n(rst_n), .cfg_valid(take_cfg), .cfg_ready(predict_ready),
        .cfg_tag(cfg_tag), .cfg_tokens(cfg_tokens), .cfg_strips(cfg_input_features[12:3]),
        .cfg_groups(cfg_intermediate_features[12:5]), .cfg_epsilon_q16(cfg_epsilon_q16),
        .cfg_activation_base(cfg_activation_base), .cfg_activation_stride(cfg_activation_stride),
        .cfg_activation_shifts(cfg_activation_shifts),
        .cfg_gate_sign_base(cfg_gate_sign_base), .cfg_up_sign_base(cfg_up_sign_base), .residual_token(residual_token),
        .stats_valid(stats_valid && state == Active), .stats_ready(stats_ready), .stats_last(stats_last), .stats_data(stats_data),
        .replay_valid(replay_valid && state == Active), .replay_ready(replay_ready),
        .replay_last(replay_last), .replay_data(replay_data), .replay_gamma(replay_gamma),
        .out_valid(prediction_valid), .out_ready(prediction_ready), .out_last(prediction_last),
        .out_tag(prediction_tag), .out_group(prediction_group), .out_token(prediction_token),
        .gate_nearzero_mask(unused_gate_mask), .up_nearzero_mask(unused_up_mask),
        .skip_mask(prediction_skip), .outlier_count(unused_outlier_count),
        .done_valid(predict_done), .done_ready(retire), .done_error(predict_error), .done_tag(unused_predict_done_tag),
        .req_valid(predict_req_valid), .req_ready(predict_req_ready),
        .req_address(predict_req_address), .req_length(predict_req_length), .rsp_valid(predict_rsp_valid),
        .rsp_ready(predict_rsp_ready), .rsp_last(rsp_last), .rsp_error(rsp_error), .rsp_data(rsp_data),
        .wr_req_valid(predict_wr_req_valid), .wr_req_ready(wr_req_ready && !compute_started),
        .wr_address(predict_wr_address), .wr_length(predict_wr_length),
        .wr_data_valid(predict_wr_data_valid), .wr_data_ready(wr_data_ready && !compute_started),
        .wr_data(predict_wr_data), .wr_strobe(predict_wr_strobe), .wr_data_last(predict_wr_data_last),
        .wr_rsp_valid(wr_rsp_valid && !compute_started), .wr_rsp_error(wr_rsp_error), .wr_rsp_ready(predict_wr_rsp_ready)
    );

    tri_oracle_batched_mask_packet399 packetizer (
        .clk(clk), .rst_n(rst_n), .cfg_valid(take_cfg), .cfg_ready(packet_ready),
        .cfg_tag(cfg_tag), .cfg_tokens(cfg_tokens), .cfg_channels(cfg_intermediate_features),
        .in_valid(prediction_valid && !drop_predictions), .in_ready(packet_in_ready),
        .in_tag(prediction_tag), .in_group(prediction_group), .in_token(prediction_token),
        .in_last(prediction_last), .in_skip_mask(prediction_skip),
        .cancel_valid(cancel_packet), .cancel_tag(tag), .mask_valid(packet_mask_valid),
        .mask_ready(packet_mask_ready), .mask_tag(packet_mask_tag), .mask_start(packet_mask_start),
        .mask_count(packet_mask_count), .mask_last(packet_mask_last), .mask_bits(packet_mask_bits),
        .done_valid(packet_done), .done_ready(retire), .done_error(packet_error), .done_tag(unused_packet_done_tag)
    );

    tri_oracle_batched_frame437 #(
      .AGGREGATOR_SIGN_BANK(AGGREGATOR_SIGN_BANK), .CORE_STRIP_PREDICTOR(CORE_STRIP_PREDICTOR)
    ) compute (
      .strip_request,.strip_response,
      .merge_sign_data,.merge_sign_control,.merge_sign_counts,
        .clk(clk), .rst_n(rst_n), .cfg_valid(launch_compute), .cfg_ready(compute_ready),
        .attention, .attention_enable(state == Idle && read_state == PickRead && !cfg_valid),
        .cfg_tag(tag), .cfg_tokens(saved.tokens), .cfg_input_features(saved.input_features),
        .cfg_intermediate_features(saved.intermediate_features), .cfg_output_features(saved.output_features),
        .cfg_activation_base(saved.activation_base), .cfg_gate_base(saved.gate_base), .cfg_up_base(saved.up_base),
        .cfg_down_base(saved.down_base), .cfg_intermediate_base(saved.intermediate_base),
        .cfg_activation_stride(saved.activation_stride),
        .cfg_gate_shifts(saved.gate_shifts), .cfg_up_shifts(saved.up_shifts), .cfg_down_shifts(saved.down_shifts),
        .mask_valid(compute_mask_valid), .mask_ready(compute_mask_ready),
        .mask_tag(packet_mask_tag), .mask_start(packet_mask_start), .mask_count(compute_mask_count),
        .mask_last(packet_mask_last), .mask_bits(packet_mask_bits),
        .out_valid(out_valid), .out_ready(out_ready), .out_tag(out_tag), .out_token(out_token),
        .out_start(out_start), .out_count(out_count), .out_last(out_last), .out_data(out_data),
        .done_valid(compute_done), .done_ready(retire), .done_error(compute_error), .done_tag(unused_compute_done_tag),
        .req_valid(compute_req_valid), .req_ready(compute_req_ready),
        .req_address(compute_req_address), .req_length(compute_req_length),
        .rsp_valid(compute_rsp_valid), .rsp_ready(compute_rsp_ready),
        .rsp_last(rsp_last), .rsp_error(rsp_error), .rsp_data(rsp_data),
        .wr_req_valid(compute_wr_req_valid), .wr_req_ready(wr_req_ready && compute_started),
        .wr_address(compute_wr_address), .wr_length(compute_wr_length),
        .wr_data_valid(compute_wr_data_valid), .wr_data_ready(wr_data_ready && compute_started),
        .wr_data(compute_wr_data), .wr_strobe(compute_wr_strobe), .wr_data_last(compute_wr_data_last),
        .wr_rsp_valid(wr_rsp_valid && compute_started), .wr_rsp_error(wr_rsp_error), .wr_rsp_ready(compute_wr_rsp_ready)
    );

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= Idle;
            read_state <= PickRead;
            saved <= '0;
            tag <= '0;
            compute_started <= 0;
            owner_compute <= 0;
        end else begin
            case (state)
                Idle: if (cfg_valid && cfg_ready) begin
                    tag <= cfg_tag;
                    saved <= {cfg_tokens, cfg_input_features, cfg_intermediate_features, cfg_output_features,
                        cfg_activation_base, cfg_gate_base, cfg_up_base, cfg_down_base, cfg_intermediate_base,
                        cfg_activation_stride, cfg_gate_shifts, cfg_up_shifts, cfg_down_shifts};
                    compute_started <= 0;
                    if (config_bad) state <= Reject;
                    else state <= Active;
                end
                Active: begin
                    if (launch_compute) compute_started <= 1;
                    if (retire) state <= Idle;
                end
                Reject: if (done_ready) state <= Idle;
                default: state <= Idle;
            endcase
            case (read_state)
                PickRead: if (predict_req_valid || compute_req_valid) begin
                    owner_compute <= compute_req_valid;
                    read_state <= OfferRead;
                end
                OfferRead: if (req_valid && req_ready) read_state <= WaitRead;
                WaitRead: if (rsp_valid && rsp_ready && rsp_last) read_state <= PickRead;
                default: read_state <= PickRead;
            endcase
        end
    end
endmodule
