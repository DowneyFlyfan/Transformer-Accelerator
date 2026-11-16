`timescale 1ns/1ps

module tri_oracle_memory_request_link_tb;
  typedef struct packed {
    logic [63:0] address;
    logic [5:0] length;
  } request_t;

  bit clk = 0;
  bit rst_n = 0;
  always #5 clk = !clk;

  logic [1:0] source_valid, source_ready, memory_valid, memory_ready;
  logic [1:0][63:0] source_address, memory_address;
  logic [1:0][5:0] source_length, memory_length;
  logic tx_valid, tx_ready, rx_ready;
  logic [21:0] tx_data;
  bit link_open = 1, memory_open = 1, add_stalls = 0;

  tri_oracle_memory_request_tx tx (
    .clk, .rst_n, .req_valid(source_valid), .req_ready(source_ready),
    .req_address(source_address), .req_length(source_length),
    .tx_valid, .tx_ready, .tx_data
  );
  tri_oracle_memory_request_rx rx (
    .clk, .rst_n, .rx_valid(tx_valid && link_open), .rx_ready, .rx_data(tx_data),
    .req_valid(memory_valid), .req_ready(memory_ready),
    .req_address(memory_address), .req_length(memory_length)
  );
  assign tx_ready = rx_ready && link_open;

  request_t expected [2][256];
  int issued [2], received [2];
  int tick, packets, compact_packets, full_packets, tx_stalls, output_stalls;
  int offset, first_tick;
  bit last_stalled, output_stalled;
  logic [21:0] held_flit;
  logic [1:0] held_valid;
  logic [1:0][63:0] held_address;
  logic [1:0][5:0] held_length;
  logic [87:0] wire_packet;

  assign memory_ready = memory_open ? (add_stalls ? 2'(tick % 4) : 2'b11) : 2'b00;
  always @(negedge clk) if (add_stalls) link_open = tick % 7 < 5;

  always @(posedge clk) begin
    if (!rst_n) begin
      issued = '{default:0};
      received = '{default:0};
      offset = 0;
      last_stalled = 0;
      output_stalled = 0;
    end else begin
      tick <= tick + 1;
      if (last_stalled && (!tx_valid || tx_data !== held_flit))
        $fatal(1, "STALLED_FLIT_CHANGED");
      if (output_stalled && (memory_valid !== held_valid || memory_address !== held_address ||
                             memory_length !== held_length))
        $fatal(1, "STALLED_REQUEST_CHANGED");
      last_stalled = tx_valid && !tx_ready;
      output_stalled = |memory_valid && !(|(memory_valid & memory_ready));
      held_flit = tx_data;
      held_valid = memory_valid;
      held_address = memory_address;
      held_length = memory_length;
      if (last_stalled) tx_stalls++;
      if (output_stalled) output_stalls++;

      if (tx_valid && tx_ready) begin
        int lane, beats;
        logic [63:0] encoded_address;
        bit compact;
        if (offset == 0) begin
          wire_packet = '0;
          first_tick = tick;
        end
        wire_packet[offset*22 +: 22] = tx_data;
        offset++;
        compact = wire_packet[0];
        lane = int'(wire_packet[1]);
        beats = compact ? 2 : 4;
        if (offset == beats) begin
          encoded_address = compact ? {22'd0, wire_packet[43:8], 6'd0} : wire_packet[71:8];
          if ((source_ready & source_valid) !== (2'b01 << lane) ||
              wire_packet[7:2] !== source_length[lane] || encoded_address !== source_address[lane] ||
              compact !== (source_address[lane][63:42] == '0 && source_address[lane][5:0] == '0) ||
              wire_packet[87:72] !== '0)
            $fatal(1, "WRONG_WIRE_PACKET lane=%0d compact=%0d", lane, compact);
          if (!add_stalls && tick - first_tick + 1 != beats)
            $fatal(1, "ADDED_SERIALIZATION_CYCLE");
          if (!add_stalls && memory_open && memory_valid !== (2'b01 << lane))
            $fatal(1, "ADDED_MEMORY_ISSUE_CYCLE");
          expected[lane][issued[lane]] = {source_address[lane], source_length[lane]};
          issued[lane]++;
          packets++;
          if (compact) compact_packets++;
          else full_packets++;
          offset = 0;
        end else if (|(source_ready & source_valid)) begin
          $fatal(1, "ACKNOWLEDGED_BEFORE_LAST_FLIT");
        end
      end else if (|(source_ready & source_valid)) begin
        $fatal(1, "ACKNOWLEDGED_WITHOUT_FLIT");
      end

      if (!$onehot0(memory_valid)) $fatal(1, "DECODER_SELECTED_MULTIPLE_LANES");
      for (int lane = 0; lane < 2; lane++) begin
        if (memory_valid[lane] && memory_ready[lane]) begin
          if (received[lane] >= issued[lane] ||
              {memory_address[lane], memory_length[lane]} !== expected[lane][received[lane]])
            $fatal(1, "REQUEST_MISMATCH lane=%0d ordinal=%0d", lane, received[lane]);
          received[lane]++;
        end
      end
    end
  end

  task automatic send_request(input int lane, input logic [63:0] address, input logic [5:0] length);
    @(negedge clk);
    source_valid[lane] = 1;
    source_address[lane] = address;
    source_length[lane] = length;
    do @(posedge clk); while (!source_ready[lane]);
    @(negedge clk);
    source_valid[lane] = 0;
  endtask

  task automatic reset_link;
    @(negedge clk);
    rst_n = 0;
    source_valid = '0;
    repeat (2) @(negedge clk);
    rst_n = 1;
  endtask

  initial begin
    source_valid = '0;
    source_address = '0;
    source_length = '0;
    reset_link();
    send_request(0, 64'd0, 6'd1);
    send_request(1, 64'h000003ffffffffc0, 6'd63);
    send_request(0, 64'h0000040000000000, 6'd0);
    send_request(1, 64'h0000000000000001, 6'd32);
    send_request(0, 64'hffffffffffffffff, 6'd63);
    wait (received[0] == 3 && received[1] == 2);

    // Stall lane zero's first flit, introduce lane one, and reset mid-packet.
    @(negedge clk);
    link_open = 0;
    source_valid[0] = 1;
    repeat (2) @(negedge clk);
    source_valid[1] = 1;
    repeat (3) @(negedge clk);
    link_open = 1;
    @(negedge clk);
    reset_link();
    repeat (3) @(negedge clk);
    if (|memory_valid || tx_valid) $fatal(1, "PARTIAL_PACKET_SURVIVED_RESET");

    memory_open = 0;
    send_request(0, 64'h90000000, 6'd2);
    repeat (3) @(negedge clk);
    reset_link();
    memory_open = 1;
    repeat (3) @(negedge clk);
    if (|memory_valid || tx_valid) $fatal(1, "BUFFERED_REQUEST_SURVIVED_RESET");

    add_stalls = 1;
    fork
      begin
        for (int index = 0; index < 120; index++)
          send_request(0, 64'h80000000 + 64'(index * 64 + (index % 3 == 0 ? 1 : 0)), 6'(index));
      end
      begin
        for (int index = 0; index < 120; index++)
          send_request(1, (index % 4 == 0 ? 64'h8000000000000000 : 64'h100000000) | 64'(index * 128),
                       6'(63 - index));
      end
    join
    wait (received[0] == 120 && received[1] == 120);
    if (packets != 246 || compact_packets != 173 || full_packets != 73 ||
        tx_stalls == 0 || output_stalls == 0)
      $fatal(1, "INSUFFICIENT_COVERAGE packets=%0d compact=%0d full=%0d", packets, compact_packets, full_packets);
    $display("MEMORY_REQUEST_LINK_PASS packets=%0d compact=%0d full=%0d flit_stalls=%0d output_stalls=%0d",
             packets, compact_packets, full_packets, tx_stalls, output_stalls);
    $finish;
  end

  initial begin
    #50000;
    $fatal(1, "MEMORY_REQUEST_LINK_TIMEOUT");
  end
endmodule
