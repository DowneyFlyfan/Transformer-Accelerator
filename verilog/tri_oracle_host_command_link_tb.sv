`timescale 1ns/1ps

module tri_oracle_host_command_link_tb;
  logic clk = 0, rst_n = 0;
  always #5 clk = ~clk;

  logic rx_valid = 0, rx_ready, rx_is_payload = 0, rx_payload_last = 0;
  logic [15:0] rx_data = 0;
  logic tx_valid, tx_ready = 0, tx_last;
  logic [15:0] tx_data;
  logic command_valid, command_ready, payload_valid, payload_ready, payload_last;
  logic response_valid, response_ready, response_error;
  logic [2:0] command_opcode, response_opcode;
  logic [31:0] command_tag, response_tag, layer_command_tag;
  logic [63:0] payload_data;
  logic [7:0] layer_command_valid, layer_command_ready = 0;
  logic [7:0] layer_done_valid = 0, layer_done_ready, layer_done_error = 0;
  logic [255:0] layer_done_tag = 0;
  logic [1663:0] layer_command_payload;
  logic layer_feedforward_indexed;
  int successful = 0, rejected = 0;
  int received_flits = 0, sent_flits = 0;

  tri_oracle_host_command_link adapter (.*);
  tri_oracle_indexed_chip_dispatch dispatcher (.*);

  always @(posedge clk) begin
    if (rst_n && rx_valid && rx_ready) received_flits++;
    if (rst_n && tx_valid && tx_ready) sent_flits++;
  end

  function automatic logic [63:0] test_word(input int index, input logic [31:0] tag);
    return 64'h84f9_f07e_1234_568a ^ (64'(index) << 27) ^ {tag, ~tag};
  endfunction

  task automatic receive_flit(input logic [15:0] data, input logic kind, input logic last_payload);
    int cycles = 0;
    rx_valid = 1;
    rx_data = data;
    rx_is_payload = kind;
    rx_payload_last = last_payload;
    do begin
      @(posedge clk);
      cycles++;
      if (cycles > 24) $fatal(1, "Command link did not accept flit");
    end while (!rx_ready);
    @(negedge clk);
    rx_valid = 0;
  endtask

  task automatic header(input logic [2:0] opcode, input logic [31:0] tag);
    receive_flit(tag[15:0], 0, 0);
    receive_flit(tag[31:16], 1, 1);
    receive_flit({13'd0, opcode}, 1, 1);
  endtask

  task automatic word(input logic [63:0] data, input logic last_word, input logic wait_first);
    if (wait_first) repeat (2) @(negedge clk);
    receive_flit(data[15:0], 1, last_word);
    receive_flit(data[31:16], 0, !last_word);
    receive_flit(data[47:32], 0, !last_word);
    receive_flit(data[63:48], 0, !last_word);
  endtask

  task automatic read_response(input logic [2:0] opcode, input logic [31:0] tag,
                               input logic expected_error, input logic [7:0] owner);
    logic [47:0] expected;
    int cycles = 0;
    expected = {12'd0, expected_error, opcode, tag};
    while (!tx_valid) begin
      @(negedge clk);
      if (++cycles > 24) $fatal(1, "No framed response");
    end
    for (int flit = 0; flit < 3; flit++) begin
      repeat (2) begin
        @(posedge clk);
        if ({tx_valid,tx_last,tx_data} !== {1'b1,flit==2,expected[flit*16+:16]})
          $fatal(1, "Corrupt or unstable response flit %0d", flit);
        if (layer_done_ready != 0 || command_ready)
          $fatal(1, "Dispatcher released the command before the final response flit");
        @(negedge clk);
      end
      tx_ready = 1;
      @(posedge clk);
      if (layer_done_ready !== (flit==2 ? owner : 8'b0))
        $fatal(1, "Wrong completion owner or release cycle");
      @(negedge clk);
      tx_ready = 0;
    end
    layer_done_valid = 0;
    layer_done_error = 0;
    if (tx_valid !== 0 || command_ready !== 1) $fatal(1, "Dispatcher did not return to idle");
  endtask

  task automatic send_payload(input int words, input logic [31:0] tag, input logic terminate);
    for (int n = 0; n < words; n++) begin
      if (layer_command_valid !== 0) $fatal(1, "Command issued before its payload completed");
      word(test_word(n,tag), terminate && n==words-1, n%3==1);
    end
  endtask

  task automatic issue(input logic [2:0] opcode, input logic [31:0] tag,
                       input int words, input logic indexed,
                       input logic incorrect_tag, input logic completion_error);
    logic [7:0] owner;
    int cycles = 0;
    owner = 8'b1<<opcode;
    while (layer_command_valid==0) begin
      @(negedge clk);
      if (++cycles>24) $fatal(1, "No mapped command issue");
    end
    layer_command_ready = ~owner;
    repeat (3) begin
      @(posedge clk);
      if (layer_command_valid !== owner || layer_command_tag !== tag ||
          layer_feedforward_indexed !== indexed)
        $fatal(1, "Mapped dispatch changed opcode, tag or format under stall");
      for (int n = 0; n < words; n++)
        if (layer_command_payload[64*n+:64] !== test_word(n,tag))
          $fatal(1, "Mapped dispatch payload mismatch at word %0d", n);
      @(negedge clk);
    end
    layer_command_ready = owner;
    @(negedge clk);
    layer_command_ready = 0;
    layer_done_valid = ~owner;
    repeat (2) begin
      @(negedge clk);
      if (tx_valid !== 0 || layer_done_ready !== 0) $fatal(1, "Accepted a non-owner response");
    end
    layer_done_valid = owner;
    layer_done_tag[32*int'(opcode)+:32] = incorrect_tag ? ~tag : tag;
    layer_done_error = completion_error ? owner : 0;
  endtask

  task automatic valid_case(input logic [2:0] opcode, input int words,
                            input logic [31:0] tag, input logic indexed,
                            input logic incorrect_tag, input logic completion_error);
    header(opcode,tag);
    send_payload(words,tag,!indexed);
    if (indexed) word(64'h1,1,1);
    issue(opcode,tag,words,indexed,incorrect_tag,completion_error);
    read_response(opcode,tag,incorrect_tag||completion_error,8'b1<<opcode);
    successful++;
  endtask

  task automatic malformed_case(input int base_words, input logic [63:0] format_word,
                                input logic format_last, input logic [31:0] tag);
    header(0,tag);
    send_payload(base_words,tag,base_words<15);
    if (base_words==15) begin
      word(format_word,format_last,0);
      if (!format_last) word(64'h1,1,1);
    end
    read_response(0,tag,1,0);
    if (layer_command_valid!==0 || layer_feedforward_indexed!==0)
      $fatal(1, "Malformed command reached the layer");
    rejected++;
  endtask

  initial begin
    int lengths[8] = '{15,9,1,1,3,3,5,26};
    repeat (3) @(negedge clk);
    rst_n = 1;
    for (int op = 0; op < 8; op++)
      valid_case(3'(op),lengths[op],32'h7687_a100+32'(op),0,op==4,op==5);

    valid_case(0,15,32'h7687_a109,1,0,0);
    malformed_case(14,0,0,32'h7687_b001);
    malformed_case(15,64'h0100_0000_0000_0001,1,32'h7687_b002);
    malformed_case(15,64'h1,0,32'h7687_b003);

    // Queue the next header while the old completion is still at the link.
    header(2,32'h7687_b004);
    send_payload(1,32'h7687_b004,1);
    issue(2,32'h7687_b004,1,0,0,0);
    header(3,32'h7687_b005);
    repeat (2) begin
      @(posedge clk);
      if (rx_ready || !command_valid || command_ready ||
          command_tag!==32'h7687_b005) $fatal(1, "Stalled command header was not held");
      @(negedge clk);
    end
    read_response(2,32'h7687_b004,0,8'h04);
    send_payload(1,32'h7687_b005,1);
    issue(3,32'h7687_b005,1,0,0,0);
    read_response(3,32'h7687_b005,0,8'h08);
    successful += 2;

    receive_flit(16'hdead,0,0);
    receive_flit(16'hbeef,0,0);
    rst_n = 0;
    repeat (2) @(negedge clk);
    rst_n = 1;
    valid_case(6,5,32'h7687_c101,0,0,0);
    if (successful!=12 || rejected!=3 || sent_flits!=45)
      $fatal(1, "Missing protocol cases");
    $display("TRI_ORACLE_HOST_COMMAND_LINK_PASS valid=%0d malformed=%0d rx=%0d tx=%0d",
             successful,rejected,received_flits,sent_flits);
    $finish;
  end

  initial begin
    #40000;
    $fatal(1, "Host command link watchdog");
  end
endmodule
