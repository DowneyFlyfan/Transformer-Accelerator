`timescale 1ns/1ps

// Each peer queue slot grants one initial credit. A returned pulse gives
// back one slot after the peer has removed a byte. Both ends reset together
// and keep reset asserted until the registered link's flight time has passed.
module tri_oracle_memory_tx_credit #(
  parameter int CREDITS = 16
) (
  input logic clk, rst_n,
  input logic in_valid,
  output logic in_ready,
  input logic [21:0] in_word,
  output logic pad_valid,
  output logic [7:0] pad_data,
  output wire pad_clock,
  input logic pad_credit,
  output logic protocol_error
);
  localparam int COUNT_BITS = $clog2(CREDITS + 1);
  logic [COUNT_BITS-1:0] available;
  logic credit_received, byte_valid, byte_ready;
  logic [7:0] byte_data;
  wire send = byte_valid && byte_ready;
  wire credit_accepted = credit_received && available != COUNT_BITS'(CREDITS);

  // Data launches on the rising edge. The forwarded clock gives the peer
  // a nominal half period before its capture edge. The return pulse is
  // synchronous to this same clock source and has a separate input budget.
  assign pad_clock = ~clk;
  assign byte_ready = rst_n && available != 0;

  tri_oracle_flit_to_pads serializer (
    .clk, .rst_n, .in_valid, .in_ready, .in_word,
    .pad_valid(byte_valid), .pad_ready(byte_ready), .pad_data(byte_data)
  );

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      available <= COUNT_BITS'(CREDITS);
      credit_received <= 1'b0;
      protocol_error <= 1'b0;
      pad_valid <= 1'b0;
    end else begin
      credit_received <= pad_credit;
      pad_valid <= send;
      if (credit_received && !credit_accepted) protocol_error <= 1'b1;
      if (send && !credit_accepted) available <= available - 1'b1;
      else if (credit_accepted && !send) available <= available + 1'b1;
    end
  end

  always_ff @(posedge clk)
    if (send) pad_data <= byte_data;
endmodule
