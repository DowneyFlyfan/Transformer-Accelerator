`timescale 1ns/1ps

module tri_oracle_bounded_weight_decode_tb;
  logic clk = 0;
  logic rst_n = 0;
  logic flush = 0;
  logic in_valid = 0;
  logic out_ready;
  logic [3:0] width;
  logic [6:0] expected_escapes;
  logic [511:0] codes, escapes;
  logic in_ready, out_valid, out_error;
  logic reference_ready, reference_valid, reference_error;
  logic [511:0] weights, reference_weights;
  int cycle, accepted, compared, error_words, stalled_cycles;
  logic [511:0] oracle_weights[$];
  bit oracle_errors[$];

  always #5 clk = !clk;
  always @(negedge clk) cycle <= cycle + 1;
  assign out_ready = cycle % 11 < 7;

  weight_decode_flush reference_decoder (
    .clk, .rst_n, .flush, .in_valid, .out_ready, .width, .expected_escapes, .codes, .escapes,
    .in_ready(reference_ready), .out_valid(reference_valid), .out_error(reference_error), .weights(reference_weights)
  );

`ifdef LEGACY_BOUNDED_DECODER
  weight_decode_flush decoder (
`else
  tri_oracle_bounded_weight_decode decoder (
`endif
    .clk, .rst_n, .flush, .in_valid, .out_ready, .width, .expected_escapes, .codes, .escapes,
    .in_ready, .out_valid, .out_error, .weights
  );

  always @(posedge clk) if (rst_n && !flush) begin
    if (in_ready !== reference_ready || out_valid !== reference_valid)
      $fatal(1, "BOUNDED_DECODER_HANDSHAKE cycle=%0d", cycle);
    if (out_valid && !out_ready)
      stalled_cycles++;
    if (out_valid && out_ready) begin
      logic [511:0] expected_weights;
      bit expected_error;
      if (oracle_weights.size() == 0)
        $fatal(1, "BOUNDED_DECODER_UNEXPECTED_OUTPUT");
      expected_weights = oracle_weights.pop_front();
      expected_error = oracle_errors.pop_front();
      if (out_error !== expected_error || weights !== expected_weights) begin
        if (expected_error && reference_error == 0)
          $fatal(1, "BOUNDED_DECODER_ACCEPTED_OVER_32_ESCAPES");
        $fatal(1, "BOUNDED_DECODER_OUTPUT cycle=%0d", cycle);
      end
      if (!expected_error && (out_error !== reference_error || weights !== reference_weights))
        $fatal(1, "BOUNDED_DECODER_REFERENCE cycle=%0d", cycle);
      compared++;
      error_words += int'(expected_error);
    end
  end

  task automatic submit(int bits, int count, int start, int stride, int claimed);
    logic [511:0] golden;
    bit invalid;
    int literal_rank, code;
    width = 4'(bits);
    expected_escapes = 7'(claimed);
    codes = '0;
    golden = '0;
    invalid = bits < 4 || bits > 8 || count != claimed || claimed > 32;
    for (int lane = 0; lane < 64; lane++)
      escapes[511-8*lane -: 8] = 8'(73*lane + 17 + start);
    literal_rank = 0;
    for (int lane = 0; lane < 64; lane++) begin
      code = bits == 8 ? (lane*13 + start) % 256 : (lane*13 + start) % ((1 << bits)-1);
      if (bits < 8 && ((lane*stride + start) & 63) < count) begin
        code = (1 << bits)-1;
        golden[511-8*lane -: 8] = 8'(73*literal_rank + 17 + start);
        literal_rank++;
      end else begin
        golden[511-8*lane -: 8] = bits == 8 ? 8'(code) : 8'(code - ((1 << (bits-1))-1));
      end
      for (int code_bit = 0; code_bit < bits && bits <= 8; code_bit++)
        codes[511-bits*lane-code_bit] = 1'(code >> (bits-1-code_bit));
    end
    if (literal_rank != count) $fatal(1, "BOUNDED_DECODER_FIXTURE");
    in_valid = 1;
    do @(posedge clk); while (!in_ready);
    #1;
    oracle_weights.push_back(invalid ? '0 : golden);
    oracle_errors.push_back(invalid);
    accepted++;
    @(negedge clk);
    in_valid = 0;
  endtask

  task automatic discard_pipeline;
    flush = 1;
    @(negedge clk);
    flush = 0;
    oracle_weights.delete();
    oracle_errors.delete();
    if (out_valid || out_error || weights !== '0)
      $fatal(1, "BOUNDED_DECODER_FLUSH");
  endtask

  initial begin
    repeat (2) @(negedge clk);
    rst_n = 1;
    submit(4, 33, 0, 1, 33);
    for (int bits = 4; bits <= 7; bits++)
      for (int start = 0; start < 64; start++)
        for (int count = 0; count <= 32; count++)
          submit(bits, count, start, start[0] ? 9 : 1, count);
    submit(8, 0, 23, 1, 0);
    submit(4, 31, 13, 9, 32);
    submit(4, 64, 0, 1, 32);
    submit(9, 0, 0, 1, 0);
    repeat (14) @(negedge clk);
    if (oracle_weights.size() != 0 || accepted != compared || error_words != 4 || stalled_cycles == 0)
      $fatal(1, "BOUNDED_DECODER_INCOMPLETE");

    while (!out_ready) @(negedge clk);
    submit(4, 32, 57, 9, 32);
    discard_pipeline();
    submit(4, 32, 63, 1, 32);
    repeat (14) @(negedge clk);
    if (oracle_weights.size() != 0 || accepted != compared + 1)
      $fatal(1, "BOUNDED_DECODER_POST_FLUSH");
    $display("BOUNDED_DECODER_PASS words=%0d errors=%0d stalls=%0d flushed=1", compared, error_words, stalled_cycles);
    $finish;
  end

  initial begin
    #300us;
    $fatal(1, "BOUNDED_DECODER_TIMEOUT");
  end
endmodule
