`timescale 1ns/1ps
// Release the divider on a memory-clock rising edge, then release the chip
// on a core-clock rising edge. Reset assertion remains asynchronous.
module tri_oracle_phase_chip_clock (
  input logic memory_clk, rst_n,
  output logic core_clk, core_rst_n
);
  (* async_reg = "true" *) logic [1:0] memory_release, core_release;

  always_ff @(posedge memory_clk or negedge rst_n) begin
    if (!rst_n) memory_release <= 0;
    else memory_release <= {memory_release[0], 1'b1};
  end

  tri_oracle_weight_phase_clock divider (
    .memory_clk, .rst_n(memory_release[1]), .core_clk
  );

  always_ff @(posedge core_clk or negedge rst_n) begin
    if (!rst_n) core_release <= 0;
    else core_release <= {core_release[0], 1'b1};
  end
  assign core_rst_n = core_release[1];
endmodule
