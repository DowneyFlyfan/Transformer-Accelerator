`timescale 1ns/1ps

// Transmit the least-significant pad word first. The source holds the
// complete word valid until the final pad handshake acknowledges it.
module tri_oracle_flit_to_pads #(
  parameter int WORD_BITS = 22,
  parameter int PAD_BITS = 8
) (
  input logic clk, rst_n,
  input logic in_valid,
  output logic in_ready,
  input logic [WORD_BITS-1:0] in_word,
  output logic pad_valid,
  input logic pad_ready,
  output logic [PAD_BITS-1:0] pad_data
);
  localparam int PARTS = (WORD_BITS + PAD_BITS - 1) / PAD_BITS;
  localparam int INDEX_BITS = $clog2(PARTS);
  logic [INDEX_BITS-1:0] index;
  wire last_part = index == INDEX_BITS'(PARTS - 1);
  wire [PARTS*PAD_BITS-1:0] frame = (PARTS*PAD_BITS)'(in_word);

  assign pad_valid = rst_n && in_valid;
  assign in_ready = rst_n && pad_ready && last_part;
  assign pad_data = frame[index*PAD_BITS+:PAD_BITS];

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) index <= '0;
    else if (pad_valid && pad_ready) index <= last_part ? '0 : index + 1'b1;
  end
endmodule

// Buffer each early pad word. On the final beat the assembled transfer and
// its acknowledgment go directly to the ready/valid destination.
module tri_oracle_flit_from_pads #(
  parameter int WORD_BITS = 22,
  parameter int PAD_BITS = 8
) (
  input logic clk, rst_n,
  input logic pad_valid,
  output logic pad_ready,
  input logic [PAD_BITS-1:0] pad_data,
  output logic out_valid,
  input logic out_ready,
  output logic [WORD_BITS-1:0] out_word
);
  localparam int PARTS = (WORD_BITS + PAD_BITS - 1) / PAD_BITS;
  localparam int INDEX_BITS = $clog2(PARTS);
  logic [INDEX_BITS-1:0] index;
  logic [(PARTS-1)*PAD_BITS-1:0] earlier;
  wire last_part = index == INDEX_BITS'(PARTS - 1);

  assign pad_ready = rst_n && (!last_part || out_ready);
  assign out_valid = rst_n && pad_valid && last_part;
  assign out_word = WORD_BITS'({pad_data, earlier});

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) index <= '0;
    else if (pad_valid && pad_ready) index <= last_part ? '0 : index + 1'b1;
  end

  always_ff @(posedge clk)
    if (pad_valid && pad_ready && !last_part)
      earlier[index*PAD_BITS+:PAD_BITS] <= pad_data;
endmodule
