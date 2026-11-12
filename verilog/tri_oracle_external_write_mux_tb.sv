`timescale 1ns/1ps

module tri_oracle_external_write_mux_tb;
  logic clk = 0;
  logic rst_n = 0;
  always #5 clk = ~clk;

  logic scalar_req_valid, scalar_req_ready;
  logic [63:0] scalar_req_address;
  logic [4:0] scalar_req_length;
  logic scalar_data_valid, scalar_data_ready, scalar_data_last;
  logic [63:0] scalar_data;
  logic [7:0] scalar_strobe;
  logic scalar_rsp_valid, scalar_rsp_ready, scalar_rsp_error;
  logic vector_req_valid, vector_req_ready;
  logic [63:0] vector_req_address;
  logic [511:0] vector_req_data;
  logic vector_rsp_valid, vector_rsp_ready, vector_rsp_error;
  logic mem_req_valid, mem_req_ready;
  logic [63:0] mem_req_address;
  logic [4:0] mem_req_length;
  logic mem_data_valid, mem_data_ready, mem_data_last;
  logic [63:0] mem_data;
  logic [7:0] mem_strobe;
  logic mem_rsp_valid, mem_rsp_ready, mem_rsp_error;
  logic [511:0] payload;

  tri_oracle_external_write_mux dut (.*);

  task automatic check_request(input logic [63:0] address, input logic [4:0] length,
                               input logic scalar_grant, vector_grant);
    #1;
    if ({mem_req_valid, mem_req_address, mem_req_length, scalar_req_ready, vector_req_ready}
        !== {1'b1, address, length, scalar_grant, vector_grant})
      $fatal(1, "Unexpected write request at %0t address=%h length=%0d", $time, mem_req_address, mem_req_length);
  endtask

  task automatic check_data(input logic [63:0] word, input logic [7:0] strobe,
                            input logic last, scalar_ready);
    #1;
    if ({mem_data_valid, mem_data, mem_strobe, mem_data_last, scalar_data_ready}
        !== {1'b1, word, strobe, last, scalar_ready}
        || mem_req_valid || mem_rsp_ready || scalar_rsp_valid || vector_rsp_valid)
      $fatal(1, "Wrong write beat or ownership at %0t data=%h", $time, mem_data);
  endtask

  task automatic write_vector(input logic [511:0] expected, input logic error);
    for (int word = 0; word < 8; word++) begin
      mem_data_ready = 0;
      check_data(expected[word*64 +: 64], 8'hff, word == 7, 0);
      @(negedge clk);
      mem_data_ready = 1;
      check_data(expected[word*64 +: 64], 8'hff, word == 7, 0);
      @(negedge clk);
    end
    mem_rsp_valid = 1;
    mem_rsp_error = error;
    repeat (2) begin
      #1;
      if (!vector_rsp_valid || vector_rsp_error !== error || scalar_rsp_valid || mem_rsp_ready || mem_req_valid)
        $fatal(1, "Vector completion was lost or routed to the other client");
      @(negedge clk);
    end
    vector_rsp_ready = 1;
    #1;
    if (!mem_rsp_ready || !vector_rsp_valid) $fatal(1, "Vector response handshake failed");
    @(negedge clk);
    vector_rsp_ready = 0;
    mem_rsp_valid = 0;
  endtask

  initial begin
    scalar_req_valid = 0;
    scalar_req_address = 64'h1088;
    scalar_req_length = 2;
    scalar_data_valid = 0;
    scalar_data = 0;
    scalar_strobe = 0;
    scalar_data_last = 0;
    scalar_rsp_ready = 0;
    vector_req_valid = 0;
    vector_req_address = 64'h8000;
    vector_req_data = 0;
    vector_rsp_ready = 0;
    mem_req_ready = 0;
    mem_data_ready = 0;
    mem_rsp_valid = 0;
    mem_rsp_error = 0;
    for (int word = 0; word < 8; word++) payload[word*64 +: 64] = 64'h123456789abcdef0 ^ (64'(word) << 8);
    repeat (2) @(negedge clk);
    rst_n = 1;

    vector_req_valid = 1;
    vector_req_data = payload;
    check_request(64'h8000, 5'd8, 0, 0);
    @(negedge clk);
    scalar_req_valid = 1;
    check_request(64'h8000, 5'd8, 0, 0);
    @(negedge clk);
    mem_req_ready = 1;
    check_request(64'h8000, 5'd8, 0, 1);
    @(negedge clk);
    vector_req_valid = 0;
    vector_req_data = '0;
    vector_req_address = 64'h9000;
    write_vector(payload, 1);

    vector_req_valid = 1;
    vector_req_data = ~payload;
    check_request(64'h1088, 5'd2, 1, 0);
    @(negedge clk);
    scalar_req_valid = 0;
    scalar_data_valid = 1;
    scalar_data = 64'h1020304050607080;
    scalar_strobe = 8'h5a;
    mem_data_ready = 0;
    check_data(scalar_data, 8'h5a, 0, 0);
    @(negedge clk);
    mem_data_ready = 1;
    check_data(scalar_data, 8'h5a, 0, 1);
    @(negedge clk);
    scalar_data = 64'h0102030405060708;
    scalar_strobe = 8'hc3;
    scalar_data_last = 1;
    mem_rsp_valid = 1;
    mem_rsp_error = 0;
    check_data(scalar_data, 8'hc3, 1, 1);
    @(negedge clk);
    scalar_data_valid = 0;
    repeat (2) begin
      #1;
      if (!scalar_rsp_valid || scalar_rsp_error || vector_rsp_valid || mem_rsp_ready || mem_req_valid)
        $fatal(1, "Scalar completion was lost or routed to the other client");
      @(negedge clk);
    end
    scalar_rsp_ready = 1;
    #1;
    if (!mem_rsp_ready || !scalar_rsp_valid) $fatal(1, "Scalar response handshake failed");
    @(negedge clk);
    mem_rsp_valid = 0;
    scalar_req_valid = 1;

    check_request(64'h9000, 5'd8, 0, 1);
    @(negedge clk);
    vector_req_valid = 0;
    write_vector(~payload, 0);
    check_request(64'h1088, 5'd2, 1, 0);
    $display("TRI_ORACLE_EXTERNAL_WRITE_MUX_PASS scalar_bursts=1 vector_bursts=2");
    $finish;
  end

  initial begin
    #3000;
    $fatal(1, "Write multiplexer test timed out");
  end
endmodule
