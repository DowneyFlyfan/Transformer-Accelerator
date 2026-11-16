`timescale 1ns/1ps

// Lane 0 samples the shared data pins on the rising edge. Lane 1 samples
// them on the falling edge. Each lane's sideband and ready are sampled on
// its own edge. Both assembled streams are consumed on the rising edge.
module tri_oracle_dual_edge_memory_capture (
  input logic clk, rst_n,
  input logic [447:0] pad_data,
  input logic [1:0] pad_valid, pad_last, pad_error, pad_compact,
  input logic [5:0] pad_words,
  output logic [1:0] pad_ready,
  input logic [1:0] out_ready,
  output logic [1:0] out_valid, out_last, out_error, out_compact,
  output logic [5:0] out_words,
  output logic [895:0] out_data
);
  logic rising_valid, falling_valid, falling_taken;

  assign out_valid = {2{rst_n}} & {falling_valid, rising_valid};
  assign pad_ready[0] = rst_n && (!rising_valid || out_ready[0]);
  assign pad_ready[1] = rst_n && (!falling_valid || falling_taken);

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      rising_valid <= 1'b0;
      falling_taken <= 1'b0;
    end else begin
      if (pad_ready[0]) rising_valid <= pad_valid[0];
      // A falling-edge slot can be replaced after the rising-edge consumer
      // has accepted it. Backpressure holds the slot across both edges.
      falling_taken <= falling_valid && out_ready[1];
    end
  end

  always_ff @(negedge clk or negedge rst_n)
    if (!rst_n) falling_valid <= 1'b0;
    else if (pad_ready[1]) falling_valid <= pad_valid[1];

  always_ff @(posedge clk)
    if (pad_valid[0] && pad_ready[0]) begin
      out_data[447:0] <= pad_data;
      {out_words[2:0], out_compact[0], out_last[0], out_error[0]} <=
        {pad_words[2:0], pad_compact[0], pad_last[0], pad_error[0]};
    end

  always_ff @(negedge clk)
    if (pad_valid[1] && pad_ready[1]) begin
      out_data[895:448] <= pad_data;
      {out_words[5:3], out_compact[1], out_last[1], out_error[1]} <=
        {pad_words[5:3], pad_compact[1], pad_last[1], pad_error[1]};
    end
endmodule
