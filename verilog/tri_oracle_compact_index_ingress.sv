`timescale 1ns/1ps

// A compact response is one terminal chunk with two low 64-bit words.
// Its reserved bits stay visible to the existing index decoder. A producer
// dropping nonzero high padding must assert in_error. Ordinary responses
// retain the full-width gearbox and must complete before a compact response.
module tri_oracle_compact_index_ingress (
  input logic clk, rst_n,
  input logic in_valid,
  output logic in_ready,
  input logic in_compact,
  input logic [447:0] in_data,
  input logic [2:0] in_words,
  input logic in_last, in_error,
  output logic out_valid,
  input logic out_ready,
  output logic [511:0] out_data,
  output logic out_last, out_error
);
  logic wide_ready, wide_valid, wide_last, wide_error, wide_burst_open;
  logic [511:0] wide_data;
  logic compact_valid, compact_error;
  logic [127:0] compact_data;

  assign in_ready = rst_n && !compact_valid &&
                    (in_compact ? !wide_burst_open && !wide_valid : wide_ready);
  assign out_valid = compact_valid || wide_valid;
  assign out_data = compact_valid ? {384'd0, compact_data} : wide_data;
  assign out_last = compact_valid || wide_last;
  assign out_error = compact_valid ? compact_error : wide_error;

  tri_oracle_memory_response_gearbox wide_response (
    .clk, .rst_n, .in_valid(in_valid && !in_compact && !compact_valid), .in_ready(wide_ready),
    .in_data, .in_words, .in_last, .in_error, .out_valid(wide_valid),
    .out_ready(out_ready && !compact_valid), .out_data(wide_data),
    .out_last(wide_last), .out_error(wide_error)
  );

  always_ff @(posedge clk)
    if (in_valid && in_ready && in_compact) compact_data <= in_data[127:0];

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      wide_burst_open <= 0;
      compact_valid <= 0;
      compact_error <= 0;
    end else begin
      if (compact_valid && out_ready) compact_valid <= 0;
      if (in_valid && in_ready) begin
        if (in_compact) begin
          compact_valid <= 1;
          compact_error <= in_error || in_words != 2 || !in_last;
        end else begin
          wide_burst_open <= !in_last;
        end
      end
    end
  end
endmodule
