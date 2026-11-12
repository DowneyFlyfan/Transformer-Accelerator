`timescale 1ns/1ps

module tri_oracle_external_read_mux_tb;
  logic clk = 0;
  logic rst_n = 0;
  always #5 clk = ~clk;

  logic scalar_req_valid, scalar_req_ready;
  logic [63:0] scalar_req_address;
  logic [4:0] scalar_req_length;
  logic scalar_rsp_valid, scalar_rsp_ready, scalar_rsp_last, scalar_rsp_error;
  logic [63:0] scalar_rsp_data;
  logic vector_req_valid, vector_req_ready;
  logic [63:0] vector_req_address;
  logic vector_rsp_valid, vector_rsp_ready, vector_rsp_error;
  logic [511:0] vector_rsp_data;
  logic mem_req_valid, mem_req_ready;
  logic [63:0] mem_req_address;
  logic [4:0] mem_req_length;
  logic mem_rsp_valid, mem_rsp_ready, mem_rsp_last, mem_rsp_error;
  logic [63:0] mem_rsp_data;
  logic [511:0] expected_vector;

  tri_oracle_external_read_mux dut (.*);

  task automatic expect_request(input logic [63:0] address, input logic [4:0] length,
                                input logic scalar_grant, vector_grant);
    #1;
    if ({mem_req_valid, mem_req_address, mem_req_length, scalar_req_ready, vector_req_ready}
        !== {1'b1, address, length, scalar_grant, vector_grant})
      $fatal(1, "Unexpected request at %0t address=%h length=%0d", $time, mem_req_address, mem_req_length);
  endtask

  task automatic vector_beat(input logic [63:0] word, input logic last, error);
    mem_rsp_valid = 1;
    mem_rsp_data = word;
    mem_rsp_last = last;
    mem_rsp_error = error;
    #1;
    if (!mem_rsp_ready || scalar_rsp_valid || vector_rsp_valid)
      $fatal(1, "Vector beat escaped the vector receiver at %0t", $time);
    @(posedge clk);
    @(negedge clk);
    mem_rsp_valid = 0;
  endtask

  task automatic check_vector(input logic error, input logic [511:0] data);
    repeat (3) begin
      #1;
      if (!vector_rsp_valid || vector_rsp_error !== error || vector_rsp_data !== data || mem_req_valid)
        $fatal(1, "Invalid or unstable vector response at %0t", $time);
      @(negedge clk);
    end
    vector_rsp_ready = 1;
    @(posedge clk);
    @(negedge clk);
    vector_rsp_ready = 0;
  endtask

  task automatic start_vector(input logic [63:0] address);
    vector_req_address = address;
    vector_req_valid = 1;
    expect_request(address, 5'd8, 0, 1);
    @(posedge clk);
    @(negedge clk);
    vector_req_valid = 0;
  endtask

  initial begin
    scalar_req_valid = 0;
    scalar_req_address = 64'h1238;
    scalar_req_length = 2;
    scalar_rsp_ready = 0;
    vector_req_valid = 0;
    vector_req_address = 64'h9000;
    vector_rsp_ready = 0;
    mem_req_ready = 0;
    mem_rsp_valid = 0;
    mem_rsp_last = 0;
    mem_rsp_error = 0;
    mem_rsp_data = 0;
    repeat (2) @(negedge clk);
    rst_n = 1;

    // A vector request arriving during a scalar stall cannot replace its address.
    scalar_req_valid = 1;
    expect_request(64'h1238, 5'd2, 0, 0);
    @(negedge clk);
    vector_req_valid = 1;
    repeat (2) begin
      expect_request(64'h1238, 5'd2, 0, 0);
      @(negedge clk);
    end
    mem_req_ready = 1;
    expect_request(64'h1238, 5'd2, 1, 0);
    @(negedge clk);
    scalar_req_valid = 0;

    mem_rsp_valid = 1;
    mem_rsp_data = 64'h123456789abcdef0;
    repeat (2) begin
      #1;
      if (!scalar_rsp_valid || mem_rsp_ready || scalar_rsp_last || scalar_rsp_error || vector_rsp_valid
          || scalar_rsp_data !== mem_rsp_data || mem_req_valid)
        $fatal(1, "Scalar response backpressure or ownership failed");
      @(negedge clk);
    end
    scalar_rsp_ready = 1;
    @(negedge clk);
    mem_rsp_data = 64'hf0debc9a78563412;
    mem_rsp_error = 1;
    mem_rsp_last = 1;
    #1;
    if (!scalar_rsp_valid || !mem_rsp_ready || !scalar_rsp_last || !scalar_rsp_error
        || scalar_rsp_data !== mem_rsp_data || vector_rsp_valid)
      $fatal(1, "Scalar final beat or error was lost");
    @(negedge clk);
    mem_rsp_valid = 0;
    scalar_req_valid = 1;
    // Both clients are pending. The client that did not get the last grant wins.
    expect_request(64'h9000, 5'd8, 0, 1);
    @(negedge clk);
    vector_req_valid = 0;
    for (int word = 0; word < 8; word++) begin
      expected_vector[word*64 +: 64] = 64'h13579abc12340000 | 64'(word);
      vector_beat(expected_vector[word*64 +: 64], word == 7, 0);
    end
    check_vector(0, expected_vector);
    expect_request(64'h1238, 5'd2, 1, 0);
    @(negedge clk);
    scalar_req_valid = 0;
    mem_rsp_valid = 1;
    mem_rsp_last = 0;
    mem_rsp_error = 0;
    @(negedge clk);
    mem_rsp_last = 1;
    @(negedge clk);
    mem_rsp_valid = 0;

    start_vector(64'h9100);
    vector_beat(64'ha5, 1, 0);
    check_vector(1, '0);

    start_vector(64'h9200);
    for (int word = 0; word < 8; word++) vector_beat(64'(word), 0, 0);
    vector_beat(64'hdead, 0, 0);
    vector_beat(64'hbeef, 1, 0);
    check_vector(1, '0);

    start_vector(64'h9300);
    for (int word = 0; word < 8; word++) vector_beat(64'(word), word == 7, word == 3);
    check_vector(1, '0);
    $display("TRI_ORACLE_EXTERNAL_READ_MUX_PASS scalar_bursts=2 vector_bursts=4");
    $finish;
  end

  initial begin
    #3000;
    $fatal(1, "Read multiplexer test timed out");
  end
endmodule
