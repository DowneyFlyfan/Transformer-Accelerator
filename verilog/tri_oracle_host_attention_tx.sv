`timescale 1ns/1ps

// Successful attention-row responses append 128 low-word-first transfers
// to the ordinary three-word response. Hold its terminal handshake until
// the entire result transfers, so the core owns and holds the row throughout.
module tri_oracle_host_attention_tx (
  input logic clk, rst_n,
  input logic link_valid, link_last,
  output logic link_ready,
  input logic [15:0] link_data,
  input logic [2047:0] result_values,
  output logic tx_valid, tx_last,
  input logic tx_ready,
  output logic [15:0] tx_data
);
  logic sending, append_status, fetch_group, final_word;
  logic [3:0] next_group;
  logic [2:0] word_index;
  logic [127:0] group_words;

  assign append_status = link_valid && link_last && link_data == 16'h0005;
  assign final_word = next_group == 0 && word_index == 7;
  assign tx_valid = rst_n && (sending || link_valid);
  assign tx_last = tx_valid && (sending ? final_word : link_last && !append_status);
  assign tx_data = sending ? group_words[{word_index, 4'b0} +: 16] : link_data;
  assign link_ready = rst_n && tx_ready && (sending ? final_word : !append_status);
  assign fetch_group = rst_n && tx_ready &&
                       (sending ? word_index == 7 && !final_word : append_status);

  always_ff @(posedge clk)
    if (fetch_group) group_words <= result_values[{next_group, 7'b0} +: 128];

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      sending <= 0;
      next_group <= 0;
      word_index <= 0;
    end else begin
      if (fetch_group) next_group <= next_group + 1'b1;
      if (sending && tx_ready) begin
        word_index <= word_index + 1'b1;
        if (final_word) sending <= 0;
      end else if (fetch_group) begin
        sending <= 1;
      end
    end
  end
endmodule
