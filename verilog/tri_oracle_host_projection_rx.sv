`timescale 1ns/1ps

// At a record boundary, the auxiliary flags select A678 for an 18-word
// residual/shift record or A679 for an eight-word coefficient record. Send
// words least significant first and in the normalizer's token/strip order.
// The final operand word contains three padding bits above the five-bit shift.
// One completed record can wait for the consumer. Other host records retain
// their framing and use the existing receiver behind this filter.
module tri_oracle_host_projection_rx (
  input logic clk, rst_n,
  input logic rx_valid,
  output logic rx_ready,
  input logic rx_is_payload, rx_payload_last,
  input logic [15:0] rx_data,
  output logic forward_valid,
  input logic forward_ready,
  output logic operand_valid,
  input logic operand_ready,
  output logic [279:0] residual_q32,
  output logic [4:0] projection_shift,
  output logic gamma_valid,
  input logic gamma_ready,
  output logic [127:0] gamma_data
);
  typedef enum logic [1:0] {RecordStart, ForwardBody, ReceiveBody, Pending} state_t;
  state_t state;
  logic [6:0] forward_left;
  logic [4:0] word_index;
  logic [287:0] buffer;
  logic auxiliary, new_header, forwarding, transfer, coefficient;

  assign auxiliary = !rx_is_payload && rx_payload_last;
  assign new_header = auxiliary && rx_data[15:1] == 15'h533C;
  assign forwarding = state == ForwardBody || (state == RecordStart && !new_header);
  assign rx_ready = rst_n && (forwarding ? forward_ready : state != Pending);
  assign forward_valid = rst_n && forwarding && rx_valid;
  assign transfer = rx_valid && rx_ready;
  assign operand_valid = rst_n && state == Pending && !coefficient;
  assign gamma_valid = rst_n && state == Pending && coefficient;
  assign {projection_shift, residual_q32} = buffer[284:0];
  assign gamma_data = buffer[127:0];

  for (genvar word_number = 0; word_number < 18; word_number++) begin : words
    always_ff @(posedge clk)
      if (state == ReceiveBody && transfer && word_index == 5'(word_number))
        buffer[word_number * 16 +: 16] <= rx_data;
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state <= RecordStart;
      forward_left <= 0;
      word_index <= 0;
      coefficient <= 0;
    end else case (state)
      RecordStart: if (transfer) begin
        if (new_header) begin
          word_index <= 0;
          coefficient <= rx_data[0];
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
        if (word_index == (coefficient ? 5'd7 : 5'd17)) state <= Pending;
      end
      Pending: if (coefficient ? gamma_ready : operand_ready) state <= RecordStart;
      default: state <= RecordStart;
    endcase
  end
endmodule
