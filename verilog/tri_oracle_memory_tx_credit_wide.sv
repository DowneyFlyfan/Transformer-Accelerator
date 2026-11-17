`timescale 1ns/1ps

// A full 22-bit request flit is transferred on each credited pad cycle.
// The shared reset restores the peer's sixteen capture slots and discards
// any pending transfers. Data launches a half-cycle before the peer edge.
module tri_oracle_memory_tx_credit_wide (
  input  logic clk,
  input  logic rst_n,
  input  logic in_valid,
  output logic in_ready,
  input  logic [21:0] in_word,
  output logic pad_valid,
  output logic [21:0] pad_data,
  output logic pad_clock,
  input  logic pad_credit,
  output logic protocol_error
);
  localparam logic [4:0] InitialCredits = 5'd16;
  logic [4:0] available;
  logic credit_received;
  logic send, credit_accepted;

  assign pad_clock = ~clk;
  assign in_ready = rst_n && available != 0;
  assign send = in_valid && in_ready;
  assign credit_accepted = credit_received && available != InitialCredits;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      available <= InitialCredits;
      credit_received <= 1'b0;
      pad_valid <= 1'b0;
      protocol_error <= 1'b0;
    end else begin
      credit_received <= pad_credit;
      pad_valid <= send;
      if (credit_received && !credit_accepted) protocol_error <= 1'b1;
      if (send && !credit_accepted) available <= available - 1'b1;
      else if (credit_accepted && !send) available <= available + 1'b1;
    end
  end

  always_ff @(posedge clk)
    if (send) pad_data <= in_word;
endmodule
