`timescale 1ns/1ps
module tri_oracle_packed_read_mux_tb;
  logic clk = 0, rst_n = 0;
  always #5 clk = ~clk;

  logic narrow_req_valid = 0, wide_req_valid = 0, mem_req_ready = 0;
  wire narrow_req_ready, wide_req_ready, mem_req_valid, mem_req_wide;
  logic [63:0] narrow_req_address = 64'h1008, wide_req_address = 64'h8000;
  logic [4:0] narrow_req_length = 2;
  logic [5:0] wide_req_length = 32;
  wire [63:0] mem_req_address;
  wire [5:0] mem_req_length;
  logic narrow_rsp_ready = 0, wide_rsp_ready = 0;
  logic mem_rsp_valid = 0, mem_rsp_last = 0, mem_rsp_error = 0;
  logic [511:0] mem_rsp_data = 0;
  wire mem_rsp_ready, narrow_rsp_valid, narrow_rsp_last, narrow_rsp_error;
  wire wide_rsp_valid, wide_rsp_last, wide_rsp_error;
  wire [63:0] narrow_rsp_data;
  wire [511:0] wide_rsp_data;
  int requests = 0, narrow_beats = 0, wide_beats = 0, stalled_beats = 0;
  bit wrong_lane;

  tri_oracle_packed_read_mux dut (.*);

  always @(posedge clk) if (rst_n) begin
    if ((narrow_rsp_valid && wide_rsp_valid) || (narrow_req_ready && wide_req_ready))
      $fatal(1, "Multiple read clients own the port");
    if (mem_req_valid && mem_req_ready) requests++;
    if (narrow_rsp_valid && narrow_rsp_ready) narrow_beats++;
    if (wide_rsp_valid && wide_rsp_ready) wide_beats++;
    if ((narrow_rsp_valid || wide_rsp_valid) && !mem_rsp_ready) stalled_beats++;
  end

  task automatic request(input bit wide, input logic [63:0] address, input int words);
    mem_req_ready = 1;
    @(posedge clk);
    if (!mem_req_valid || mem_req_wide !== wide || mem_req_address !== address ||
        mem_req_length !== 6'(words) || narrow_req_ready !== !wide || wide_req_ready !== wide)
      $fatal(1, "Incorrect external request address=%h wide=%0d length=%0d", address, wide, words);
    @(negedge clk);
    mem_req_ready = 0;
  endtask

  task automatic response(input bit wide, input int index, input bit last, input bit fault,
                          input int stalled_cycles = 0);
    logic [63:0] expected_narrow;
    mem_rsp_valid = 1;
    mem_rsp_last = last;
    mem_rsp_error = fault;
    for (int lane = 0; lane < 8; lane++)
      mem_rsp_data[64*lane+:64] = 64'hace1beef00000000 | (64'(index) << 8) | 64'(lane);
    expected_narrow = wrong_lane ? mem_rsp_data[127:64] : mem_rsp_data[63:0];
    narrow_rsp_ready = wide || stalled_cycles == 0;
    wide_rsp_ready = !wide || stalled_cycles == 0;
    for (int step = 0; step <= stalled_cycles; step++) begin
      @(posedge clk);
      if (mem_req_valid || mem_rsp_ready !== (step == stalled_cycles) ||
          narrow_rsp_valid !== !wide || wide_rsp_valid !== wide)
        $fatal(1, "Read ownership changed before the accepted terminal response");
      if (wide && {wide_rsp_data,wide_rsp_last,wide_rsp_error} !== {mem_rsp_data,last,fault})
        $fatal(1, "PACKED_READ_MUX_WIDE_DATA_MISMATCH beat=%0d", index);
      if (!wide && {narrow_rsp_data,narrow_rsp_last,narrow_rsp_error} !== {expected_narrow,last,fault})
        $fatal(1, "PACKED_READ_MUX_NARROW_DATA_MISMATCH beat=%0d", index);
      @(negedge clk);
      if (step + 1 == stalled_cycles) begin
        narrow_rsp_ready = 1;
        wide_rsp_ready = 1;
      end
    end
    mem_rsp_valid = 0;
  endtask

  initial begin
    wrong_lane = $test$plusargs("WRONG_LANE");
    repeat (2) @(negedge clk);
    rst_n = 1;
    mem_rsp_valid = 1;
    narrow_rsp_ready = 1;
    wide_rsp_ready = 1;
    @(posedge clk);
    if (mem_rsp_ready || narrow_rsp_valid || wide_rsp_valid) $fatal(1, "Unowned response was forwarded");
    @(negedge clk);
    mem_rsp_valid = 0;

    narrow_req_valid = 1;
    @(negedge clk);
    wide_req_valid = 1;
    repeat (3) begin
      @(posedge clk);
      if (!mem_req_valid || mem_req_wide || mem_req_address !== narrow_req_address ||
          mem_req_length !== 6'd2 || narrow_req_ready || wide_req_ready)
        $fatal(1, "Narrow offer changed when a wide request arrived");
      @(negedge clk);
    end
    request(0, narrow_req_address, 2);
    narrow_req_valid = 0;
    response(0, 0, 0, 1, 2);
    response(0, 1, 1, 0);

    narrow_req_valid = 1;
    narrow_req_address = 64'h2000;
    narrow_req_length = 1;
    request(1, wide_req_address, 32);
    wide_req_valid = 0;
    for (int beat = 0; beat < 32; beat++)
      response(1, beat, beat == 31, beat == 5, beat == 31 ? 3 : 0);

    wide_req_valid = 1;
    wide_req_address = 64'ha000;
    wide_req_length = 3;
    request(0, narrow_req_address, 1);
    narrow_req_valid = 0;
    response(0, 2, 1, 0);
    request(1, wide_req_address, 3);
    wide_req_valid = 0;
    response(1, 32, 0, 1);
    response(1, 33, 0, 0);
    response(1, 34, 0, 0);
    response(1, 35, 1, 0);

    if (requests != 4 || narrow_beats != 3 || wide_beats != 36 || stalled_beats != 5)
      $fatal(1, "Shared read port inventory mismatch");
    $display("PACKED_READ_MUX_PASS requests=4 narrow_beats=3 wide_beats=36 stalled_beats=5");
    $finish;
  end

  initial begin #10000; $fatal(1, "Shared read port timed out"); end
endmodule
