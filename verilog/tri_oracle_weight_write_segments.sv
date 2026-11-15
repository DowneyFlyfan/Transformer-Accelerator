`timescale 1ns/1ps
module tri_oracle_weight_write_segments (
  input logic clk, rst_n,
  input logic decoded_valid,
  output logic decoded_ready,
  input logic [31:0] decoded_rows,
  input logic [2047:0] decoded_payload,
  output logic segment_valid,
  input logic segment_ready,
  output logic [31:0] segment_rows,
  output logic [511:0] segment_payload
);
  logic [3:0] enabled_groups, sent_groups, pending_groups, selected_group;
  logic [1:0] group_index;

  assign pending_groups = enabled_groups & ~sent_groups;
  assign selected_group = 4'b0001 << group_index;
  assign segment_valid = rst_n && decoded_valid && (|pending_groups);
  assign decoded_ready = rst_n && decoded_valid &&
      (pending_groups == 0 || (segment_ready && pending_groups == selected_group));
  assign segment_payload = decoded_payload[512*group_index+:512];

  always_comb begin
    if (pending_groups[0]) group_index = 2'd0;
    else if (pending_groups[1]) group_index = 2'd1;
    else if (pending_groups[2]) group_index = 2'd2;
    else group_index = 2'd3;
  end

  for (genvar group_id=0; group_id<4; group_id++) begin : rows
    assign enabled_groups[group_id] = |decoded_rows[8*group_id+:8];
    assign segment_rows[8*group_id+:8] =
        selected_group[group_id] ? decoded_rows[8*group_id+:8] : 8'b0;
  end

  // The decoder holds both payload and metadata until its final segment handshakes.
  // A decoder error can instead withdraw valid and abandon an incomplete word.
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) sent_groups <= '0;
    else if (!decoded_valid || decoded_ready) sent_groups <= '0;
    else if (segment_valid && segment_ready) sent_groups <= sent_groups | selected_group;
  end
endmodule
