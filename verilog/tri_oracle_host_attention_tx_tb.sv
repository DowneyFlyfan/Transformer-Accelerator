`timescale 1ns/1ps

module tri_oracle_host_attention_tx_tb;
  bit clk = 0, rst_n = 0;
  always #5 clk = !clk;
  logic tx_valid, tx_ready = 0, tx_last;
  logic [15:0] tx_data;
  logic link_valid, link_ready, link_last;
  logic [15:0] link_data;
  logic response_valid = 0, response_ready, response_error = 0;
  logic [2:0] response_opcode = 0;
  logic [31:0] response_tag = 0;
  logic [2047:0] result_values;
  int accepted, words, held;

  tri_oracle_host_attention_tx dut (.*);
  tri_oracle_host_command_link host_link (
    .clk, .rst_n, .rx_valid(1'b0), .rx_ready(), .rx_is_payload(1'b0), .rx_payload_last(1'b0), .rx_data(16'd0),
    .tx_valid(link_valid), .tx_ready(link_ready), .tx_last(link_last), .tx_data(link_data),
    .command_valid(), .command_ready(1'b0), .command_opcode(), .command_tag(),
    .payload_valid(), .payload_ready(1'b0), .payload_data(), .payload_last(),
    .response_valid, .response_ready, .response_error, .response_opcode, .response_tag
  );
  always @(posedge clk) if (rst_n && response_valid && response_ready) accepted++;

  task automatic word(input logic [15:0] wanted, input bit last, input int stalls);
    // Delay ready after valid explicitly so a stalled word must remain stable.
    do @(posedge clk); while (!tx_valid);
    repeat (stalls) begin
      if ({tx_valid, tx_last, tx_data, response_ready} !== {1'b1, last, wanted, 1'b0})
        $fatal(1, "ATTENTION_TX_STALL expected=%h last=%b actual=%h last=%b", wanted, last, tx_data, tx_last);
      held++;
      @(posedge clk);
    end
    @(negedge clk);
    tx_ready = 1;
    @(posedge clk);
    if ({tx_valid, tx_last, tx_data, response_ready} !== {1'b1, last, wanted, last})
      $fatal(1, "ATTENTION_TX_WORD expected=%h last=%b actual=%h last=%b ready=%b", wanted, last, tx_data, tx_last, response_ready);
    words++;
    @(negedge clk);
    tx_ready = 0;
  endtask

  task automatic status(input logic [31:0] tag, input logic [2:0] op, input bit error);
    response_valid = 1;
    response_tag = tag;
    response_opcode = op;
    response_error = error;
    word(tag[15:0], 0, 1);
    word(tag[31:16], 0, 0);
    word({12'd0, error, op}, op != 5 || error, 2);
  endtask

  initial begin
    repeat (3) @(negedge clk);
    rst_n = 1;
    status(32'h95000005, 1, 0);
    status(32'h94000000, 5, 1);
    for (int vector = 0; vector < 2; vector++) begin
      for (int index = 0; index < 128; index++)
        result_values[index * 16 +: 16] = 16'(vector * 20039 + index * 313);
      status(32'h96000000 + 32'(vector), 5, 0);
      for (int index = 0; index < 128; index++)
        word(16'(vector * 20039 + index * 313), index == 127, (index % 7 == 0) ? 2 : 0);
    end
    // Reset a partially transmitted result and start another ordinary status.
    status(32'h96000002, 5, 0);
    word(result_values[15:0], 0, 0);
    rst_n = 0;
    response_valid = 0;
    repeat (2) @(negedge clk);
    if (tx_valid || link_ready || tx_last) $fatal(1, "ATTENTION_TX_RESET");
    rst_n = 1;
    status(32'h97000000, 3, 0);
    response_valid = 0;
    if (accepted != 5 || words != 275 || held != 94)
      $fatal(1, "ATTENTION_TX_INVENTORY completed=%0d words=%0d held=%0d", accepted, words, held);
    $display("HOST_ATTENTION_TX_PASS completed=%0d words=%0d held=%0d", accepted, words, held);
    $finish;
  end

  initial begin
    #25000;
    $fatal(1, "HOST_ATTENTION_TX_TIMEOUT");
  end
endmodule
