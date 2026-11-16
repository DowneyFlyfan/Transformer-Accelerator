`timescale 1ns/1ps

// A674 with the auxiliary header flags starts an eight-word address record.
// The first four words hold the context base and the next four hold the value
// cache base, both least significant word first. Send between completed chip
// commands. Both addresses commit together on acceptance of the last word.
module tri_oracle_host_control_rx (
  input logic clk, rst_n,
  input logic rx_valid,
  output logic rx_ready,
  input logic rx_is_payload, rx_payload_last,
  input logic [15:0] rx_data,
  output logic link_valid,
  input logic link_ready, config_enable,
  output logic angle_valid,
  input logic angle_ready,
  output logic angle_last,
  output logic [1023:0] angle_data,
  output logic [63:0] context_base, value_read_base
);
  typedef enum logic [2:0] {RecordStart, HostBody, RotaryBody, RotaryPending, AddressBody} state_t;
  state_t state;
  logic [1:0] host_words_left;
  logic [5:0] rotary_index;
  logic [2:0] address_index;
  logic [127:0] address_words;
  logic auxiliary_header, rotary_header, address_header, ordinary, transfer;

  assign auxiliary_header = !rx_is_payload && rx_payload_last;
  assign rotary_header = auxiliary_header && rx_data[15:1] == 15'h5338;
  assign address_header = auxiliary_header && rx_data == 16'hA674;
  assign ordinary = state == HostBody || (state == RecordStart && !rotary_header && !address_header);
  assign link_valid = rst_n && ordinary && rx_valid;
  assign rx_ready = rst_n && (ordinary ? link_ready :
                     state == RecordStart && address_header ? config_enable && link_ready : state != RotaryPending);
  assign angle_valid = rst_n && state == RotaryPending;
  assign transfer = rx_valid && rx_ready;

  for (genvar word = 0; word < 64; word++) begin : rotary_words
    always_ff @(posedge clk)
      if (state == RotaryBody && transfer && rotary_index == 6'(word))
        angle_data[word * 16 +: 16] <= rx_data;
  end

  always_ff @(posedge clk)
    if (state == AddressBody && transfer) address_words[{address_index, 4'b0} +: 16] <= rx_data;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state <= RecordStart;
      host_words_left <= 0;
      rotary_index <= 0;
      address_index <= 0;
      angle_last <= 0;
      {value_read_base, context_base} <= 0;
    end else case (state)
      RecordStart: if (transfer) begin
        if (rotary_header) begin
          rotary_index <= 0;
          angle_last <= rx_data[0];
          state <= RotaryBody;
        end else if (address_header) begin
          address_index <= 0;
          state <= AddressBody;
        end else begin
          host_words_left <= rx_is_payload ? 2'd3 : 2'd2;
          state <= HostBody;
        end
      end
      HostBody: if (transfer) begin
        host_words_left <= host_words_left - 1'b1;
        if (host_words_left == 1) state <= RecordStart;
      end
      RotaryBody: if (transfer) begin
        rotary_index <= rotary_index + 1'b1;
        if (rotary_index == 63) state <= RotaryPending;
      end
      RotaryPending: if (angle_ready) state <= RecordStart;
      AddressBody: if (transfer) begin
        address_index <= address_index + 1'b1;
        if (address_index == 7) begin
          {value_read_base, context_base} <= {rx_data, address_words[111:0]};
          state <= RecordStart;
        end
      end
      default: state <= RecordStart;
    endcase
  end
endmodule

// After a successful status, opcode 4 sends the 42-bit prediction record in
// three words and opcode 5 sends the attention row in 128 words. The source
// holds the result until the final word's handshake. Errors end at the status.
module tri_oracle_host_control_tx (
  input logic clk, rst_n,
  input logic source_valid, source_last,
  output logic source_ready,
  input logic [15:0] source_data,
  input logic [41:0] head_values,
  input logic [2047:0] result_values,
  output logic tx_valid, tx_last,
  input logic tx_ready,
  output logic [15:0] tx_data
);
  logic sending, sending_head, head_status, row_status, append_status, capture_head, fetch_group, final_word;
  logic [3:0] next_group;
  logic [2:0] word_index;
  logic [127:0] group_words;

  assign head_status = source_valid && source_last && source_data == 16'h0004;
  assign row_status = source_valid && source_last && source_data == 16'h0005;
  assign append_status = head_status || row_status;
  assign final_word = sending_head ? word_index == 2 : next_group == 0 && word_index == 7;
  assign tx_valid = rst_n && (sending || source_valid);
  assign tx_last = tx_valid && (sending ? final_word : source_last && !append_status);
  assign tx_data = sending ? group_words[{word_index, 4'b0} +: 16] : source_data;
  assign source_ready = rst_n && tx_ready && (sending ? final_word : !append_status);
  assign capture_head = rst_n && !sending && tx_ready && head_status;
  assign fetch_group = rst_n && tx_ready &&
                       (sending ? !sending_head && word_index == 7 && !final_word : row_status);

  always_ff @(posedge clk) begin
    if (capture_head) group_words <= {86'd0, head_values};
    else if (fetch_group) group_words <= result_values[{next_group, 7'b0} +: 128];
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      sending <= 0;
      sending_head <= 0;
      next_group <= 0;
      word_index <= 0;
    end else begin
      if (fetch_group) next_group <= next_group + 1'b1;
      if (sending && tx_ready) begin
        word_index <= final_word ? 3'd0 : word_index + 1'b1;
        if (final_word) sending <= 0;
      end else if (capture_head || fetch_group) begin
        sending <= 1;
        sending_head <= capture_head;
      end
    end
  end
endmodule
