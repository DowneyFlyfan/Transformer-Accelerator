`timescale 1ns/1ps
module tri_oracle_weight_write_segments_tb;
  logic clk=0;
  always #5 clk=~clk;
  logic rst_n=0;
  logic decoded_valid=0, decoded_ready;
  logic [31:0] decoded_rows='0;
  logic [2047:0] decoded_payload;
  logic segment_valid, segment_ready=0;
  logic [31:0] segment_rows;
  logic [511:0] segment_payload;
  int emitted=0, consumed=0;

`ifdef RAW_BOUNDARY
  // The registered stage accepts a 512-bit write each cycle.
  assign segment_valid=rst_n && decoded_valid;
  assign decoded_ready=rst_n && segment_ready;
  assign segment_rows=decoded_rows;
  assign segment_payload=decoded_payload[511:0];
`else
  tri_oracle_weight_write_segments dut (.*);
`endif

  always @(posedge clk) if (rst_n) begin
    if (segment_valid && segment_ready) emitted++;
    if (decoded_valid && decoded_ready) consumed++;
  end

  task automatic expect_segment(input int group_index, input bit accepted,
                                input bit last_segment);
    segment_ready=accepted;
    #1;
    if (!segment_valid ||
        segment_rows !== (32'(decoded_rows[8*group_index+:8]) << (8*group_index)) ||
        segment_payload !== decoded_payload[512*group_index+:512])
      $fatal(1,"WEIGHT_SEGMENT_MISMATCH expected_group=%0d rows=%h actual_rows=%h",
             group_index,decoded_rows,segment_rows);
    if (decoded_ready !== (accepted && last_segment))
      $fatal(1,"WEIGHT_WORD_RELEASED_EARLY group=%0d",group_index);
    @(negedge clk);
  endtask

  initial begin
    for (int b=0; b<256; b++) decoded_payload[8*b+:8]=8'(b);
    repeat (2) @(negedge clk);
    rst_n=1;
    for (int mask=1; mask<16; mask++) begin
      logic [3:0] groups;
      groups=4'(mask);
      decoded_valid=1;
      decoded_rows='0;
      decoded_payload=~decoded_payload;
      for (int g=0; g<4; g++)
        if (groups[g]) decoded_rows[8*g+:8]=8'h95 ^ (8'h13 << g);
      for (int g=0; g<4; g++) begin
        if (groups[g]) begin
          groups[g]=0;
          expect_segment(g,0,groups=='0);
          expect_segment(g,1,groups=='0);
        end
      end
    end
    if (emitted!=32 || consumed!=15) $fatal(1,"WEIGHT_MASK_CENSUS");

    decoded_rows='0;
    segment_ready=0;
    #1;
    if (segment_valid || !decoded_ready) $fatal(1,"WEIGHT_EMPTY_WORD");
    @(negedge clk);

    decoded_rows=32'ha200_0053;
    expect_segment(0,1,0);
    decoded_valid=0;
    #1;
    if (segment_valid) $fatal(1,"WEIGHT_CANCELLED_WORD_EMITTED");
    @(negedge clk);
    decoded_valid=1;
    decoded_rows=32'h0000_00dc;
    expect_segment(0,1,1);

    decoded_rows=32'h4500_0001;
    expect_segment(0,1,0);
    rst_n=0;
    #1;
    if (segment_valid || decoded_ready) $fatal(1,"WEIGHT_RESET_HANDSHAKE");
    @(negedge clk);
    rst_n=1;
    decoded_rows=32'h0000_00ba;
    expect_segment(0,1,1);
    if (emitted!=36 || consumed!=18) $fatal(1,"WEIGHT_FINAL_CENSUS");
    $display("WEIGHT_SEGMENTS_PASS masks=16 segments=%0d words=%0d cancellation=1 reset=1",
             emitted,consumed);
    $finish;
  end
endmodule
