`timescale 1ns/1ps

module tri_oracle_chip_dispatch_tb;
  logic clk = 0;
  logic rst_n = 0;
  always #5 clk = ~clk;

  logic command_valid = 0, command_ready;
  logic [2:0] command_opcode = 0;
  logic [31:0] command_tag = 0;
  logic payload_valid = 0, payload_ready, payload_last = 0;
  logic [63:0] payload_data = 0;
  logic response_valid, response_ready = 0, response_error;
  logic [2:0] response_opcode;
  logic [31:0] response_tag;
  logic [5:0] layer_command_valid, layer_command_ready = 0;
  logic [31:0] layer_command_tag;
  logic [959:0] layer_command_payload;
  logic [5:0] layer_done_valid = 0, layer_done_ready, layer_done_error = 0;
  logic [191:0] layer_done_tag = '0;
  int checked = 0;

  tri_oracle_chip_dispatch dut (.*);

  function automatic logic [63:0] word_value(input int index, input logic [31:0] tag);
    return {32'(index), tag ^ 32'h12d3_5ff0};
  endfunction

  task automatic header(input logic [2:0] opcode, input logic [31:0] tag);
    @(negedge clk);
    command_valid = 1;
    command_opcode = opcode;
    command_tag = tag;
    @(posedge clk);
    if (command_ready !== 1'b1) $fatal(1, "Header did not transfer");
    @(negedge clk);
    command_valid = 0;
    command_opcode = '1;
    command_tag = '1;
  endtask

  task automatic word_transfer(input int index, input logic [31:0] tag, input logic last);
    payload_valid = 1;
    payload_data = word_value(index, tag);
    payload_last = last;
    @(posedge clk);
    if (payload_ready !== 1'b1) $fatal(1, "Payload did not transfer");
    @(negedge clk);
    payload_valid = 0;
    payload_data = '1;
    payload_last = 0;
  endtask

  task automatic response(input logic [2:0] opcode, input logic [31:0] tag,
                          input logic error, input logic [5:0] owner);
    repeat (3) begin
      @(posedge clk);
      if ({response_valid, response_opcode, response_tag, response_error}
          !== {1'b1, opcode, tag, error} || layer_done_ready !== 6'b0 ||
          command_ready !== 1'b0) $fatal(1, "Response changed under backpressure");
      @(negedge clk);
    end
    response_ready = 1;
    @(posedge clk);
    if (response_valid !== 1'b1 || layer_done_ready !== owner)
      $fatal(1, "Wrong completion owner");
    @(negedge clk);
    response_ready = 0;
    layer_done_valid = 0;
    layer_done_error = 0;
    @(posedge clk);
    if (response_valid !== 1'b0 || command_ready !== 1'b1)
      $fatal(1, "Did not return to idle after completion");
    checked++;
  endtask

  task automatic valid_command(input logic [2:0] opcode, input int words,
                               input logic [31:0] tag, input logic wrong_tag,
                               input logic operation_error);
    logic [5:0] owner;
    owner = 6'b1 << opcode;
    header(opcode, tag);
    for (int word = 0; word < words; word++) begin
      if (layer_command_valid !== 0) $fatal(1, "Issued before complete payload");
      word_transfer(word, tag, word == words - 1);
    end
    layer_command_ready = ~owner;
    repeat (3) begin
      @(posedge clk);
      if (layer_command_valid !== owner || layer_command_tag !== tag || command_ready !== 1'b0)
        $fatal(1, "Lost stalled command or selected wrong operation");
      for (int word = 0; word < words; word++)
        if (layer_command_payload[word*64 +: 64] !== word_value(word, tag))
          $fatal(1, "Wrong payload word %0d for opcode %0d", word, opcode);
      @(negedge clk);
    end
    layer_command_ready = owner;
    @(posedge clk);
    if (layer_command_valid !== owner) $fatal(1, "Layer command was not issued");
    @(negedge clk);
    layer_command_ready = 0;
    layer_done_valid = ~owner;
    repeat (2) begin
      @(posedge clk);
      if (layer_command_valid !== 0 || response_valid !== 1'b0 || layer_done_ready !== 0)
        $fatal(1, "Accepted a non-owner completion");
      @(negedge clk);
    end
    layer_done_valid = '1;
    layer_done_tag[{opcode, 5'b0} +: 32] = wrong_tag ? ~tag : tag;
    layer_done_error[opcode] = operation_error;
    response(opcode, tag, wrong_tag || operation_error, owner);
  endtask

  initial begin
    repeat (2) @(negedge clk);
    rst_n = 1;
    valid_command(3'd0, 15, 32'h0123_4567, 0, 0);
    valid_command(3'd1, 9, 32'h1123_4567, 0, 0);
    valid_command(3'd2, 1, 32'h2123_4567, 0, 0);
    valid_command(3'd3, 1, 32'h3123_4567, 0, 0);
    valid_command(3'd4, 3, 32'h4123_4567, 1, 0);
    valid_command(3'd5, 3, 32'h5123_4567, 0, 1);

    header(3'd7, 32'h7000_0001);
    response(3'd7, 32'h7000_0001, 1, 6'b0);
    header(3'd0, 32'h7000_0002);
    word_transfer(0, 32'h7000_0002, 1);
    response(3'd0, 32'h7000_0002, 1, 6'b0);
    header(3'd2, 32'h7000_0003);
    word_transfer(0, 32'h7000_0003, 0);
    if (layer_command_valid !== 0) $fatal(1, "Oversized frame issued");
    word_transfer(1, 32'h7000_0003, 0);
    word_transfer(2, 32'h7000_0003, 1);
    response(3'd2, 32'h7000_0003, 1, 6'b0);

    header(3'd0, 32'h7000_0004);
    word_transfer(0, 32'h7000_0004, 0);
    rst_n = 0;
    repeat (2) @(negedge clk);
    rst_n = 1;
    valid_command(3'd5, 3, 32'h7000_0005, 0, 0);
    if (checked != 10) $fatal(1, "Missing dispatch cases");
    $display("TRI_ORACLE_CHIP_DISPATCH_PASS cases=%0d", checked);
    $finish;
  end

  initial begin
    #10000;
    $fatal(1, "Chip dispatch watchdog");
  end
endmodule
