`timescale 1ns/1ps

// Auxiliary headers A67A/B carry eight statistics words, and A67C/D
// carry eight replay-data words followed by eight coefficient words.
// B and D mark the last strip. A678/A679 retain their established projection
// formats. Words arrive least significant first within each field.
module tri_oracle_host_context_rx (
  input logic clk, rst_n,
  input logic rx_valid,
  output logic rx_ready,
  input logic rx_is_payload, rx_payload_last,
  input logic [15:0] rx_data,
  output logic forward_valid,
  input logic forward_ready,
  output logic context_control_valid,context_control_finish,
  input logic context_control_ready,
  output logic control_valid,
  input logic control_ready,
  output logic [1:0] control_action,
  output logic operand_valid,
  input logic operand_ready,
  output logic [279:0] residual_q32,
  output logic [4:0] projection_shift,
  output logic gamma_valid,
  input logic gamma_ready,
  output logic [127:0] gamma_data,
  output logic stats_valid, stats_last,
  input logic stats_ready,
  output logic [127:0] stats_data,
  output logic replay_valid, replay_last,
  input logic replay_ready,
  output logic [127:0] replay_data, replay_gamma
);
  typedef enum logic [1:0] {RecordStart, ForwardBody, ReceiveBody, Pending} state_t;
  typedef enum logic [1:0] {Operand, Gamma, Statistics, Replay} kind_t;
  state_t state;
  kind_t kind;
  logic [6:0] forward_left;
  logic [4:0] word_index, final_index;
  logic [287:0] buffer;
  logic context_header,sideband_header, auxiliary, local_header, forwarding, transfer, publish, consumed, last;

  assign auxiliary = !rx_is_payload && rx_payload_last;
  assign local_header = auxiliary && rx_data[15:3] == 13'h14CF && rx_data[2:1] != 2'b11;
  assign context_header = auxiliary && (rx_data == 16'hA685 || rx_data == 16'hA686);
  assign context_control_valid = rst_n && state == RecordStart && context_header && rx_valid;
  assign context_control_finish = rx_data == 16'hA686;
  assign sideband_header = auxiliary && (rx_data == 16'hA67E || rx_data[15:1] == 15'h5341);
  assign control_valid = rst_n && state == RecordStart && sideband_header && rx_valid;
  assign control_action = rx_data == 16'hA67E ? 2'd0 : rx_data[0] ? 2'd2 : 2'd1;
  assign forwarding = state == ForwardBody ||
                      (state == RecordStart && !local_header && !sideband_header && !context_header);
  always_comb begin
    if (!rst_n || state == Pending) rx_ready = 1'b0;
    else if (state == RecordStart && context_header) rx_ready = context_control_ready;
    else if (state == RecordStart && sideband_header) rx_ready = control_ready;
    else if (forwarding) rx_ready = forward_ready;
    else rx_ready = 1'b1;
  end
  assign forward_valid = rst_n && forwarding && rx_valid;
  assign transfer = rx_valid && rx_ready;
  assign publish = rst_n && state == Pending;
  assign operand_valid = publish && kind == Operand;
  assign gamma_valid = publish && kind == Gamma;
  assign stats_valid = publish && kind == Statistics;
  assign replay_valid = publish && kind == Replay;
  assign consumed = (operand_valid && operand_ready) || (gamma_valid && gamma_ready) ||
                    (stats_valid && stats_ready) || (replay_valid && replay_ready);
  assign {projection_shift, residual_q32} = buffer[284:0];
  assign gamma_data = buffer[127:0];
  assign {stats_data, replay_data} = {2{buffer[127:0]}};
  assign replay_gamma = buffer[255:128];
  assign {stats_last, replay_last} = {2{last}};
  assign final_index = kind == Operand ? 5'd17 : kind == Replay ? 5'd15 : 5'd7;

  for (genvar word = 0; word < 18; word++) begin : words
    always_ff @(posedge clk)
      if (state == ReceiveBody && transfer && word_index == 5'(word))
        buffer[word * 16 +: 16] <= rx_data;
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state <= RecordStart;
      kind <= Operand;
      forward_left <= 0;
      word_index <= 0;
      last <= 0;
    end else case (state)
      RecordStart: if (transfer && !sideband_header && !context_header) begin
        if (local_header) begin
          word_index <= 0;
          last <= rx_data[0];
          if (rx_data[2]) kind <= Replay;
          else if (rx_data[1]) kind <= Statistics;
          else kind <= rx_data[0] ? Gamma : Operand;
          state <= ReceiveBody;
        end else begin
          if (auxiliary && rx_data[15:1] == 15'h5338) forward_left <= 7'd64;
          else if (auxiliary && rx_data == 16'hA674) forward_left <= 7'd8;
          else forward_left <= rx_is_payload ? 7'd3 : 7'd2;
          state <= ForwardBody;
        end
      end
      ForwardBody: if (transfer) begin
        forward_left <= forward_left - 1'b1;
        if (forward_left == 1) state <= RecordStart;
      end
      ReceiveBody: if (transfer) begin
        word_index <= word_index + 1'b1;
        if (word_index == final_index) state <= Pending;
      end
      Pending: if (consumed) state <= RecordStart;
      default: state <= RecordStart;
    endcase
  end
endmodule
