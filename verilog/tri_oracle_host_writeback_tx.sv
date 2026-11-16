`timescale 1ns/1ps

// Writeback records use 13 transfers: marker, tag low/high, start,
// {reserved, frame last, count, token}, then eight low-word-first values.
// Host responses keep their original framing. The marker can also appear in a
// response tag, so the receiver distinguishes records by length at tx_last.
module tri_oracle_host_writeback_tx (
  input logic clk, rst_n,
  input logic source_valid, source_last,
  input logic [15:0] source_data,
  output logic source_ready,
  input logic wb_valid, wb_last,
  input logic [31:0] wb_tag,
  input logic [3:0] wb_token, wb_count,
  input logic [15:0] wb_start,
  input logic [127:0] wb_data,
  output logic wb_ready,
  input logic tx_ready,
  output logic tx_valid, tx_last,
  output logic [15:0] tx_data
);
  logic source_in_progress, strip_pending, send_strip;
  logic [3:0] word_index;
  logic [2:0] data_index;
  logic [31:0] strip_tag;
  logic [15:0] strip_start;
  logic [8:0] strip_flags;
  logic [127:0] strip_data;
  logic [15:0] strip_word;

  assign send_strip = strip_pending && !source_in_progress;
  assign wb_ready = rst_n && !strip_pending;
  assign source_ready = rst_n && !send_strip && tx_ready;
  assign tx_valid = rst_n && (send_strip || source_valid);
  assign tx_last = tx_valid && (send_strip ? word_index == 4'd12 : source_last);
  assign tx_data = send_strip ? strip_word : source_data;
  assign data_index = word_index[2:0] - 3'd5;

  always_comb begin
    case (word_index)
      4'd0: strip_word = 16'ha67e;
      4'd1: strip_word = strip_tag[15:0];
      4'd2: strip_word = strip_tag[31:16];
      4'd3: strip_word = strip_start;
      4'd4: strip_word = {7'b0, strip_flags};
      default: strip_word = strip_data[{data_index, 4'b0} +: 16];
    endcase
  end

  always_ff @(posedge clk)
    if (wb_valid && wb_ready) begin
      strip_tag <= wb_tag;
      strip_start <= wb_start;
      strip_flags <= {wb_last, wb_count, wb_token};
      strip_data <= wb_data;
    end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      source_in_progress <= 1'b0;
      strip_pending <= 1'b0;
      word_index <= '0;
    end else begin
      // Lock even a stalled first word, and retain ownership across gaps.
      if (!send_strip && source_valid)
        source_in_progress <= !(tx_ready && source_last);

      if (wb_valid && wb_ready)
        strip_pending <= 1'b1;
      else if (send_strip && tx_ready) begin
        word_index <= tx_last ? 4'd0 : word_index + 1'b1;
        if (tx_last) strip_pending <= 1'b0;
      end
    end
  end
endmodule
