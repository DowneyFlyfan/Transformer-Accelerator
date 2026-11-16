`timescale 1ns/1ps

// The linker supplies the instance from the previously verified wrapper.
module tri_oracle_chip_packet_io_tb;
  localparam int Slots = 409, Groups = 40, WordsPerToken = 256, Tokens = 16;
  localparam logic [63:0] ActivationBase = 64'h10000, WeightBase = 64'h10000000, CacheBase = 64'h2000000;
  localparam logic [31:0] Tag = 32'h43000000;
  bit clk = 0, rst_n = 0;
  always #5 clk = !clk;

  logic host_rx_valid = 0, host_rx_ready, host_rx_is_payload = 0, host_rx_payload_last = 0;
  logic [15:0] host_rx_data = '0;
  logic host_tx_valid, host_tx_ready = 0, host_tx_last;
  logic [15:0] host_tx_data;
  logic angle_valid = 0, angle_last = 0, angle_ready;
  logic [511:0] angle_cos = '0, angle_sin = '0;

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

  logic [63:0] activations[Slots * WordsPerToken], weights[Groups * 64 * WordsPerToken];
  logic [511:0] cosines[Slots], sines[Slots], expected[Groups * Slots], committed[Tokens];
  logic [5:0] biases[Slots];
  logic [239:0] shifts[1];
  logic [511:0] assembly;
  logic [63:0] read_address;
  bit reading = 0, writing = 0;
  int ack_delay = 0, read_remaining, write_offset;
  int cycles = 0, bursts = 0, activation_beats = 0, weight_beats = 0;
  int write_bursts = 0, write_words = 0, acks = 0;
  int forward_stalls = 0, acknowledgment_wait_cycles = 0;
  string fixture, dump;

  // CHIP_INSTANCE

  tri_oracle_memory_forward_rx peer (
    .clk, .rst_n, .rx_valid(memory_tx_valid && cycles % 13 != 0),
    .rx_ready(peer_rx_ready), .rx_data(memory_tx_data),
    .req_valid(peer_req_valid), .req_ready(peer_req_ready), .req_address(peer_req_address),
    .req_length(peer_req_length), .req_wide(peer_wide),
    .write_valid(peer_write_valid), .write_ready(peer_write_ready),
    .write_address(peer_write_address), .write_length(peer_write_length),
    .word_valid(peer_word_valid), .word_ready(peer_word_ready),
    .write_data(peer_write_data), .write_strobe(peer_write_strobe), .write_last(peer_write_last)
  );

  function automatic logic [63:0] read_word(input logic [63:0] address);
    if (address >= WeightBase)
      return weights[int'((address - WeightBase) >> 3)];
    return activations[int'((address - ActivationBase) >> 3)];
  endfunction

  assign memory_tx_ready = peer_rx_ready && cycles % 13 != 0;
  assign peer_req_ready = {2'b00, !reading && !writing && ack_delay == 0 && cycles % 5 != 0};
  assign peer_write_ready = !reading && !writing && ack_delay == 0 && cycles % 7 != 0;
  assign peer_word_ready = writing && cycles % 9 != 0;
  assign memory_mem_rsp_valid = {1'b0, reading || ack_delay == 1};
  assign memory_mem_rsp_last = {1'b0, reading ? read_remaining == 1 : ack_delay == 1};
  assign memory_mem_rsp_data = {960'd0, reading ? read_word(read_address) : 64'd0};

  always @(posedge clk) if (rst_n) begin
    cycles <= cycles + 1;
    if (memory_tx_valid && !memory_tx_ready) forward_stalls++;
    if (ack_delay > 1) begin
      acknowledgment_wait_cycles++;
      ack_delay <= ack_delay - 1;
    end
    if (peer_req_valid[2:1] != 0)
      $fatal(1, "PROJECTION_USED_UNEXPECTED_READ_PORT");
    if (peer_req_valid[0] && peer_req_ready[0]) begin
      logic [63:0] address, bound;
      address = peer_req_address[0];
      bound = address >= WeightBase ? WeightBase + 64 * WordsPerToken * 8 :
                                      ActivationBase + Tokens * WordsPerToken * 8;
      if (peer_wide || peer_req_length[0] == 0 || address < ActivationBase || address[2:0] != 0 ||
          address >= bound || address + 8 * 64'(peer_req_length[0]) > bound)
        $fatal(1, "PACKET_PROJECTION_READ_ADDRESS addr=%h len=%0d wide=%b", address, peer_req_length[0], peer_wide);
      read_address <= address;
      read_remaining <= int'(peer_req_length[0]);
      reading <= 1;
      bursts++;
    end else if (reading && memory_mem_rsp_ready[0]) begin
      if (read_address >= WeightBase) weight_beats++;
      else activation_beats++;
      read_address <= read_address + 64'd8;
      read_remaining <= read_remaining - 1;
      reading <= read_remaining != 1;
    end

    if (peer_write_valid && peer_write_ready) begin
      if (write_bursts >= Tokens || peer_write_address !== CacheBase + 64'(write_bursts * 64) ||
          peer_write_length !== 5'd8 || write_bursts != acks)
        $fatal(1, "PACKET_PROJECTION_WRITE_ADDRESS addr=%h len=%0d", peer_write_address, peer_write_length);
      write_bursts++;
      write_offset <= 0;
      writing <= 1;
    end
    if (peer_word_valid && peer_word_ready) begin
      if (peer_write_strobe !== 8'hff || peer_write_last !== (write_offset == 7) ||
          peer_write_data !== expected[write_bursts - 1][write_offset * 64 +: 64])
        $fatal(1, "PACKET_PROJECTION_WRITE_BYTES slot=%0d word=%0d", write_bursts - 1, write_offset);
      assembly[write_offset * 64 +: 64] <= peer_write_data;
      write_words++;
      if (peer_write_last) begin
        writing <= 0;
        ack_delay <= 4;
      end else write_offset <= write_offset + 1;
    end
    if (ack_delay == 1 && memory_mem_rsp_ready[0]) begin
      committed[acks] <= assembly;
      acks++;
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

  initial begin
    logic [95:0] strip_biases;
    logic [575:0] descriptor;
    logic [47:0] response;
    int file;
    if (!$value$plusargs("FIXTURE=%s", fixture) || !$value$plusargs("DUMP=%s", dump))
      $fatal(1, "PACKET_PROJECTION_FIXTURE");
    $readmemh({fixture, "/activation.hex"}, activations);
    $readmemh({fixture, "/weights.hex"}, weights);
    $readmemh({fixture, "/cos.hex"}, cosines);
    $readmemh({fixture, "/sin.hex"}, sines);
    $readmemh({fixture, "/biases.hex"}, biases);
    $readmemh({fixture, "/shifts.hex"}, shifts);
    $readmemh({fixture, "/expected.hex"}, expected);
    for (int token = 0; token < Tokens; token++) strip_biases[token * 6 +: 6] = biases[token];
    descriptor = 576'({strip_biases, shifts[0], CacheBase, WeightBase, ActivationBase,
                       10'd0, 6'd1, 6'd0, 5'd16});

    repeat (8) @(negedge clk);
    rst_n = 1;
    repeat (8) @(negedge clk);
    flit(Tag[15:0], 0, 0);
    flit(Tag[31:16], 0, 0);
    flit(16'd1, 0, 0);
    for (int word = 0; word < 9; word++) begin
      flit(descriptor[word * 64 +: 16], 1, word == 8);
      for (int part = 1; part < 4; part++) flit(descriptor[word * 64 + part * 16 +: 16], 0, 0);
    end
    for (int token = 0; token < Tokens; token++) begin
      angle_valid = 1;
      angle_last = token == Tokens - 1;
      angle_cos = cosines[token];
      angle_sin = sines[token];
      do @(posedge clk); while (!angle_ready);
      @(negedge clk);
    end
    angle_valid = 0;

    response = {12'd0, 1'b0, 3'd1, Tag};
    while (!host_tx_valid) @(negedge clk);
    if (acks != Tokens || write_bursts != Tokens || write_words != Tokens * 8 || !activation_beats ||
        !weight_beats || !forward_stalls || acknowledgment_wait_cycles != Tokens * 3)
      $fatal(1, "PACKET_PROJECTION_COUNTS");
    for (int index = 0; index < 3; index++) begin
      @(posedge clk);
      if ({host_tx_valid, host_tx_last, host_tx_data} !== {1'b1, index == 2, response[index * 16 +: 16]})
        $fatal(1, "PACKET_PROJECTION_HOST_RESPONSE");
      @(negedge clk);
      host_tx_ready = 1;
      @(negedge clk);
      host_tx_ready = 0;
    end
    file = $fopen(dump, "w");
    if (!file) $fatal(1, "PACKET_PROJECTION_DUMP");
    for (int slot = 0; slot < Tokens; slot++) $fdisplay(file, "%0128h", committed[slot]);
    $fclose(file);
    $display("COLD_PACKET_PROJECTION_PASS vectors=%0d acks=%0d writes=%0d read_bursts=%0d activation_words=%0d weight_words=%0d stalls=%0d",
             Tokens, acks, write_words, bursts, activation_beats, weight_beats, forward_stalls);
    $finish;
  end

  initial begin
    #2000000;
    $fatal(1, "PACKET_PROJECTION_TIMEOUT");
  end
endmodule
