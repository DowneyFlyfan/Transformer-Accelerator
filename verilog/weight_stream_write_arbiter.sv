`timescale 1ns/1ps
module weight_stream_write_arbiter (
  input logic clk, rst_n,
  input logic [1:0] offered,
  input logic [1:0][4:0] core,
  input logic [1:0] memory_ready,
  output logic [1:0] granted
);
  logic next_lane, conflict, take_preferred, take_other;
  assign conflict = (&offered) && core[0][4:2] == core[1][4:2];
  assign take_preferred = memory_ready[next_lane];
  assign take_other = !take_preferred && memory_ready[!next_lane];
  assign granted = !conflict ? memory_ready :
      take_preferred ? (2'b01 << next_lane) :
      take_other ? (2'b01 << !next_lane) : 2'b00;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) next_lane <= 0;
    else if (conflict && |granted) next_lane <= granted[0];
  end
endmodule
