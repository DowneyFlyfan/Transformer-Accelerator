`timescale 1ns / 1ps
// Gate/up sequencing for one existing twenty-core projection fabric.
// The projection peer returns completed sums across all four cores per cluster;
// nonlinear activation is applied only after both full projections finish.
// No compute core is instantiated here. A packet owns the projection peer until
// completion. System reset must also reset that peer and its memory transaction peer.
module tri_oracle_fabric_gated_executor (
    input logic clk,
    input logic rst_n,
    input logic in_valid,
    output logic in_ready,
    input logic in_last,
    input logic in_fallback,
    input logic [31:0] in_tag,
    input logic [2559:0] in_channels,
    input logic [7:0] in_count,
    input logic [63:0] in_activation_base,
    input logic [63:0] in_weight_base,
    input logic [63:0] in_up_weight_base,
    input logic [9:0] in_features,
    input logic [5:0] in_gate_shift,
    input logic [5:0] in_up_shift,
    output logic out_valid,
    input logic out_ready,
    output logic out_last,
    output logic out_fallback,
    output logic out_error,
    output logic [31:0] out_tag,
    output logic [7:0] out_count,
    output logic [2559:0] out_channels,
    output logic [5119:0] out_data,
    output logic projection_in_valid,
    input logic projection_in_ready,
    output logic projection_in_last,
    output logic projection_in_fallback,
    output logic [31:0] projection_in_tag,
    output logic [2559:0] projection_in_channels,
    output logic [7:0] projection_in_count,
    output logic [63:0] projection_in_activation_base,
    output logic [63:0] projection_in_weight_base,
    output logic [9:0] projection_in_features,
    input logic projection_out_valid,
    output logic projection_out_ready,
    input logic projection_out_last,
    input logic projection_out_fallback,
    input logic projection_out_error,
    input logic [31:0] projection_out_tag,
    input logic [2559:0] projection_out_channels,
    input logic [7:0] projection_out_count,
    input logic [5119:0] projection_out_data
);
  localparam int Rows = 160;
  localparam int CountWidth = $clog2(Rows+1);
  localparam int WordWidth = 32;
  localparam int ChannelWidth = 16;
  localparam int MaxStrips = 512;
  localparam logic [64:0] LastAddress = 65'h0ffffffffffffffff;
  typedef enum logic [3:0] {
    Idle, GateLaunch, GateWait, UpLaunch, UpWait, Activate, Drain, Result
  } state_t;
  state_t state;
  logic last, fallback, result_error, invalid_config, projection_fault;
  logic [31:0] tag;
  logic [Rows*ChannelWidth-1:0] channels;
  logic [CountWidth-1:0] count, issue_index, completed, activation_index;
  logic [63:0] activation_base, gate_base, up_base;
  logic [9:0] features;
  logic [5:0] gate_shift, up_shift;
  logic [Rows*WordWidth-1:0] gate_values, up_values, result_data;
  logic [64:0] input_bytes, activation_end, gate_end, up_end;
  logic activation_ready, activation_valid;
  logic signed [15:0] activation_data;
  logic [15:0] activation_tag;

  function automatic logic signed [15:0] requantize(
      input logic signed [31:0] value, input logic [5:0] shift);
    logic signed [33:0] extended, rounded;
    extended = {{2{value[31]}}, value};
    if (shift > 6'd32) rounded = 0;
    else if (shift == 0) rounded = extended;
    else if (extended < 0)
      rounded = -((-extended+(34'sd1 << (shift-6'd1))) >>> shift);
    else rounded = (extended+(34'sd1 << (shift-6'd1))) >>> shift;
    if (rounded > 34'sd32767) return 16'sh7fff;
    if (rounded < -34'sd32768) return 16'sh8000;
    return rounded[15:0];
  endfunction

  always_comb begin
    input_bytes = 65'(in_features) << 3;
    activation_end = {1'b0, in_activation_base}+input_bytes-1;
    invalid_config = in_count > CountWidth'(Rows) || in_features == 0 ||
        in_features > 10'(MaxStrips) || in_activation_base[2:0] != 0 ||
        in_weight_base[2:0] != 0 || in_up_weight_base[2:0] != 0 ||
        activation_end > LastAddress;
    gate_end = 0;
    up_end = 0;
    for (int row = 0; row < Rows; row++) begin
      gate_end = {1'b0, in_weight_base}+
          (65'(in_channels[row*ChannelWidth+:ChannelWidth])+1)*input_bytes-1;
      up_end = {1'b0, in_up_weight_base}+
          (65'(in_channels[row*ChannelWidth+:ChannelWidth])+1)*input_bytes-1;
      if (row < int'(in_count) && (gate_end > LastAddress || up_end > LastAddress))
        invalid_config = 1;
    end
  end

  always_comb begin
    in_ready = state == Idle;
    out_valid = state == Result;
    out_last = result_error || last;
    out_fallback = !result_error && fallback;
    out_error = result_error;
    out_tag = tag;
    out_count = result_error ? '0 : count;
    out_channels = result_error ? '0 : channels;
    out_data = result_error ? '0 : result_data;
    projection_in_valid = state == GateLaunch || state == UpLaunch;
    projection_in_last = last;
    projection_in_fallback = fallback;
    projection_in_tag = tag;
    projection_in_channels = channels;
    projection_in_count = count;
    projection_in_activation_base = activation_base;
    projection_in_weight_base = state == GateLaunch ? gate_base : up_base;
    projection_in_features = features;
    projection_out_ready = state == GateWait || state == UpWait;
    projection_fault = projection_out_error || projection_out_tag != tag ||
        projection_out_count != count || projection_out_channels != channels ||
        projection_out_last != last || projection_out_fallback != fallback;
    activation_index = issue_index < CountWidth'(Rows) ? issue_index : '0;
  end

  tri_oracle_silu_gate activation_unit (
      .clk(clk),
      .rst_n(rst_n),
      .in_valid(state == Activate),
      .in_ready(activation_ready),
      .in_gate(requantize($signed(gate_values[activation_index*WordWidth+:WordWidth]),
                          gate_shift)),
      .in_up(requantize($signed(up_values[activation_index*WordWidth+:WordWidth]),
                        up_shift)),
      .in_tag(16'(issue_index)),
      .out_valid(activation_valid),
      .out_ready(state == Activate || state == Drain),
      .out_data(activation_data),
      .out_tag(activation_tag)
  );

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state <= Idle;
      last <= 0;
      fallback <= 0;
      result_error <= 0;
      tag <= 0;
      channels <= 0;
      count <= 0;
      issue_index <= 0;
      completed <= 0;
      activation_base <= 0;
      gate_base <= 0;
      up_base <= 0;
      features <= 0;
      gate_shift <= 0;
      up_shift <= 0;
      gate_values <= 0;
      up_values <= 0;
      result_data <= 0;
    end else begin
      case (state)
        Idle: if (in_valid) begin
          tag <= in_tag;
          channels <= in_channels;
          count <= in_count;
          last <= in_last;
          fallback <= in_fallback;
          activation_base <= in_activation_base;
          gate_base <= in_weight_base;
          up_base <= in_up_weight_base;
          features <= in_features;
          gate_shift <= in_gate_shift;
          up_shift <= in_up_shift;
          issue_index <= 0;
          completed <= 0;
          result_data <= 0;
          result_error <= invalid_config;
          state <= invalid_config || in_count == 0 ? Result : GateLaunch;
        end
        GateLaunch: if (projection_in_ready) state <= GateWait;
        GateWait: if (projection_out_valid) begin
          if (projection_fault) begin
            result_error <= 1;
            state <= Result;
          end else begin
            gate_values <= projection_out_data;
            state <= UpLaunch;
          end
        end
        UpLaunch: if (projection_in_ready) state <= UpWait;
        UpWait: if (projection_out_valid) begin
          if (projection_fault) begin
            result_error <= 1;
            state <= Result;
          end else begin
            up_values <= projection_out_data;
            state <= Activate;
          end
        end
        Activate: if (activation_ready) begin
          issue_index <= issue_index+1'b1;
          if (issue_index+1'b1 == count) state <= Drain;
        end
        Result: if (out_ready) state <= Idle;
        default: begin end
      endcase
      if ((state == Activate || state == Drain) && activation_valid) begin
        result_data[activation_tag[CountWidth-1:0]*WordWidth+:WordWidth] <=
            {{(WordWidth-16){activation_data[15]}}, activation_data};
        completed <= completed+1'b1;
        if (completed+1'b1 == count) state <= Result;
      end
    end
  end
endmodule
