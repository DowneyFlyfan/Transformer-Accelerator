`timescale 1ns/1ps

// Assemble 512-bit read responses from one to seven 64-bit words per clock.
// in_words counts the valid low words of in_data. A chunk can finish at most
// one response. When it does, in_last and in_error describe that response.
// A burst's final chunk stops at the last response boundary.
module tri_oracle_memory_response_gearbox (
  input logic clk, rst_n,
  input logic in_valid,
  output logic in_ready,
  input logic [447:0] in_data,
  input logic [2:0] in_words,
  input logic in_last, in_error,
  output logic out_valid,
  input logic out_ready,
  output logic [511:0] out_data,
  output logic out_last, out_error
);
  logic [2:0] partial_words;
  logic [3:0] combined_words;
  logic completes_beat, input_transfer;
  logic [511:0] partial_data;

  assign combined_words = {1'b0, partial_words} + {1'b0, in_words};
  assign completes_beat = combined_words[3];
  assign in_ready = rst_n && in_words != 0 && (!completes_beat || !out_valid || out_ready);
  assign input_transfer = in_valid && in_ready;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      partial_words <= 0;
      out_valid <= 0;
      out_last <= 0;
      out_error <= 0;
    end else begin
      if (input_transfer) partial_words <= combined_words[2:0];
      if (input_transfer && completes_beat) begin
        out_valid <= 1;
        out_last <= in_last;
        out_error <= in_error;
      end else if (out_ready) begin
        out_valid <= 0;
      end
    end
  end

  for (genvar word_slot = 0; word_slot < 8; word_slot++) begin : g_words
    localparam logic [2:0] SLOT = 3'(word_slot);
    logic [2:0] source_word;
    logic [63:0] next_word;

    // Modulo eight lets trailing words become the start of the next beat.
    // Slot seven of the padded input is never selected for a valid update.
    assign source_word = SLOT - partial_words;
    wire [511:0] padded = {64'd0, in_data};
    assign next_word = padded[{source_word, 6'b0} +: 64];

    always_ff @(posedge clk) begin
      if (input_transfer && source_word < in_words)
        partial_data[word_slot*64 +: 64] <= next_word;
      if (input_transfer && completes_beat)
        out_data[word_slot*64 +: 64] <= SLOT < partial_words
            ? partial_data[word_slot*64 +: 64] : next_word;
    end
  end
endmodule
