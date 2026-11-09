`timescale 1ns/1ps
// The active row with the largest unsigned ID has the largest byte end.
// Keep the original 65-bit arithmetic, including zero-stride underflow.
// This is an input guard only; it does not change generated memory addresses.
module tri_oracle_row_address_guard #(
    parameter int ROWS = 160,
    parameter int COUNT_BITS = $clog2(ROWS + 1)
) (
    input logic [COUNT_BITS-1:0] in_count,
    input logic [ROWS*16-1:0] in_channels,
    input logic [9:0] in_features,
    input logic [63:0] in_weight_base,
    output logic out_overflow
);
  localparam int LEAF_COUNT = 1 << $clog2(ROWS);
  logic [15:0] id_tree [2*LEAF_COUNT];
  logic [15:0] maximum_id;
  logic [64:0] input_bytes, maximum_end;

  always_comb begin
    id_tree[0] = 0;
    for (int row = 0; row < ROWS; row++) begin
      id_tree[LEAF_COUNT + row] = 0;
      if (row < int'(in_count)) id_tree[LEAF_COUNT + row] = in_channels[row*16+:16];
    end
    for (int row = ROWS; row < LEAF_COUNT; row++) id_tree[LEAF_COUNT + row] = 0;
    for (int node = LEAF_COUNT - 1; node > 0; node--)
      id_tree[node] = id_tree[2*node] > id_tree[2*node+1] ? id_tree[2*node] : id_tree[2*node+1];
    maximum_id = id_tree[1];
    input_bytes = 65'(in_features) << 3;
    maximum_end = {1'b0, in_weight_base} + (65'(maximum_id) + 1) * input_bytes - 1;
    out_overflow = 0;
    if (in_count != 0 && maximum_end > 65'h0ffffffffffffffff) out_overflow = 1;
  end
endmodule
