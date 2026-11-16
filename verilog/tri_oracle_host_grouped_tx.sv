`timescale 1ns/1ps

// Grouped rows use 132 words: marker, tag low/high, cluster/lane/last flags,
// then 128 low-word-first values. The batch owner holds its row until the
// terminal host transfer. Existing responses retain their full framing.
module tri_oracle_host_grouped_tx (
  input logic clk, rst_n,
  input logic source_valid, source_last,
  input logic [15:0] source_data,
  output logic source_ready,
  input logic group_valid, group_last,
  input logic [31:0] group_tag,
  input logic [2:0] group_cluster,
  input logic [1:0] group_lane,
  input logic [2047:0] group_values,
  output logic group_ready,
  input logic tx_ready,
  output logic tx_valid, tx_last,
  output logic [15:0] tx_data
);
  logic sending, source_in_progress, start_group, fetch_group, final_word;
  logic [7:0] word_index;
  logic [3:0] next_group;
  logic [2:0] lane_index;
  logic [127:0] window_values;
  logic [31:0] row_tag;
  logic [5:0] row_flags;

  assign start_group = rst_n && !sending && !source_in_progress && !source_valid && group_valid;
  assign source_ready = rst_n && !sending && !start_group && tx_ready;
  assign final_word = word_index == 8'd131;
  assign group_ready = rst_n && sending && final_word && tx_ready;
  assign tx_valid = rst_n && (sending || source_valid);
  assign tx_last = tx_valid && (sending ? final_word : source_last);
  assign lane_index = word_index[2:0] - 3'd4;
  assign fetch_group = start_group || (sending && tx_ready && !final_word &&
                                      word_index >= 8'd11 && word_index[2:0] == 3'd3);

  always_comb begin
    if (!sending) tx_data = source_data;
    else begin
      case (word_index)
        8'd0: tx_data = 16'ha680;
        8'd1: tx_data = row_tag[15:0];
        8'd2: tx_data = row_tag[31:16];
        8'd3: tx_data = {10'b0, row_flags};
        default: tx_data = window_values[{lane_index, 4'b0} +: 16];
      endcase
    end
  end

  always_ff @(posedge clk) begin
    if (start_group) begin
      row_tag <= group_tag;
      row_flags <= {group_last, group_lane, group_cluster};
    end
    if (fetch_group) window_values <= group_values[{next_group, 7'b0} +: 128];
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      sending <= 1'b0;
      source_in_progress <= 1'b0;
      word_index <= '0;
      next_group <= '0;
    end else begin
      if (!sending && source_valid)
        source_in_progress <= !(tx_ready && source_last);
      if (fetch_group) next_group <= next_group + 1'b1;
      if (start_group) sending <= 1'b1;
      else if (sending && tx_ready) begin
        word_index <= final_word ? 8'd0 : word_index + 1'b1;
        if (final_word) sending <= 1'b0;
      end
    end
  end
endmodule
