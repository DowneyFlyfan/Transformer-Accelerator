`timescale 1ns/1ps

module tri_oracle_shared_read_link_tb;
  bit clk = 0, rst_n = 0;
  always #5 clk = !clk;

  logic [2:0] req_valid = '0, req_ready;
  logic [2:0][63:0] req_address;
  logic [2:0][5:0] req_length;
  logic primary_wide = 1;
  logic [2:0] rsp_valid, rsp_ready = '0, rsp_last, rsp_error;
  logic [1087:0] rsp_data;
  logic tx_valid, tx_ready, remote_ready;
  logic [21:0] tx_data;
  bit link_open = 1;
  logic [2:0] remote_valid;
  logic [2:0][63:0] remote_address;
  logic [2:0][5:0] remote_length;
  logic remote_wide;
  logic [1:0] mem_rsp_valid = '0, mem_rsp_ready, mem_rsp_last = '0, mem_rsp_error = '0;
  logic [1:0][511:0] mem_rsp_data = '0;
  int requests, responses, faults, terminal_stalls, simultaneous_responses;

  tri_oracle_shared_read_link dut (.*);
  tri_oracle_memory_request_rx peer (
    .clk, .rst_n, .rx_valid(tx_valid && link_open), .rx_ready(remote_ready), .rx_data(tx_data),
    .req_valid(remote_valid), .req_ready(3'b111), .req_address(remote_address),
    .req_length(remote_length), .req_wide(remote_wide)
  );
  assign tx_ready = link_open && remote_ready;

  always @(posedge clk) if (rst_n) begin
    if (rsp_valid[0] && rsp_valid[2]) $fatal(1, "MULTIPLE_OWNERS_OF_PRIMARY_LANE");
    if (req_ready !== remote_valid) $fatal(1, "SERIAL_REQUEST_HANDSHAKE_MISMATCH");
    requests += $countones(req_valid & req_ready);
    responses += $countones(rsp_valid & rsp_ready);
    faults += $countones(rsp_valid & rsp_ready & rsp_error);
    terminal_stalls += $countones(mem_rsp_valid & mem_rsp_last & ~mem_rsp_ready);
    if (&(mem_rsp_valid & mem_rsp_ready)) simultaneous_responses++;
  end

  task automatic offer_request(input int port_id, input logic [63:0] address, input logic [5:0] length,
                               input bit wide);
    req_address[port_id] = address;
    req_length[port_id] = length;
    if (port_id == 0) primary_wide = wide;
    req_valid[port_id] = 1;
  endtask

  task automatic accept_request(input int port_id, input bit wide);
    do @(posedge clk); while (! (|remote_valid));
    if (remote_valid !== (3'b001 << port_id) || remote_wide !== wide ||
        remote_address[port_id] !== req_address[port_id] || remote_length[port_id] !== req_length[port_id])
      $fatal(1, "REMOTE_REQUEST_MISMATCH port=%0d actual=%b", port_id, remote_valid);
    @(negedge clk);
    req_valid[port_id] = 0;
  endtask

  task automatic offer_beat(input int bus_lane, tag, input bit last, fault);
    for (int word = 0; word < 8; word++)
      mem_rsp_data[bus_lane][word*64 +: 64] = 64'h98765432fedc0000 | (64'(tag) << 4) | 64'(word);
    mem_rsp_valid[bus_lane] = 1;
    mem_rsp_last[bus_lane] = last;
    mem_rsp_error[bus_lane] = fault;
  endtask

  task automatic check_response(input int port_id, bus_lane, input bit ready);
    logic [511:0] actual;
    actual = port_id == 2 ? {448'b0, rsp_data[1087:1024]} : rsp_data[port_id*512 +: 512];
    if (rsp_valid[port_id] !== 1'b1 || mem_rsp_ready[bus_lane] !== ready ||
        rsp_last[port_id] !== mem_rsp_last[bus_lane] || rsp_error[port_id] !== mem_rsp_error[bus_lane] ||
        actual !== (port_id == 2 ? {448'b0, mem_rsp_data[bus_lane][63:0]} : mem_rsp_data[bus_lane]))
      $fatal(1, "LOGICAL_RESPONSE_MISMATCH port=%0d ready=%b", port_id, ready);
  endtask

  initial begin
    req_address = '0;
    req_length = '0;
    repeat (2) @(negedge clk);
    rst_n = 1;
    rsp_ready = '1;
    offer_beat(0, 1, 0, 0);
    offer_beat(1, 2, 0, 0);
    @(posedge clk);
    if (rsp_valid || mem_rsp_ready) $fatal(1, "IDLE_RESPONSE_ESCAPED");
    @(negedge clk);
    mem_rsp_valid = '0;

    link_open = 0;
    offer_request(2, 64'h400008, 6'd2, 0);
    repeat (2) @(negedge clk);
    offer_request(0, 64'h600000, 6'd2, 1);
    offer_request(1, 64'h800000, 6'd1, 1);
    repeat (2) @(negedge clk);
    link_open = 1;
    accept_request(2, 0);
    accept_request(1, 1);
    offer_beat(0, 3, 0, 0);
    offer_beat(1, 4, 1, 1);
    @(posedge clk);
    check_response(2, 0, 1);
    check_response(1, 1, 1);
    @(negedge clk);
    mem_rsp_valid[1] = 0;
    offer_beat(0, 5, 1, 1);
    rsp_ready[2] = 0;
    offer_request(1, 64'ha00000, 6'd1, 1);
    accept_request(1, 1);
    offer_beat(1, 6, 1, 0);
    @(posedge clk);
    check_response(2, 0, 0);
    check_response(1, 1, 1);
    if (remote_valid[0] || req_ready[0]) $fatal(1, "STALLED_TAIL_RELEASED_OWNER");
    @(negedge clk);
    mem_rsp_valid[1] = 0;
    rsp_ready[2] = 1;
    @(posedge clk);
    check_response(2, 0, 1);
    @(negedge clk);
    mem_rsp_valid[0] = 0;
    accept_request(0, 1);

    offer_request(2, 64'h100008, 6'd1, 0);
    offer_beat(0, 7, 0, 1);
    @(posedge clk);
    check_response(0, 0, 1);
    if (tx_valid) $fatal(1, "NONTERMINAL_ERROR_RELEASED_OWNER");
    @(negedge clk);
    offer_beat(0, 8, 1, 0);
    @(posedge clk);
    check_response(0, 0, 1);
    if (!tx_valid || !tx_ready) $fatal(1, "BUBBLE_AFTER_RESPONSE_TAIL");
    @(negedge clk);
    mem_rsp_valid[0] = 0;
    accept_request(2, 0);
    offer_beat(0, 9, 1, 0);
    @(posedge clk);
    check_response(2, 0, 1);
    @(negedge clk);
    mem_rsp_valid[0] = 0;

    offer_request(0, 64'h500008, 6'd1, 0);
    accept_request(0, 0);
    rsp_ready[0] = 0;
    offer_beat(0, 10, 1, 0);
    @(posedge clk);
    check_response(0, 0, 0);
    @(negedge clk);
    rst_n = 0;
    repeat (2) @(negedge clk);
    rst_n = 1;
    @(posedge clk);
    if (rsp_valid || mem_rsp_ready) $fatal(1, "RESPONSE_OWNER_SURVIVED_RESET");
    @(negedge clk);
    mem_rsp_valid = '0;
    rsp_ready = '1;
    offer_request(0, 64'hf000000000000007, 6'd1, 0);
    accept_request(0, 0);
    offer_beat(0, 11, 1, 0);
    @(posedge clk);
    check_response(0, 0, 1);
    @(negedge clk);
    if (requests != 7 || responses != 8 || faults != 3 || terminal_stalls < 2 || simultaneous_responses != 1)
      $fatal(1, "SHARED_READ_INVENTORY requests=%0d responses=%0d faults=%0d", requests, responses, faults);
    $display("SHARED_READ_LINK_PASS requests=%0d responses=%0d faults=%0d terminal_stalls=%0d simultaneous=%0d",
             requests, responses, faults, terminal_stalls, simultaneous_responses);
    $finish;
  end

  initial begin
    #20000;
    $fatal(1, "SHARED_READ_LINK_TIMEOUT");
  end
endmodule
