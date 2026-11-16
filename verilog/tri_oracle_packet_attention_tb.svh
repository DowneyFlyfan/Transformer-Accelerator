`timescale 1ns/1ps

module tri_oracle_chip_packet_io_tb;
  localparam int Slots = 409, ImageTokens = 576;
  localparam logic [63:0] CacheBase = 64'h2000000, ContextBase = 64'h30000000;
  localparam logic [63:0] KeyBase = CacheBase + (64'd32 << 16), ValueBase = CacheBase + (64'd36 << 16);
  bit clk = 0, rst_n = 0;
  always #5 clk = !clk;

  logic host_rx_valid = 0, host_rx_ready, host_rx_is_payload = 0, host_rx_payload_last = 0;
  logic [15:0] host_rx_data = '0;
  logic host_tx_valid, host_tx_ready = 0, host_tx_last;
  logic [15:0] host_tx_data;
  logic sign_valid = 0, sign_ready, map_valid, map_last;
  logic [2047:0] sign_data = '0;
  logic [9:0] map_index, map_origin;
  logic head_done_streaming;
  logic [4:0] head_done_id;
  logic [17:0] head_done_inner, head_done_recent;

  logic memory_tx_valid, memory_tx_ready;
  logic [21:0] memory_tx_data;
  logic [1:0] memory_mem_rsp_valid, memory_mem_rsp_ready, memory_mem_rsp_last;
  logic [1023:0] memory_mem_rsp_data;
  logic peer_rx_ready;
  logic [2:0] peer_req_valid, peer_req_ready;
  logic [2:0][63:0] peer_req_address;
  logic [2:0][5:0] peer_req_length;
  logic peer_wide, peer_write_valid, peer_write_ready, peer_word_valid, peer_word_ready;
  logic [63:0] peer_write_address, peer_write_data;
  logic [4:0] peer_write_length;
  logic [7:0] peer_write_strobe;
  logic peer_write_last;

  logic [2047:0] signs[ImageTokens];
  logic [9:0] golden_map[ImageTokens];
  logic [319:0] packed_map[18];
  logic [511:0] projected_cache[40 * Slots];
  logic [1:0][63:0] read_address;
  bit [1:0] reading = 0, reading_wide = 0;
  int read_remaining[2], write_limb, ack_delay = 0;
  bit writing = 0;
  int cycles, maps, reads, value_reads, wide_reads, auxiliary_reads;
  int context_bursts, context_words, context_acks, host_words;
  string fixture, dump;

  // CHIP_INSTANCE

  tri_oracle_memory_forward_rx peer (
    .clk, .rst_n, .rx_valid(memory_tx_valid && cycles % 13 != 0),
    .rx_ready(peer_rx_ready), .rx_data(memory_tx_data),
    .req_valid(peer_req_valid), .req_ready(peer_req_ready), .req_address(peer_req_address),
    .req_length(peer_req_length), .req_wide(peer_wide),
    .write_valid(peer_write_valid), .write_ready(peer_write_ready), .write_address(peer_write_address),
    .write_length(peer_write_length), .word_valid(peer_word_valid), .word_ready(peer_word_ready),
    .write_data(peer_write_data), .write_strobe(peer_write_strobe), .write_last(peer_write_last)
  );

  function automatic logic [511:0] read_response(input logic [63:0] address, input bit wide);
    int slot, start_bit;
    slot = int'(address[15:6]);
    start_bit = int'(address[5:3]) * 64;
    if (address >= ValueBase) slot += 36 * Slots;
    else if (address >= KeyBase) slot += 32 * Slots;
    if (wide) return projected_cache[slot];
    return {448'd0, projected_cache[slot][start_bit +: 64]};
  endfunction

  assign memory_tx_ready = peer_rx_ready && cycles % 13 != 0;
  assign peer_req_ready = {1'b0, !reading[1] && cycles % 5 != 1,
                           !reading[0] && !writing && ack_delay == 0 && cycles % 5 != 0};
  assign peer_write_ready = !reading[0] && !writing && ack_delay == 0 && cycles % 7 != 0;
  assign peer_word_ready = writing && cycles % 9 != 0;
  assign memory_mem_rsp_valid = {reading[1], reading[0] || ack_delay == 1};
  assign memory_mem_rsp_last = {reading[1] && read_remaining[1] == 1,
                               reading[0] ? read_remaining[0] == 1 : ack_delay == 1};
  for (genvar lane = 0; lane < 2; lane++) begin : response_lane
    assign memory_mem_rsp_data[lane * 512 +: 512] = reading[lane] ?
        read_response(read_address[lane], reading_wide[lane]) : '0;
  end

  always @(posedge clk) if (rst_n) begin
    cycles <= cycles + 1;
    if (map_valid) begin
      if (maps >= ImageTokens || map_index !== 10'(maps) || map_origin !== golden_map[maps] ||
          map_last !== (maps == ImageTokens - 1)) $fatal(1, "PACKET_ATTENTION_MAP index=%0d", maps);
      maps++;
    end
    if (peer_req_valid[2]) $fatal(1, "PACKET_ATTENTION_UNEXPECTED_PROJECTION_PORT");
    for (int lane = 0; lane < 2; lane++) begin
      if (peer_req_valid[lane] && peer_req_ready[lane]) begin
        logic [63:0] address, limit;
        int bytes_per_beat;
        address = peer_req_address[lane];
        limit = (address >= ValueBase ? ValueBase : address >= KeyBase ? KeyBase : CacheBase) + Slots * 64;
        bytes_per_beat = peer_wide ? 64 : 8;
        if (peer_req_length[lane] == 0 || address < CacheBase || address % 64'(bytes_per_beat) != 0 ||
            address + 64'(bytes_per_beat) * 64'(peer_req_length[lane]) > limit)
          $fatal(1, "PACKET_ATTENTION_READ lane=%0d addr=%h len=%0d wide=%b", lane, address, peer_req_length[lane], peer_wide);
        if (address >= ValueBase) begin
          if (address[5:0] != 0 || bytes_per_beat * int'(peer_req_length[lane]) != 64)
            $fatal(1, "PACKET_ATTENTION_VALUE_BURST");
          value_reads++;
        end
        read_address[lane] <= address;
        read_remaining[lane] <= int'(peer_req_length[lane]);
        reading[lane] <= 1;
        reading_wide[lane] <= peer_wide;
        reads++;
        if (peer_wide) wide_reads++;
        if (lane == 1) auxiliary_reads++;
      end else if (reading[lane] && memory_mem_rsp_ready[lane]) begin
        read_address[lane] <= read_address[lane] + (reading_wide[lane] ? 64'd64 : 64'd8);
        read_remaining[lane] <= read_remaining[lane] - 1;
        reading[lane] <= read_remaining[lane] != 1;
      end
    end
    if (peer_write_valid && peer_write_ready) begin
      if (context_bursts >= 18 || peer_write_address !== ContextBase + 64'(context_bursts * 40) ||
          peer_write_length != 5) $fatal(1, "PACKET_ATTENTION_CONTEXT_BURST");
      context_bursts++;
      write_limb <= 0;
      writing <= 1;
    end
    if (peer_word_valid && peer_word_ready) begin
      if (peer_write_strobe !== 8'hff || peer_write_last !== (write_limb == 4) ||
          peer_write_data !== packed_map[context_bursts - 1][write_limb * 64 +: 64])
        $fatal(1, "PACKET_ATTENTION_CONTEXT_DATA burst=%0d word=%0d", context_bursts, write_limb);
      context_words++;
      if (peer_write_last) begin
        writing <= 0;
        ack_delay <= 4;
      end else write_limb <= write_limb + 1;
    end
    if (ack_delay > 1) ack_delay <= ack_delay - 1;
    if (ack_delay == 1 && memory_mem_rsp_ready[0]) begin
      context_acks++;
      ack_delay <= 0;
    end
  end

  task automatic flit(input logic [15:0] value, input bit payload, final_payload);
    host_rx_valid = 1;
    host_rx_data = value;
    host_rx_is_payload = payload;
    host_rx_payload_last = final_payload;
    do @(posedge clk); while (!host_rx_ready);
    @(negedge clk);
    host_rx_valid = 0;
  endtask

  task automatic command(input logic [2:0] opcode, input logic [31:0] tag,
                         input int words, input logic [191:0] descriptor);
    flit(tag[15:0], 0, 0);
    flit(tag[31:16], 0, 0);
    flit({13'd0, opcode}, 0, 0);
    for (int word = 0; word < words; word++) begin
      flit(descriptor[word * 64 +: 16], 1, word == words - 1);
      for (int part = 1; part < 4; part++) flit(descriptor[word * 64 + part * 16 +: 16], 0, 0);
    end
  endtask

  task automatic receive(input logic [15:0] expected, input bit last, input int stalls,
                         output logic [15:0] sampled);
    while (!host_tx_valid) @(negedge clk);
    repeat (stalls) begin
      @(posedge clk);
      if ({host_tx_valid, host_tx_last, host_tx_data} !== {1'b1, last, expected})
        $fatal(1, "PACKET_ATTENTION_STALL expected=%h last=%b actual=%h last=%b", expected, last, host_tx_data, host_tx_last);
      @(negedge clk);
    end
    host_tx_ready = 1;
    @(posedge clk);
    if ({host_tx_valid, host_tx_last, host_tx_data} !== {1'b1, last, expected})
        $fatal(1, "PACKET_ATTENTION_DATA expected=%h last=%b actual=%h last=%b", expected, last, host_tx_data, host_tx_last);
    sampled = host_tx_data;
    host_words++;
    @(negedge clk);
    host_tx_ready = 0;
  endtask

  task automatic response(input logic [2:0] opcode, input logic [31:0] tag, input bit error);
    logic [15:0] sampled;
    receive(tag[15:0], 0, 1, sampled);
    receive(tag[31:16], 0, 1, sampled);
    receive({12'd0, error, opcode}, error || opcode != 5, 2, sampled);
  endtask

  initial begin
    int refs, results, image_start, head, alpha, shift, inner, recent, streaming;
    int rank, position, expected_reads, prior_reads;
    logic [31:0] tag;
    logic [2047:0] expected, assembled;
    if (!$value$plusargs("FIXTURE=%s", fixture) || !$value$plusargs("DUMP=%s", dump))
      $fatal(1, "PACKET_ATTENTION_FIXTURE");
    $readmemh({fixture, "/map.hex"}, golden_map);
    $readmemh({fixture, "/signs.hex"}, signs);
    $readmemh({fixture, "/expected.hex"}, projected_cache);
    for (int index = 0; index < ImageTokens; index++) packed_map[index / 32][(index % 32) * 10 +: 10] = golden_map[index];
    refs = $fopen({fixture, "/rows.txt"}, "r");
    if (!refs || $fscanf(refs, "%d %d %d %d %d %d %d", image_start, head, alpha, shift, inner, recent, streaming) != 7 || head != 0)
      $fatal(1, "PACKET_ATTENTION_REFERENCE");
    results = $fopen(dump, "w");
    if (!results) $fatal(1, "PACKET_ATTENTION_DUMP");

    repeat (8) @(negedge clk);
    rst_n = 1;
    repeat (8) @(negedge clk);
    command(5, 32'h43010001, 1, '0);
    response(5, 32'h43010001, 1);
    command(2, 32'h43020000, 1, 192'({12'd1536, 10'(image_start), 5'd0, 1'b1}));
    for (int index = 0; index < ImageTokens; index++) begin
      sign_valid = 1;
      sign_data = signs[index];
      do @(posedge clk); while (!sign_ready);
      @(negedge clk);
    end
    sign_valid = 0;
    response(2, 32'h43020000, 0);
    if (maps != ImageTokens || context_bursts != 18 || context_words != 90 || context_acks != 18)
      $fatal(1, "PACKET_ATTENTION_CONTEXT_COUNTS");
    $display("PACKET_ATTENTION_CONTEXT_PASS maps=%0d at %0t", maps, $time);

    command(4, 32'h43011111, 3, {KeyBase, CacheBase + 64'd6144, 8'd1, 8'd8, 11'd408, 32'(alpha), 5'd0});
    while (!host_tx_valid) @(negedge clk);
    if ({head_done_id, head_done_inner, head_done_recent, head_done_streaming} !==
        {5'd0, 18'(inner), 18'(recent), 1'(streaming)}) $fatal(1, "PACKET_ATTENTION_PREDICTION");
    response(4, 32'h43011111, 0);
    $display("PACKET_ATTENTION_HEAD_PASS reads=%0d at %0t", reads, $time);
    for (int row = 0; row < 2; row++) begin
      if ($fscanf(refs, "%d %d %d %h", rank, position, expected_reads, expected) != 4)
        $fatal(1, "PACKET_ATTENTION_ROW_REFERENCE");
      prior_reads = value_reads;
      tag = 32'h43050000 + 32'(rank);
      command(5, tag, 3, 192'({KeyBase, CacheBase + 64'(rank * 64), 7'(shift), 11'd408, 11'(position), 5'd0}));
      response(5, tag, 0);
      for (int part = 0; part < 128; part++)
        receive(expected[part * 16 +: 16], part == 127, part % 7 == 0 ? 2 : 0, assembled[part * 16 +: 16]);
      if (value_reads - prior_reads != expected_reads) $fatal(1, "PACKET_ATTENTION_VALUE_COUNTS");
      $fdisplay(results, "%0512h", assembled);
      $fflush(results);
      $display("PACKET_ATTENTION_ROW_PASS rank=%0d value_reads=%0d at %0t", rank, expected_reads, $time);
    end
    $fclose(refs);
    $fclose(results);
    if (host_words != 271 || value_reads != 206 || reads <= value_reads || wide_reads == 0 || host_tx_valid)
      $fatal(1, "PACKET_ATTENTION_COUNTS");
    $display("COLD_PACKET_ATTENTION_PASS rows=2 host_words=%0d maps=%0d context_words=%0d reads=%0d value_reads=%0d wide=%0d auxiliary=%0d",
             host_words, maps, context_words, reads, value_reads, wide_reads, auxiliary_reads);
    $finish;
  end

  initial begin
    #10000000;
    $fatal(1, "PACKET_ATTENTION_TIMEOUT cycles=%0d maps=%0d reads=%0d host_words=%0d", cycles, maps, reads, host_words);
  end
endmodule
