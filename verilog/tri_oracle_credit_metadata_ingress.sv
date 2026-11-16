`timescale 1ns/1ps

// The peer presents metadata with the corresponding data on each clock edge.
// Only the capture flops for that edge consume it. Credits and overflow stay
// separate per lane because they describe independently buffered streams.
module tri_oracle_credit_metadata_ingress (
  input logic clk, rst_n,
  input logic [447:0] pad_data,
  input logic [6:0] pad_metadata,
  output logic [1:0] pad_credit, protocol_error,
  input logic [1:0] out_ready,
  output logic [1:0] out_valid, out_last, out_error,
  output logic [1023:0] out_data
);
  tri_oracle_credit_memory_ingress receiver (
    .clk, .rst_n, .pad_data,
    .pad_valid({2{pad_metadata[6]}}),
    .pad_words({2{pad_metadata[5:3]}}),
    .pad_compact({2{pad_metadata[2]}}),
    .pad_last({2{pad_metadata[1]}}),
    .pad_error({2{pad_metadata[0]}}),
    .pad_credit, .protocol_error,
    .out_ready, .out_valid, .out_last, .out_error, .out_data
  );
endmodule
