`timescale 1ns/1ps
// One divider shared by all weight ports. The core's rising edge is the
// falling memory edge immediately before the memory read slot.
module tri_oracle_weight_phase_clock (
  input logic memory_clk, rst_n,
  output logic core_clk
);
  always_ff @(negedge memory_clk or negedge rst_n) begin
    if (!rst_n) core_clk <= 0;
    else core_clk <= !core_clk;
  end
endmodule
