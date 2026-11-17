`timescale 1ns/1ps
module tri_oracle_weight_write_buffer_tb;
  logic clk = 0;
  always #5 clk = !clk;

  logic rst_n = 0;
  logic [1:0] load_valid = 0, load_ready, pending, write_valid, write_ready = 0;
  logic [1:0][4:0] load_core = '0, write_core;
  logic [1:0][9:0] load_addr = '0, write_addr;
  logic [1:0][31:0] load_row_enable = '0, write_row_enable;
  logic [1:0][1023:0] load_payload = '0, write_payload;
  logic loader_done_valid = 0, loader_done_error = 0, loader_done_ready;
  logic done_ready = 0, done_valid, done_error;
  int accepted_writes = 0;

  tri_oracle_weight_write_buffer dut (.*);

  function automatic logic [1023:0] value(input int number);
    return {32{32'h45ab0123 ^ (32'h10203 * 32'(number))}};
  endfunction

  task automatic offer(input int lane, input int core, input int word);
    load_valid[lane] = 1;
    load_core[lane] = 5'(core);
    load_addr[lane] = 10'(word);
    load_row_enable[lane] = 32'h10000240 ^ (32'd1 << word);
    load_payload[lane] = value(word);
  endtask

  task automatic check_write(input int lane, input int core, input int word);
    if (write_core[lane] !== 5'(core) || write_addr[lane] !== 10'(word) ||
        write_row_enable[lane] !== (32'h10000240 ^ (32'd1 << word)) ||
        write_payload[lane] !== value(word))
      $fatal(1, "WEIGHT_BUFFER_PAYLOAD lane=%0d word=%0d", lane, word);
  endtask

  task automatic step(input logic [1:0] expected_pending, input logic [1:0] expected_writes,
                      input logic [1:0] expected_ready, input bit expected_done);
    #1;
    if (pending !== expected_pending || write_valid !== expected_writes ||
        load_ready !== expected_ready || done_valid !== expected_done ||
        loader_done_ready !== (expected_done && done_ready))
      $fatal(1, "WEIGHT_BUFFER_HANDSHAKE got=%b/%b/%b/%b expected=%b/%b/%b/%b",
             pending, write_valid, load_ready, done_valid,
             expected_pending, expected_writes, expected_ready, expected_done);
    if (done_valid && done_error !== loader_done_error) $fatal(1, "WEIGHT_BUFFER_DONE_ERROR");
    accepted_writes += $countones(write_valid);
  endtask

  initial begin
    repeat (2) @(negedge clk);
    rst_n = 1;
    write_ready = 2'b10;
    offer(0, 8, 1);
    offer(1, 12, 2);
    step(2'b00, 2'b00, 2'b11, 0);

    @(negedge clk);
    load_valid = 0;
    offer(1, 10, 3);
    step(2'b11, 2'b10, 2'b10, 0);
    check_write(1, 12, 2);

    @(negedge clk);
    load_valid = 0;
    loader_done_valid = 1;
    loader_done_error = 1;
    step(2'b11, 2'b10, 2'b10, 0);
    check_write(0, 8, 1);
    check_write(1, 10, 3);
    @(negedge clk);
    write_ready = 2'b00;
    repeat (3) begin
      step(2'b01, 2'b00, 2'b10, 0);
      check_write(0, 8, 1);
      @(negedge clk);
    end
    write_ready = 2'b11;
    step(2'b01, 2'b01, 2'b11, 0);
    check_write(0, 8, 1);

    @(negedge clk);
    step(2'b00, 2'b00, 2'b11, 1);
    @(negedge clk);
    done_ready = 1;
    step(2'b00, 2'b00, 2'b11, 1);
    @(negedge clk);
    loader_done_valid = 0;
    offer(0, 8, 4);
    offer(1, 10, 5);
    step(2'b00, 2'b00, 2'b11, 0);

    // Different input cycles can make two writes to the same cluster ready
    // together. The fabric must see at most one write in either case.
    @(negedge clk);
    load_valid = 0;
    step(2'b11, 2'b01, 2'b01, 0);
    check_write(0, 8, 4);
    @(negedge clk);
    step(2'b10, 2'b10, 2'b11, 0);
    check_write(1, 10, 5);

    @(negedge clk);
    write_ready = 0;
    offer(1, 13, 6);
    step(2'b00, 2'b00, 2'b11, 0);
    @(negedge clk);
    load_valid = 0;
    rst_n = 0;
    step(2'b00, 2'b00, 2'b00, 0);
    @(negedge clk);
    rst_n = 1;
    write_ready = '1;
    step(2'b00, 2'b00, 2'b11, 0);
    if (accepted_writes != 5) $fatal(1, "WEIGHT_BUFFER_WRITE_COUNT");
    $display("WEIGHT_BUFFER_PASS writes=%0d independent=1 cluster_collision=1 completion=1 flush=1",
             accepted_writes);
    $finish;
  end
  initial begin
    #5us;
    $fatal(1, "WEIGHT_BUFFER_TIMEOUT");
  end
endmodule
