`timescale 1ns / 1ps
// Prepared channel prediction and paired gate/up execution on the same twenty cores.
// Separate top preserves the live physical revision while extending its method.
// Outputs are signed16 Q8 gated codes sign-extended into the32-bit packet lanes.
// Local batching/frame/error protocol; earlier packets commit only at final success.
// Terminal errors cancel remaining input; reset is coordinated with the memory peer.
module tri_oracle_predicted_gated_fabric (
    input logic clk,
    rst_n,
    cfg_valid,
    output logic cfg_ready,
    input logic [31:0] cfg_tag,
    input logic [63:0] cfg_activation_base,
    cfg_weight_base,
    cfg_up_weight_base,
    input logic [5:0] cfg_gate_shift,
    cfg_up_shift,
    input logic [9:0] cfg_features,
    input logic [16:0] cfg_dense_rows,
    input logic in_valid,
    in_last,
    in_group_last,
    input logic [10:0] in_group,
    input logic [127:0] norm_activations,
    input logic [255:0] gate_weight_signs,
    up_weight_signs,
    output logic in_ready,
    out_valid,
    input logic out_ready,
    output logic out_last,
    out_fallback,
    out_error,
    output logic [31:0] out_tag,
    output logic [7:0] out_count,
    output logic [2559:0] out_channels,
    output logic [5119:0] out_data,
    output logic req_valid,
    input logic req_ready,
    output logic [63:0] req_address,
    output logic [4:0] req_length,
    input logic rsp_valid,
    rsp_last,
    rsp_error,
    output logic rsp_ready,
    input logic [63:0] rsp_data
);

  localparam int Rows = 160;
  localparam int GroupRows = 32;
  localparam int GroupBits = GroupRows * 16;
  localparam int MaxStrips = 512;
  localparam logic [64:0] LastAddress = 65'h0ffffffffffffffff;
  typedef enum logic [3:0] {
    Idle,
    ConfigureReset,
    Collect,
    Drain,
    Launch,
    WaitResult,
    Result,
    AbortReset,
    Error
  } state_t;
  state_t state;
  logic child_rst_n, invalid_config, input_allow, input_fault, first_strip;
  logic input_closed, saved_group_last;
  logic [31:0] tag;
  logic [63:0] activation_base, weight_base, up_weight_base;
  logic [5:0] gate_shift, up_shift;
  logic [9:0] features, strip_count;
  logic [16:0] dense_rows;
  logic [11:0] expected_group, groups;
  logic [10:0] saved_group, incoming_count;
  logic [64:0] activation_bytes, activation_end, matrix_end, up_matrix_end;
  logic pred_in_ready, pred_valid, pred_ready, pred_last, pred_fallback;
  logic [  5:0] pred_count;
  logic [511:0] pred_channels;
  logic [255:0] unused_lane_enable;
  logic packet_fits, packet_fault;
  logic [7:0] batch_count;
  logic [2559:0] batch_channels;
  logic batch_final, batch_fallback;
  logic fabric_in_ready, fabric_valid, fabric_last, fabric_fallback, fabric_error;
  logic [31:0] fabric_tag;
  logic [7:0] fabric_count;
  logic [2559:0] fabric_channels;
  logic [5119:0] fabric_data;
  logic result_last, result_fallback;
  logic [7:0] result_count;
  logic [2559:0] result_channels;
  logic [5119:0] result_data;

  always_comb begin
    activation_bytes = 65'(cfg_features) << 3;
    activation_end = {1'b0, cfg_activation_base} + activation_bytes - 65'd1;
    matrix_end = {1'b0, cfg_weight_base} + 65'(cfg_dense_rows) * activation_bytes - 65'd1;
    up_matrix_end = {1'b0, cfg_up_weight_base} + 65'(cfg_dense_rows) * activation_bytes - 65'd1;
    invalid_config = cfg_features == 0 || cfg_features > 10'(MaxStrips) ||
        cfg_dense_rows < 17'(GroupRows) || cfg_dense_rows > 17'd65536 ||
        cfg_dense_rows[4:0] != 0 || cfg_activation_base[2:0] != 0 ||
        cfg_weight_base[2:0] != 0 || cfg_up_weight_base[2:0] != 0 ||
        activation_end > LastAddress || matrix_end > LastAddress || up_matrix_end > LastAddress;
  end

  always_comb begin
    cfg_ready = state == Idle;
    input_allow = (state == Collect && !input_closed) || state == Drain;
    incoming_count = first_strip ? 11'd1 : {1'b0, strip_count} + 11'd1;
    input_fault = in_last != (incoming_count == {1'b0, features}) ||
        (first_strip ?
          ({1'b0, in_group} != expected_group ||
           in_group_last != (expected_group + 12'd1 == groups)) :
          (in_group != saved_group || in_group_last != saved_group_last));
    out_valid = state == Result || state == Error;
    out_last = state == Error || result_last;
    out_error = state == Error;
    out_fallback = state == Result && result_fallback;
    out_tag = tag;
    out_count = state == Error ? 8'd0 : result_count;
    out_channels = state == Error ? 2560'd0 : result_channels;
    out_data = state == Error ? 5120'd0 : result_data;
  end

  always_comb begin
    packet_fits = 9'(batch_count) + 9'(pred_count) <= 9'(Rows);
    packet_fault = pred_count > 6'(GroupRows) ||
        (pred_last ? pred_count >= 6'(GroupRows) : pred_count != 6'(GroupRows));
    for (int row = 0; row < GroupRows; row++)
    if (row < int'(pred_count) && {1'b0, pred_channels[row*16+:16]} >= dense_rows) packet_fault = 1;
    pred_ready = state == Drain || (state == Collect && packet_fits);
  end

  always_comb in_ready = input_allow && pred_in_ready;

  tri_oracle_predicted_dispatch prediction (
      .clk(clk),
      .rst_n(child_rst_n),
      .in_valid(input_allow && in_valid),
      .in_last(in_last),
      .in_group_last(in_group_last),
      .in_frame_error(input_fault),
      .in_group(in_group),
      .norm_activations(norm_activations),
      .gate_weight_signs(gate_weight_signs),
      .up_weight_signs(up_weight_signs),
      .in_ready(pred_in_ready),
      .out_ready(pred_ready),
      .out_valid(pred_valid),
      .out_last(pred_last),
      .out_error(pred_fallback),
      .out_count(pred_count),
      .out_channels(pred_channels),
      .out_lane_enable(unused_lane_enable)
  );

  tri_oracle_gated_fabric fabric (
      .clk(clk),
      .rst_n(child_rst_n),
      .in_valid(state == Launch),
      .in_last(batch_final),
      .in_fallback(batch_fallback),
      .out_ready(state == WaitResult),
      .in_tag(tag),
      .in_channels(batch_channels),
      .in_count(batch_count),
      .in_activation_base(activation_base),
      .in_weight_base(weight_base),
      .in_up_weight_base(up_weight_base),
      .in_gate_shift(gate_shift),
      .in_up_shift(up_shift),
      .in_features(features),
      .in_ready(fabric_in_ready),
      .out_valid(fabric_valid),
      .out_last(fabric_last),
      .out_fallback(fabric_fallback),
      .out_error(fabric_error),
      .out_tag(fabric_tag),
      .out_count(fabric_count),
      .out_channels(fabric_channels),
      .out_data(fabric_data),
      .req_valid(req_valid),
      .req_ready(req_ready),
      .req_address(req_address),
      .req_length(req_length),
      .rsp_valid(rsp_valid),
      .rsp_last(rsp_last),
      .rsp_error(rsp_error),
      .rsp_ready(rsp_ready),
      .rsp_data(rsp_data)
  );

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state <= Idle;
      child_rst_n <= 0;
      tag <= 0;
      activation_base <= 0;
      weight_base <= 0;
      up_weight_base <= 0;
      gate_shift <= 0;
      up_shift <= 0;
      features <= 0;
      dense_rows <= 0;
      groups <= 0;
      expected_group <= 0;
      saved_group <= 0;
      saved_group_last <= 0;
      first_strip <= 1;
      strip_count <= 0;
      input_closed <= 0;
      batch_count <= 0;
      batch_channels <= 0;
      batch_final <= 0;
      batch_fallback <= 0;
      result_count <= 0;
      result_channels <= 0;
      result_data <= 0;
      result_last <= 0;
      result_fallback <= 0;
    end else begin
      // A dedicated flip-flop prevents decoded-state hazards from resetting children.
      child_rst_n <= 1;
      case (state)
        Idle:
        if (cfg_valid) begin
          tag <= cfg_tag;
          activation_base <= cfg_activation_base;
          weight_base <= cfg_weight_base;
          up_weight_base <= cfg_up_weight_base;
          gate_shift <= cfg_gate_shift;
          up_shift <= cfg_up_shift;
          features <= cfg_features;
          dense_rows <= cfg_dense_rows;
          groups <= cfg_dense_rows[16:5];
          expected_group <= 0;
          saved_group <= 0;
          saved_group_last <= 0;
          first_strip <= 1;
          strip_count <= 0;
          input_closed <= 0;
          batch_count <= 0;
          batch_channels <= 0;
          batch_final <= 0;
          batch_fallback <= 0;
          result_count <= 0;
          result_channels <= 0;
          result_data <= 0;
          result_last <= 0;
          result_fallback <= 0;
          if (invalid_config) state <= Error;
          else begin
            child_rst_n <= 0;
            state <= ConfigureReset;
          end
        end
        ConfigureReset: state <= Collect;
        Collect: begin
          if (in_valid && in_ready) begin
            if (first_strip) begin
              saved_group <= in_group;
              saved_group_last <= in_group_last;
            end
            first_strip <= in_last;
            strip_count <= in_last ? 10'd0 :
                incoming_count > 11'(MaxStrips) ? 10'(MaxStrips) : incoming_count[9:0];
            if (in_last) begin
              expected_group <= expected_group + 12'd1;
              if (first_strip ? in_group_last : saved_group_last) input_closed <= 1;
            end
          end
          // A malformed accepted strip takes priority over any buffered packet.
          // The fabric is idle in Collect, so resetting after input LAST is safe.
          if (in_valid && in_ready && input_fault) begin
            if (in_last) begin
              child_rst_n <= 0;
              state <= AbortReset;
            end
            else state <= Drain;
          end else if (pred_valid) begin
            if (packet_fault) begin
              child_rst_n <= 0;
              state <= AbortReset;
            end
            else if (!packet_fits) state <= Launch;
            else if (pred_ready) begin
              // Nonterminal compactor packets always contain exactly32 rows.
              // Only a final partial packet can leave a partly occupied group.
              if (pred_count != 0)
                batch_channels[int'(batch_count[7:5])*GroupBits+:GroupBits] <= pred_channels;
              batch_count <= batch_count + 8'(pred_count);
              batch_final <= pred_last;
              batch_fallback <= batch_fallback || pred_fallback;
              if (pred_last) state <= Launch;
            end
          end
        end
        Drain: if (in_valid && in_ready && in_last) begin
          child_rst_n <= 0;
          state <= AbortReset;
        end
        Launch: if (fabric_in_ready) state <= WaitResult;
        WaitResult:
        if (fabric_valid) begin
          if (fabric_error || fabric_tag != tag || fabric_count != batch_count ||
              fabric_channels != batch_channels || fabric_last != batch_final ||
              fabric_fallback != batch_fallback)
          begin
            child_rst_n <= 0;
            state <= AbortReset;
          end else begin
            result_count <= fabric_count;
            result_channels <= fabric_channels;
            result_data <= fabric_data;
            result_last <= fabric_last;
            result_fallback <= fabric_fallback;
            state <= Result;
          end
        end
        Result:
        if (out_ready) begin
          if (result_last) state <= Idle;
          else begin
            batch_count <= 0;
            batch_channels <= 0;
            batch_final <= 0;
            batch_fallback <= 0;
            state <= Collect;
          end
        end
        AbortReset: state <= Error;
        Error: if (out_ready) state <= Idle;
        default: begin
          child_rst_n <= 0;
          state <= AbortReset;
        end
      endcase
    end
  end
endmodule
