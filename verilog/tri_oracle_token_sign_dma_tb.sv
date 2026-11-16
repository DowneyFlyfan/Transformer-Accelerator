`timescale 1ns/1ps

module tri_oracle_token_sign_dma_tb;
  bit clk = 0, rst_n = 0;
  always #5 clk = !clk;
  logic merge_start = 0, merge_finish = 0, config_valid = 0;
  logic [35:0] config_line = '0;
  logic sign_valid, sign_ready = 0;
  logic [2047:0] sign_data;
  logic native_req_valid = 0, native_req_ready;
  logic [63:0] native_req_address = '0;
  logic [5:0] native_req_length = '0;
  logic native_rsp_valid, native_rsp_ready = 0, native_rsp_last, native_rsp_error;
  logic [511:0] native_rsp_data;
  logic req_valid, req_ready = 0;
  logic [63:0] req_address;
  logic [5:0] req_length;
  logic rsp_valid = 0, rsp_ready, rsp_last = 0, rsp_error = 0;
  logic [511:0] rsp_data = '0;
  int read_requests, vectors;
  localparam logic [63:0] SignBase = 64'h40000000;

  tri_oracle_token_sign_dma dut (.*);
  always @(posedge clk) if (rst_n) begin
    if (req_valid && req_ready) read_requests++;
    if (sign_valid && sign_ready) vectors++;
  end

  task automatic request(input logic [63:0] address, input logic [5:0] length);
    do @(posedge clk); while (!req_valid);
    repeat (3) begin
      if ({req_valid, req_address, req_length} !== {1'b1, address, length})
        $fatal(1, "SIGN_DMA_REQUEST");
      @(posedge clk);
    end
    @(negedge clk);
    req_ready = 1;
    @(negedge clk);
    req_ready = 0;
  endtask

  task automatic beat(input logic [511:0] data, input bit last, error);
    rsp_valid = 1;
    rsp_data = data;
    rsp_last = last;
    rsp_error = error;
    do @(posedge clk); while (!rsp_ready);
    @(negedge clk);
    rsp_valid = 0;
  endtask

  task automatic fetch(input int vector);
    logic [2047:0] expected;
    request(SignBase + 64'(vector * 256), 4);
    sign_ready = 0;
    for (int index = 0; index < 4; index++) begin
      if (sign_valid || native_rsp_valid) $fatal(1, "SIGN_DMA_PUBLISHED_EARLY");
      expected[index * 512 +: 512] = {16{32'(32'h51A00000 + vector * 256 + index)}};
      beat(expected[index * 512 +: 512], index == 3, 0);
      @(negedge clk);
    end
    repeat (4) begin
      if (!sign_valid || sign_data !== expected || req_valid) $fatal(1, "SIGN_DMA_VECTOR_OR_HOLD");
      @(negedge clk);
    end
    sign_ready = 1;
    @(negedge clk);
  endtask

  task automatic native_request(input logic [63:0] address);
    native_req_valid = 1;
    native_req_address = address;
    native_req_length = 1;
    request(address, 1);
    native_req_valid = 0;
  endtask

  task automatic native_tail;
    rsp_valid = 1;
    rsp_data = 512'h789;
    rsp_last = 1;
    rsp_error = 0;
    repeat (3) begin
      @(posedge clk);
      if (req_valid || sign_valid || rsp_ready || !native_rsp_valid)
        $fatal(1, "SIGN_DMA_INTERRUPTED_NATIVE_RESPONSE");
      @(negedge clk);
    end
    native_rsp_ready = 1;
    @(posedge clk);
    if ({rsp_ready, native_rsp_valid, native_rsp_last, native_rsp_error, native_rsp_data} !==
        {1'b1, 1'b1, 1'b1, 1'b0, 512'h789}) $fatal(1, "SIGN_DMA_NATIVE_RESPONSE");
    @(negedge clk);
    native_rsp_ready = 0;
    rsp_valid = 0;
  endtask

  initial begin
    repeat (3) @(negedge clk);
    rst_n = 1;
    repeat (3) @(negedge clk);
    if (req_valid || sign_valid) $fatal(1, "SIGN_DMA_UNCONFIGURED");
    native_request(64'h2300);
    merge_start = 1;
    @(negedge clk);
    merge_start = 0;
    config_line = SignBase[41:6];
    config_valid = 1;
    @(negedge clk);
    config_valid = 0;
    native_tail();
    request(SignBase, 4);
    beat(512'h1234, 0, 1);
    if (sign_valid || req_valid) $fatal(1, "SIGN_DMA_FAULT_NOT_DRAINED");
    beat(512'h5678, 1, 0);
    fetch(0);
    fetch(1);
    sign_ready = 0;
    merge_finish = 1;
    @(negedge clk);
    merge_finish = 0;
    native_request(64'h2340);
    native_tail();
    if (read_requests != 5 || vectors != 2) $fatal(1, "SIGN_DMA_COUNTS");
    $display("TOKEN_SIGN_DMA_PASS vectors=2 reads=5 native=2 retries=1");
    $finish;
  end

  initial begin
    #20000;
    $fatal(1, "TOKEN_SIGN_DMA_TIMEOUT");
  end
endmodule
