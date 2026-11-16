`timescale 1ns/1ps
module first_chunk_tb;
  bit clk = 0;
  bit rst_n = 1;
  always #5 clk = ~clk;

  localparam logic [63:0] RISING_WORD = 64'hd48c_a17b_4913_c11c;
  localparam logic [63:0] FALLING_WORD = 64'h076c_b6df_e41b_f678;
  logic [447:0] pad_data = 0;
  logic [1:0] pad_valid = 0;
  wire [1:0] pad_last = 2'b11, pad_error = 0, pad_compact = 2'b11;
  wire [5:0] pad_words = 0;
  wire [1:0] out_ready = 2'b11;
  wire [1:0] pad_credit, protocol_error, out_valid, out_last, out_error;
  wire [1023:0] out_data;

  tri_oracle_credit_memory_ingress dut (.*);

  initial begin
    #1 rst_n = 0;
    #20 rst_n = 1;
    pad_data = {384'd0, RISING_WORD};
    pad_valid = 2'b01;
    #6;
    pad_data = {384'd0, FALLING_WORD};
    pad_valid = 2'b10;
    #5 pad_valid = 0;
    @(posedge clk);
    #1;
    if (pad_credit !== 2'b11)
      $fatal(1, "FIRST_CHUNK_CREDIT_LATE credits=%b", pad_credit);
    @(posedge clk);
    #1;
    if (pad_credit !== 0 || out_valid !== 2'b11 || out_last !== 2'b11 ||
        out_error !== 0 || out_data !== {448'd0, FALLING_WORD, 448'd0, RISING_WORD})
      $fatal(1, "FIRST_CHUNK_RESPONSE_LATE_OR_CORRUPT");
    @(posedge clk);
    #1;
    if (pad_credit !== 0 || out_valid !== 0 || protocol_error !== 0)
      $fatal(1, "FIRST_CHUNK_DUPLICATE_OR_ERROR");
    $display("FIRST_CHUNK_BYPASS_PASS lanes=2");
    $finish;
  end
endmodule
