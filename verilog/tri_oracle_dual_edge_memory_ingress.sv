`timescale 1ns/1ps

// Expand the two captured seven-word streams into the chip's existing
// 512-bit response lanes.
module tri_oracle_dual_edge_memory_ingress (
  input logic clk, rst_n,
  input logic [447:0] pad_data,
  input logic [1:0] pad_valid, pad_last, pad_error, pad_compact,
  input logic [5:0] pad_words,
  output logic [1:0] pad_ready,
  input logic [1:0] out_ready,
  output logic [1:0] out_valid, out_last, out_error,
  output logic [1023:0] out_data
);
  logic [1:0] captured_valid, captured_ready, captured_last, captured_error, captured_compact;
  logic [5:0] captured_words;
  logic [895:0] captured_data;
  logic [1:0] valid, ready, last, error, compact;
  logic [5:0] words;
  logic [895:0] data;

  tri_oracle_dual_edge_memory_capture capture (
    .clk, .rst_n, .pad_data, .pad_valid, .pad_last, .pad_error, .pad_compact, .pad_words, .pad_ready,
    .out_ready(captured_ready), .out_valid(captured_valid), .out_last(captured_last),
    .out_error(captured_error), .out_compact(captured_compact),
    .out_words(captured_words), .out_data(captured_data)
  );

  assign captured_ready[0] = ready[0];
  assign {valid[0], last[0], error[0], compact[0], words[2:0], data[447:0]} =
         {captured_valid[0], captured_last[0], captured_error[0], captured_compact[0],
          captured_words[2:0], captured_data[447:0]};

  // Register the falling-edge lane before the gearbox's word-count and
  // data selection logic. The elastic slot still accepts one chunk per cycle.
  assign captured_ready[1] = !valid[1] || ready[1];
  always_ff @(posedge clk or negedge rst_n)
    if (!rst_n) valid[1] <= 1'b0;
    else if (captured_ready[1]) valid[1] <= captured_valid[1];

  always_ff @(posedge clk)
    if (captured_ready[1] && captured_valid[1])
      {last[1], error[1], compact[1], words[5:3], data[895:448]} <=
        {captured_last[1], captured_error[1], captured_compact[1],
         captured_words[5:3], captured_data[895:448]};

  for (genvar lane = 0; lane < 2; lane++) begin : response_lanes
    tri_oracle_compact_response_lane decoder (
      .clk, .rst_n, .in_valid(valid[lane]), .in_ready(ready[lane]),
      .in_compact(compact[lane]), .in_data(data[448*lane +: 448]), .in_words(words[3*lane +: 3]),
      .in_last(last[lane]), .in_error(error[lane]),
      .out_valid(out_valid[lane]), .out_ready(out_ready[lane]),
      .out_last(out_last[lane]), .out_error(out_error[lane]), .out_data(out_data[512*lane +: 512])
    );
  end
endmodule
