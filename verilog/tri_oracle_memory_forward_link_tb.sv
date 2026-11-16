`timescale 1ns/1ps

module tri_oracle_memory_forward_link_tb;
  typedef struct packed {logic [63:0] address; logic [4:0] length;} write_request_t;
  typedef struct packed {logic [63:0] data; logic [7:0] mask; logic last;} write_word_t;
  typedef struct packed {logic [63:0] address; logic [5:0] length; logic wide;} read_request_t;

  bit clk = 0, rst_n = 0;
  always #5 clk = !clk;
  logic [2:0] req_valid = '0, req_ready, peer_req_valid, peer_req_ready;
  logic [2:0][63:0] req_address = '0, peer_req_address;
  logic [2:0][5:0] req_length = '0, peer_req_length;
  logic primary_wide = 1, peer_wide;
  logic write_valid = 0, write_ready, word_valid = 0, word_ready;
  logic [63:0] write_address = '0, write_data = '0;
  logic [4:0] write_length = '0;
  logic [7:0] write_strobe = '0;
  logic write_last = 0;
  logic peer_write_valid, peer_write_ready, peer_word_valid, peer_word_ready;
  logic [63:0] peer_write_address, peer_write_data;
  logic [4:0] peer_write_length;
  logic [7:0] peer_write_strobe;
  logic peer_write_last;
  logic rd_valid, rd_ready, tx_valid, tx_ready, rx_ready;
  logic [21:0] rd_data, tx_data;
  bit run_stalls = 0, wire_open = 1;
  int tick, read_issued, read_received, headers_issued, headers_received, words_issued, words_received;
  int read_during_write, blocked_flits, pending_words;
  bit was_blocked;
  logic [21:0] held_flit;
  read_request_t read_expected [36];
  int read_lane [36];
  write_request_t header_expected [6];
  write_word_t word_expected [32];

  tri_oracle_memory_request_tx read_tx (
    .clk, .rst_n, .req_valid, .req_ready, .req_address, .req_length, .primary_wide,
    .tx_valid(rd_valid), .tx_ready(rd_ready), .tx_data(rd_data)
  );
  tri_oracle_memory_write_link_tx link_tx (
    .clk, .rst_n, .rd_valid, .rd_ready, .rd_data, .write_valid, .write_ready,
    .write_address, .write_length, .word_valid, .word_ready,
    .write_data, .write_strobe, .write_last, .tx_valid, .tx_ready, .tx_data
  );
  tri_oracle_memory_forward_rx link_rx (
    .clk, .rst_n, .rx_valid(tx_valid && wire_open), .rx_ready, .rx_data(tx_data),
    .req_valid(peer_req_valid), .req_ready(peer_req_ready), .req_address(peer_req_address),
    .req_length(peer_req_length), .req_wide(peer_wide), .write_valid(peer_write_valid),
    .write_ready(peer_write_ready), .write_address(peer_write_address), .write_length(peer_write_length),
    .word_valid(peer_word_valid), .word_ready(peer_word_ready), .write_data(peer_write_data),
    .write_strobe(peer_write_strobe), .write_last(peer_write_last)
  );
  assign tx_ready = rx_ready && wire_open;
  assign peer_req_ready = run_stalls ? 3'(tick % 8) : 3'b111;
  assign peer_write_ready = !run_stalls || tick % 9 > 4;
  assign peer_word_ready = !run_stalls || tick % 11 > 5;
  always @(negedge clk) if (run_stalls) wire_open = tick % 7 < 5;

  always @(posedge clk) begin
    if (!rst_n) begin
      was_blocked = 0;
      pending_words = 0;
    end else begin
      tick <= tick + 1;
      if (was_blocked && (!tx_valid || tx_data !== held_flit)) $fatal(1, "FORWARD_FLIT_CHANGED");
      was_blocked = tx_valid && !tx_ready;
      held_flit = tx_data;
      if (was_blocked) blocked_flits++;

      for (int lane = 0; lane < 3; lane++) if (req_valid[lane] && req_ready[lane]) begin
        read_expected[read_issued] = {req_address[lane], req_length[lane],
                                     lane == 1 || (lane == 0 && primary_wide)};
        read_lane[read_issued] = lane;
        read_issued++;
      end
      if (write_valid && write_ready) begin
        header_expected[headers_issued] = {write_address, write_length};
        headers_issued++;
      end
      if (word_valid && word_ready) begin
        word_expected[words_issued] = {write_data, write_strobe, write_last};
        words_issued++;
      end
      if (!$onehot0({(|peer_req_valid), peer_write_valid, peer_word_valid}))
        $fatal(1, "MULTIPLE_FORWARD_DESTINATIONS");
      for (int lane = 0; lane < 3; lane++) if (peer_req_valid[lane] && peer_req_ready[lane]) begin
        if (read_received >= read_issued || read_lane[read_received] != lane ||
            {peer_req_address[lane], peer_req_length[lane], peer_wide} !== read_expected[read_received])
          $fatal(1, "READ_PACKET_CHANGED lane=%0d", lane);
        if (pending_words > 0) read_during_write++;
        read_received++;
      end
      if (peer_write_valid && peer_write_ready) begin
        if (headers_received >= headers_issued || pending_words != 0 ||
            {peer_write_address, peer_write_length} !== header_expected[headers_received])
          $fatal(1, "WRITE_HEADER_CHANGED");
        pending_words = int'(peer_write_length);
        headers_received++;
      end
      if (peer_word_valid && peer_word_ready) begin
        if (words_received >= words_issued || pending_words == 0 ||
            {peer_write_data, peer_write_strobe, peer_write_last} !== word_expected[words_received] ||
            peer_write_last !== (pending_words == 1))
          $fatal(1, "WRITE_WORD_CHANGED");
        pending_words--;
        words_received++;
      end
    end
  end

  initial begin
    repeat (2) @(negedge clk);
    rst_n = 1;
    write_address = 64'h79;
    write_length = 5'd1;
    write_valid = 1;
    @(negedge clk);
    rst_n = 0;
    write_valid = 0;
    repeat (2) @(negedge clk);
    rst_n = 1;
    repeat (2) @(negedge clk);
    if (peer_write_valid || peer_word_valid || peer_req_valid || tx_valid || headers_issued != 0)
      $fatal(1, "PARTIAL_WRITE_SURVIVED_RESET");

    run_stalls = 1;
    fork
      begin
        for (int index = 0; index < 36; index++) begin
          int lane;
          lane = index % 3;
          @(negedge clk);
          req_address[lane] = 64'h90000000 + 64'(index * 64 + (index % 5 == 0 ? 1 : 0));
          req_length[lane] = 6'(index % 18 + 1);
          primary_wide = index % 2 == 0;
          req_valid[lane] = 1;
          do @(posedge clk); while (!req_ready[lane]);
          @(negedge clk);
          req_valid[lane] = 0;
        end
      end
      begin
        for (int burst = 0; burst < 6; burst++) begin
          @(negedge clk);
          write_address = 64'hf000000000001203 + 64'(burst * 8);
          write_length = 5'(burst + 1);
          write_valid = 1;
          do @(posedge clk); while (!write_ready);
          @(negedge clk);
          write_valid = 0;
          for (int beat = 0; beat <= burst; beat++) begin
            write_data = 64'hcafebabe08040201 ^ (64'(burst) << 40) ^ 64'(beat);
            write_strobe = 8'(beat * 29);
            write_last = beat == burst;
            word_valid = 1;
            do @(posedge clk); while (!word_ready);
            @(negedge clk);
            word_valid = 0;
          end
        end
      end
    join
    wait (read_received == 36 && headers_received == 6 && words_received == 21 && pending_words == 0);
    if (blocked_flits == 0 || read_during_write == 0)
      $fatal(1, "INSUFFICIENT_FORWARD_COVERAGE");
    $display("MEMORY_FORWARD_LINK_PASS reads=%0d headers=%0d words=%0d overlap=%0d stalled_flits=%0d",
             read_received, headers_received, words_received, read_during_write, blocked_flits);
    $finish;
  end

  initial begin
    #50000;
    $fatal(1, "MEMORY_FORWARD_LINK_TIMEOUT");
  end
endmodule
