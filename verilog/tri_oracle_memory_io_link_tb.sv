`timescale 1ns/1ps

module tri_oracle_memory_io_link_tb;
  bit clk = 0, rst_n = 0;
  always #5 clk = !clk;
  logic [2:0] req_valid = '0, req_ready, rsp_valid, rsp_ready = '1, rsp_last, rsp_error;
  logic [2:0][63:0] req_address = '0;
  logic [2:0][5:0] req_length = {6'd1, 6'd1, 6'd1};
  logic [1087:0] rsp_data;
  logic primary_wide = 1;
  logic wr_req_valid = 0, wr_req_ready, wr_data_valid = 0, wr_data_ready, wr_data_last = 0;
  logic [63:0] wr_address = 64'hfedcba0000000008, wr_data = '0;
  logic [4:0] wr_length = 0;
  logic [7:0] wr_strobe = 8'hb7;
  logic wr_rsp_valid, wr_rsp_ready = 0, wr_rsp_error;
  logic [1:0] mem_rsp_valid = '0, mem_rsp_ready, mem_rsp_last = '1, mem_rsp_error = '0;
  logic [1:0][511:0] mem_rsp_data = '0;
  logic tx_valid, tx_ready, peer_ready;
  logic [21:0] tx_data;
  bit wire_open = 1;
  logic [2:0] peer_req_valid;
  logic [2:0][63:0] peer_req_address;
  logic [2:0][5:0] peer_req_length;
  logic peer_wide, peer_write, peer_word, peer_last;
  logic [63:0] peer_address, peer_data;
  logic [4:0] peer_length;
  logic [7:0] peer_strobe;
  int reads, writes, words, acknowledgments, failed_writes, stalled_ack_cycles, auxiliary_on_ack;

  tri_oracle_memory_io_link dut (.*);
  tri_oracle_memory_forward_rx peer (
    .clk, .rst_n, .rx_valid(tx_valid && wire_open), .rx_ready(peer_ready), .rx_data(tx_data),
    .req_valid(peer_req_valid), .req_ready(3'b111), .req_address(peer_req_address),
    .req_length(peer_req_length), .req_wide(peer_wide), .write_valid(peer_write),
    .write_ready(1'b1), .write_address(peer_address), .write_length(peer_length),
    .word_valid(peer_word), .word_ready(1'b1), .write_data(peer_data),
    .write_strobe(peer_strobe), .write_last(peer_last)
  );
  assign tx_ready = wire_open && peer_ready;

  always @(posedge clk) if (rst_n) begin
    if ({wr_req_ready, wr_data_ready, req_ready} !== {peer_write, peer_word, peer_req_valid})
      $fatal(1, "MEMORY_IO_HANDSHAKE_MISMATCH");
    if (wr_rsp_valid && (rsp_valid[0] || rsp_valid[2] || peer_req_valid[0] || peer_req_valid[2]))
      $fatal(1, "ACKNOWLEDGMENT_READ_COLLISION");
    reads += $countones(req_ready & req_valid);
    if (wr_req_valid && wr_req_ready) writes++;
    if (wr_data_valid && wr_data_ready) words++;
    if (wr_rsp_valid && !wr_rsp_ready) stalled_ack_cycles++;
    if (wr_rsp_valid && rsp_valid[1] && rsp_ready[1]) auxiliary_on_ack++;
    if (wr_rsp_valid && wr_rsp_ready) begin
      acknowledgments++;
      if (wr_rsp_error) failed_writes++;
    end
  end

  task automatic offer_read(input int lane);
    req_valid[lane] = 1;
    req_address[lane] = 64'h2000000 + 64'(lane * 64);
  endtask

  task automatic accept_read(input int lane);
    do @(posedge clk); while (!(|peer_req_valid));
    if (peer_req_valid !== (3'b001 << lane) || peer_req_address[lane] !== req_address[lane] ||
        peer_req_length[lane] != 1 || peer_wide !== (lane != 2))
      $fatal(1, "MEMORY_IO_READ_DECODE");
    @(negedge clk);
    req_valid[lane] = 0;
  endtask

  task automatic accept_write(input logic [4:0] beats);
    do @(posedge clk); while (!peer_write);
    if (peer_address !== wr_address || peer_length !== beats) $fatal(1, "MEMORY_IO_WRITE_DECODE");
    @(negedge clk);
    wr_req_valid = 0;
  endtask

  task automatic send_word(input bit last);
    wr_data_valid = 1;
    wr_data = last ? 64'h0011223344556677 : 64'hfedcba9876543210;
    wr_data_last = last;
    do @(posedge clk); while (!peer_word);
    if ({peer_data, peer_strobe, peer_last} !== {wr_data, wr_strobe, wr_data_last})
      $fatal(1, "MEMORY_IO_WORD_DECODE");
    @(negedge clk);
    wr_data_valid = 0;
  endtask

  task automatic ack(input bit fault, input bit ready);
    mem_rsp_valid[0] = 1;
    mem_rsp_error[0] = fault;
    wr_rsp_ready = ready;
    @(posedge clk);
    if (!wr_rsp_valid || wr_rsp_error !== fault || mem_rsp_ready[0] !== ready)
      $fatal(1, "MEMORY_IO_WRITE_ACK");
    @(negedge clk);
    if (ready) mem_rsp_valid[0] = 0;
  endtask

  initial begin
    repeat (2) @(negedge clk);
    rst_n = 1;
    wire_open = 0;
    offer_read(0);
    repeat (2) @(negedge clk);
    wr_req_valid = 1;
    wr_length = 2;
    offer_read(1);
    wire_open = 1;
    accept_read(0);
    accept_read(1);
    mem_rsp_valid = '1;
    rsp_ready[0] = 0;
    repeat (3) begin
      @(posedge clk);
      if (!rsp_valid[0] || mem_rsp_ready[0] || wr_rsp_valid || peer_write)
        $fatal(1, "WRITE_OVERTOOK_STALLED_READ");
      @(negedge clk);
      mem_rsp_valid[1] = 0;
    end
    rsp_ready[0] = 1;
    @(negedge clk);
    mem_rsp_valid[0] = 0;
    accept_write(2);

    offer_read(2);
    offer_read(1);
    fork
      send_word(0);
      accept_read(1);
    join
    mem_rsp_valid[1] = 1;
    send_word(1);
    mem_rsp_valid[1] = 0;
    ack(0, 0);
    offer_read(1);
    accept_read(1);
    mem_rsp_valid[1] = 1;
    ack(0, 0);
    mem_rsp_valid[1] = 0;
    ack(0, 1);
    accept_read(2);
    mem_rsp_data[0][63:0] = 64'h1234567890abcdef;
    mem_rsp_valid[0] = 1;
    @(posedge clk);
    if (!rsp_valid[2] || rsp_data[1087:1024] !== 64'h1234567890abcdef || wr_rsp_valid)
      $fatal(1, "POST_WRITE_PROJECTION_RESPONSE");
    @(negedge clk);
    mem_rsp_valid[0] = 0;

    wr_length = 0;
    wr_req_valid = 1;
    accept_write(0);
    ack(1, 1);
    wr_length = 1;
    wr_req_valid = 1;
    accept_write(1);
    send_word(1);
    ack(0, 0);
    rst_n = 0;
    repeat (2) @(negedge clk);
    rst_n = 1;
    @(posedge clk);
    if (wr_rsp_valid || (|rsp_valid) || (|mem_rsp_ready))
      $fatal(1, "RESET_LEFT_STALE_WRITE_ACKNOWLEDGMENT");
    if (reads != 5 || writes != 3 || words != 3 || acknowledgments != 2 || failed_writes != 1 ||
        auxiliary_on_ack != 1 || stalled_ack_cycles < 3)
      $fatal(1, "INVALID_MEMORY_IO_COUNTS reads=%0d writes=%0d words=%0d", reads, writes, words);
    $display("MEMORY_IO_LINK_PASS reads=%0d writes=%0d words=%0d acks=%0d failed=%0d stalled=%0d auxiliary_on_ack=%0d",
             reads, writes, words, acknowledgments, failed_writes, stalled_ack_cycles, auxiliary_on_ack);
    $finish;
  end

  initial begin
    #20000;
    $fatal(1, "MEMORY_IO_LINK_TIMEOUT reads=%0d writes=%0d words=%0d acks=%0d", reads, writes, words, acknowledgments);
  end
endmodule
