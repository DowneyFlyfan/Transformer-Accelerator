`timescale 1ns/1ps

module tri_oracle_flit_round_trip #(
  parameter int WORD_BITS = 22,
  parameter int PAD_BITS = 8
) (output bit done);
  localparam int PARTS = (WORD_BITS + PAD_BITS - 1) / PAD_BITS;
  localparam int COUNT = 96;
  bit clk = 0, rst_n = 0;
  always #5 clk = !clk;
  logic in_valid, in_ready, pad_valid, pad_ready, receive_ready, out_valid, out_ready;
  logic [WORD_BITS-1:0] in_word, out_word;
  logic [PAD_BITS-1:0] pad_data;
  bit wire_open, no_stalls, blocked;
  logic [PAD_BITS-1:0] held;
  int sent, received, beats, tick;

  tri_oracle_flit_to_pads #(.WORD_BITS(WORD_BITS), .PAD_BITS(PAD_BITS)) transmitter (
    .clk, .rst_n, .in_valid, .in_ready, .in_word, .pad_valid, .pad_ready, .pad_data
  );
  tri_oracle_flit_from_pads #(.WORD_BITS(WORD_BITS), .PAD_BITS(PAD_BITS)) receiver (
    .clk, .rst_n, .pad_valid(pad_valid && wire_open), .pad_ready(receive_ready), .pad_data,
    .out_valid, .out_ready, .out_word
  );
  assign pad_ready = wire_open && receive_ready;

  function automatic logic [WORD_BITS-1:0] fixture(input int ordinal);
    return WORD_BITS'(32'h99c2_fa31 * 32'(ordinal) ^ (32'h55a3_6b17 >> (ordinal % 5)));
  endfunction

  always @(posedge clk) begin
    logic [PARTS*PAD_BITS-1:0] expected;
    if (!rst_n) begin
      sent = 0;
      received = 0;
      beats = 0;
      tick = 0;
      blocked = 0;
    end else begin
      tick++;
      if (blocked && (!pad_valid || pad_data !== held)) $fatal(1, "PAD_FLIT_CHANGED_DURING_STALL");
      blocked = pad_valid && !pad_ready;
      held = pad_data;
      if (pad_valid && pad_ready) begin
        expected = (PARTS*PAD_BITS)'(fixture(sent));
        if (pad_data !== expected[(beats % PARTS)*PAD_BITS+:PAD_BITS])
          $fatal(1, "PAD_ORDER_MISMATCH");
        beats++;
      end
      if (in_valid && in_ready) begin
        if (beats != (sent + 1) * PARTS) $fatal(1, "EARLY_SOURCE_ACKNOWLEDGMENT");
        if (no_stalls && tick != (sent + 1) * PARTS) $fatal(1, "UNEXPECTED_LINK_BUBBLE");
        sent++;
      end
      if (out_valid && out_ready) begin
        if (received >= sent || out_word !== fixture(received)) $fatal(1, "WORD_ROUND_TRIP_MISMATCH");
        received++;
      end
    end
  end

  initial begin
    done = 0;
    in_valid = 0;
    in_word = '0;
    out_ready = 1;
    wire_open = 1;
    no_stalls = 0;
    repeat (2) @(negedge clk);
    rst_n = 1;
    // Reset halfway through a word and restart with a different remaining bit pattern.
    in_valid = 1;
    in_word = fixture(0);
    repeat (PARTS - 1) @(negedge clk);
    if (received != 0 || in_ready && pad_valid && beats == 0) $fatal(1, "PARTIAL_WORD_ACKNOWLEDGED");
    rst_n = 0;
    in_valid = 0;
    repeat (2) @(negedge clk);
    no_stalls = 1;
    rst_n = 1;
    while (sent != COUNT) begin
      in_word = fixture(sent);
      in_valid = 1;
      @(negedge clk);
    end
    in_valid = 0;
    if (received != COUNT) $fatal(1, "MISSING_CONTINUOUS_WORD");
    rst_n = 0;
    repeat (2) @(negedge clk);
    no_stalls = 0;
    rst_n = 1;
    while (sent != COUNT) begin
      in_word = fixture(sent);
      in_valid = 1;
      wire_open = tick % 5 < 3;
      out_ready = tick % 11 < 4;
      @(negedge clk);
    end
    in_valid = 0;
    if (received != COUNT || tick <= COUNT * PARTS) $fatal(1, "STALL_WORD_COVERAGE_MISSING");
    $display("SERIAL_FLIT_BRIDGE_PASS word_bits=%0d pad_bits=%0d parts=%0d words=%0d stall_cycles=%0d",
             WORD_BITS, PAD_BITS, PARTS, received, tick - COUNT * PARTS);
    done = 1;
  end
endmodule

module tri_oracle_serial_flit_bridge_tb;
  wire request_done, host_receive_done, host_transmit_done;
  tri_oracle_flit_round_trip #(.WORD_BITS(22), .PAD_BITS(8)) request_link (request_done);
  tri_oracle_flit_round_trip #(.WORD_BITS(18), .PAD_BITS(4)) host_rx_link (host_receive_done);
  tri_oracle_flit_round_trip #(.WORD_BITS(17), .PAD_BITS(4)) host_tx_link (host_transmit_done);
  initial begin
    wait (request_done && host_receive_done && host_transmit_done);
    $finish;
  end
  initial begin
    #100000;
    $fatal(1, "SERIAL_FLIT_BRIDGE_TIMEOUT");
  end
endmodule
