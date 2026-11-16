`timescale 1ns/1ps

// The peer starts with eight credits on each lane after a shared reset.
// Sending a chunk spends a credit. A registered return pulse grants one
// replacement credit when a chunk moves from the queue into its head slot. The return path
// may be delayed as long as it preserves every pulse and its lane.
module tri_oracle_credit_memory_ingress (
  input logic clk, rst_n,
  input logic [447:0] pad_data,
  input logic [1:0] pad_valid, pad_last, pad_error, pad_compact,
  input logic [5:0] pad_words,
  output logic [1:0] pad_credit, protocol_error,
  input logic [1:0] out_ready,
  output logic [1:0] out_valid, out_last, out_error,
  output logic [1023:0] out_data
);
  localparam int CREDIT_DEPTH = 8;
  localparam int CHUNK_BITS = 448 + 3 + 3;
  logic [1:0] capture_slot, valid, ready, last, error, compact;
  logic [5:0] words;
  logic [895:0] data;

  tri_oracle_dual_edge_memory_capture capture (
    .clk, .rst_n, .pad_data, .pad_valid, .pad_last, .pad_error, .pad_compact, .pad_words,
    .pad_ready(capture_slot), .out_ready(ready), .out_valid(valid),
    .out_last(last), .out_error(error), .out_compact(compact), .out_words(words), .out_data(data)
  );

  // On a protocol violation report overflow. A conforming peer cannot
  // exhaust the capture slots because unreturned credits cover all queued
  // and in-flight chunks, and the queue alone holds the initial window.
  always_ff @(posedge clk or negedge rst_n)
    if (!rst_n) protocol_error[0] <= 1'b0;
    else if (pad_valid[0] && !capture_slot[0]) protocol_error[0] <= 1'b1;

  always_ff @(negedge clk or negedge rst_n)
    if (!rst_n) protocol_error[1] <= 1'b0;
    else if (pad_valid[1] && !capture_slot[1]) protocol_error[1] <= 1'b1;

  for (genvar lane=0; lane<2; lane++) begin : response_lanes
    logic full, empty, reload, dequeue, head_valid, head_ready;
    logic [CHUNK_BITS-1:0] head;
    logic head_last, head_error, head_compact;
    logic [2:0] head_words;
    logic [447:0] head_data;

    assign ready[lane] = !full;
    assign reload = !head_valid || head_ready;
    assign dequeue = reload && !empty;
    assign {head_last, head_error, head_compact, head_words, head_data} = head;

    // Both ports use the same rising edge. The registered read data is
    // the head slot and remains available when the decoder stalls.
    async_fifo #(.BW(CHUNK_BITS), .MEM_SIZE(CREDIT_DEPTH)) chunks (
      .rd_clk(clk), .wr_clk(clk), .rst_n, .rd(dequeue), .wr(valid[lane]),
      .in({last[lane], error[lane], compact[lane], words[3*lane+:3], data[448*lane+:448]}),
      .out(head), .full, .empty
    );

    always_ff @(posedge clk or negedge rst_n)
      if (!rst_n) begin
        head_valid <= 1'b0;
        pad_credit[lane] <= 1'b0;
      end else begin
        if (reload) head_valid <= !empty;
        pad_credit[lane] <= dequeue;
      end

    tri_oracle_compact_response_lane decoder (
      .clk, .rst_n, .in_valid(head_valid), .in_ready(head_ready),
      .in_compact(head_compact), .in_words(head_words), .in_data(head_data),
      .in_last(head_last), .in_error(head_error),
      .out_ready(out_ready[lane]), .out_valid(out_valid[lane]), .out_last(out_last[lane]),
      .out_error(out_error[lane]), .out_data(out_data[512*lane+:512])
    );
  end
endmodule
