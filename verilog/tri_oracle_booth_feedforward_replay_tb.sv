`timescale 1ns/1ps

module tri_oracle_booth_feedforward_replay_tb;
  localparam int Tokens = 2, Hidden = 2048, Intermediate = 5632;
  localparam int ActivationStride = 2112, ActivationBytes = Tokens * Hidden;
  localparam int IntermediateBytes = Tokens * Intermediate, WeightBytes = Hidden * Intermediate;
  localparam int SignBytes = WeightBytes / 4, Flits = 14399, Strips = Tokens * Hidden / 8;
  localparam int SignRequests = 4752;
  localparam logic [31:0] Tag = 32'h39300001;
  localparam logic [63:0] ProjectionBase = 64'h02000000;
  localparam logic [63:0] ActivationBase = 64'h00000001ffffffc0;
  localparam logic [63:0] GateBase = 64'h00000003fffff000, UpBase = 64'h00000005fffff000;
  localparam logic [63:0] DownBase = 64'h00000007fffff000, ScratchBase = 64'h00000009ffffff80;
  localparam logic [63:0] SignBase = 64'h0000000bffffff00;

  bit clk = 0, rst_n = 0;
  always #5 clk = !clk;
  logic host_rx_valid = 0, host_rx_ready, host_rx_is_payload, host_rx_payload_last;
  logic [15:0] host_rx_data;
  logic host_tx_valid, host_tx_ready, host_tx_last;
  logic [15:0] host_tx_data;
  logic memory_tx_valid, memory_tx_ready;
  logic [21:0] memory_tx_data;
  logic [1:0] memory_mem_rsp_valid, memory_mem_rsp_ready, memory_mem_rsp_last;
  logic [1023:0] memory_mem_rsp_data;
  wire [1:0] memory_mem_rsp_error = 2'b00;

  logic peer_rx_ready, peer_wide;
  logic [2:0] peer_req_valid, peer_req_ready;
  logic [2:0][63:0] peer_req_address;
  logic [2:0][5:0] peer_req_length;
  logic peer_write_valid, peer_write_ready, peer_word_valid, peer_word_ready, peer_write_last;
  logic [63:0] peer_write_address, peer_write_data;
  logic [4:0] peer_write_length;
  logic [7:0] peer_write_strobe;
  bit [1:0] reading = 0, reading_wide = 0;
  logic [1:0][63:0] read_address;
  int read_remaining[2];
  bit writing = 0, activation_write;
  bit [IntermediateBytes / 8 - 1:0] scratch_committed;
  logic [63:0] write_address;
  int write_offset, write_length, ack_delay = 0;
  int cycles, projection_requests, activation_acks, scratch_acks;
  int activation_bytes, scratch_bytes, wide_reads[2], sign_reads[2], scratch_reads[IntermediateBytes / 8];
  int host_words, host_strips, host_responses, host_stalls, transcript;
  bit held_reply;
  logic [16:0] held_word;
  logic [207:0] reply;

  logic [17:0] stimulus[Flits];
  logic [207:0] expected_replies[Strips];
  logic [511:0] projection_packets[64];
  logic [65:0] sign_request_fixture[SignRequests];
  logic [63:0] expected_sign_address[2][SignRequests];
  int sign_requests_by_lane[2];
  byte unsigned activation[ActivationBytes], intermediate[IntermediateBytes];
  byte unsigned pair_weights[2 * WeightBytes], down_weights[WeightBytes], signs[SignBytes];
  string fixtures, archive, packets;

  `include "tri_oracle_booth_feedforward_pad_peer.svh"

  tb_memory_forward_rx peer (
    .clk, .rst_n, .rx_valid(memory_tx_valid && cycles % 13 != 0),
    .rx_ready(peer_rx_ready), .rx_data(memory_tx_data),
    .req_valid(peer_req_valid), .req_ready(peer_req_ready), .req_address(peer_req_address),
    .req_length(peer_req_length), .req_wide(peer_wide),
    .write_valid(peer_write_valid), .write_ready(peer_write_ready),
    .write_address(peer_write_address), .write_length(peer_write_length),
    .word_valid(peer_word_valid), .word_ready(peer_word_ready),
    .write_data(peer_write_data), .write_strobe(peer_write_strobe), .write_last(peer_write_last)
  );

  function automatic bit in_region(input logic [63:0] address, base, input int bytes);
    return address >= base && address < base + 64'(bytes);
  endfunction

  function automatic int activation_offset(input logic [63:0] address);
    int offset;
    offset = int'(address - ActivationBase);
    return (offset / ActivationStride) * Hidden + offset % ActivationStride;
  endfunction

  function automatic logic [511:0] read_value(input logic [63:0] address, input bit wide);
    logic [511:0] value;
    int index, group_id, token;
    value = '0;
    if (!wide) begin
      if (address < ActivationBase) begin
        group_id = int'((address - ProjectionBase) >> 16);
        token = int'(address[6]);
        value[63:0] = projection_packets[2 * group_id + token][64 * int'(address[5:3]) +: 64];
      end else if (address < ScratchBase) begin
        index = activation_offset(address);
        for (int lane = 0; lane < 8; lane++) value[8 * lane +: 8] = activation[index + lane];
      end else begin
        index = int'(address - ScratchBase);
        for (int lane = 0; lane < 8; lane++) value[8 * lane +: 8] = intermediate[index + lane];
      end
    end else if (address < DownBase) begin
      index = address < UpBase ? int'(address - GateBase) : WeightBytes + int'(address - UpBase);
      for (int lane = 0; lane < 64; lane++) value[8 * lane +: 8] = pair_weights[index + lane];
    end else if (address < SignBase) begin
      index = int'(address - DownBase);
      for (int lane = 0; lane < 64; lane++) value[8 * lane +: 8] = down_weights[index + lane];
    end else begin
      index = int'(address - SignBase);
      for (int lane = 0; lane < 64; lane++) value[8 * lane +: 8] = signs[index + lane];
    end
    return value;
  endfunction

  assign memory_tx_ready = peer_rx_ready && cycles % 13 != 0;
  wire shared_idle = !reading[0] && !writing && ack_delay == 0;
  assign peer_req_ready = {shared_idle, !reading[1], shared_idle} & {3{cycles % 5 != 0}};
  assign peer_write_ready = shared_idle && cycles % 7 != 0;
  assign peer_word_ready = writing && cycles % 9 != 0;
  assign memory_mem_rsp_valid = {reading[1], reading[0] || ack_delay == 1};
  assign memory_mem_rsp_last = {reading[1] && read_remaining[1] == 1,
                                reading[0] ? read_remaining[0] == 1 : ack_delay == 1};
  for (genvar lane = 0; lane < 2; lane++) begin : payload
    assign memory_mem_rsp_data[lane * 512 +: 512] =
        reading[lane] ? read_value(read_address[lane], reading_wide[lane]) : 512'd0;
  end

  always @(posedge clk) if (rst_n) begin : memory_scoreboard
    cycles <= cycles + 1;
    for (int lane = 0; lane < 2; lane++) begin
      int port_id, beats, offset, column, bytes;
      logic [63:0] address, limit;
      port_id = lane == 0 && peer_req_valid[2] ? 2 : lane;
      address = peer_req_address[port_id];
      beats = int'(peer_req_length[port_id]);
      bytes = beats * (peer_wide ? 64 : 8);
      if (peer_req_valid[port_id] && peer_req_ready[port_id]) begin
        if (beats == 0 || (peer_wide ? address[5:0] != 0 : address[2:0] != 0))
          $fatal(1, "FEEDFORWARD_PHYSICAL_MISALIGNED_READ port=%0d address=%h beats=%0d", port_id, address, beats);
        if (port_id == 2) begin
          if (projection_requests >= 64 || peer_wide || beats != 8 ||
              address !== ProjectionBase + 64'(projection_requests % 32) * 65536 + 64'(projection_requests / 32) * 64)
            $fatal(1, "FEEDFORWARD_PHYSICAL_PROJECTION_READ index=%0d address=%h", projection_requests, address);
          projection_requests++;
          if (projection_requests == 64) $display("FEEDFORWARD_PHYSICAL_PROJECTION_REQUESTS count=64");
        end else if (peer_wide) begin
          if (activation_bytes != ActivationBytes || beats > 32)
            $fatal(1, "FEEDFORWARD_PHYSICAL_WIDE_READ_BEFORE_ACTIVATION");
          if (in_region(address, SignBase, SignBytes)) begin
            if (beats != 1 || sign_reads[lane] >= sign_requests_by_lane[lane] ||
                address !== expected_sign_address[lane][sign_reads[lane]])
              $fatal(1, "FEEDFORWARD_PHYSICAL_SIGN_BURST lane=%0d index=%0d address=%h",
                     lane, sign_reads[lane], address);
            sign_reads[lane]++;
          end else begin
            if (in_region(address, GateBase, WeightBytes)) limit = GateBase + WeightBytes;
            else if (in_region(address, UpBase, WeightBytes)) limit = UpBase + WeightBytes;
            else if (in_region(address, DownBase, WeightBytes) && scratch_bytes == IntermediateBytes)
              limit = DownBase + WeightBytes;
            else $fatal(1, "FEEDFORWARD_PHYSICAL_UNKNOWN_WEIGHT_ADDRESS %h", address);
            if (address + 64'(bytes) > limit) $fatal(1, "FEEDFORWARD_PHYSICAL_WEIGHT_RANGE");
            wide_reads[lane] += beats;
          end
        end else if (port_id == 0 && in_region(address, ActivationBase, Tokens * ActivationStride)) begin
          column = int'(address - ActivationBase) % ActivationStride;
          if (activation_acks != ActivationBytes / 128 || column + bytes > Hidden)
            $fatal(1, "FEEDFORWARD_PHYSICAL_ACTIVATION_READ address=%h", address);
        end else if (port_id == 0 && in_region(address, ScratchBase, IntermediateBytes)) begin
          offset = int'(address - ScratchBase);
          if (offset + bytes > IntermediateBytes) $fatal(1, "FEEDFORWARD_PHYSICAL_INTERMEDIATE_RANGE");
          for (int word = 0; word < beats; word++) begin
            if (!scratch_committed[offset / 8 + word])
              $fatal(1, "FEEDFORWARD_PHYSICAL_INTERMEDIATE_NOT_COMMITTED address=%h", address);
            scratch_reads[offset / 8 + word]++;
          end
        end else $fatal(1, "FEEDFORWARD_PHYSICAL_UNKNOWN_READ port=%0d address=%h", port_id, address);
        read_address[lane] <= address;
        read_remaining[lane] <= beats;
        reading[lane] <= 1;
        reading_wide[lane] <= peer_wide;
      end else if (reading[lane] && memory_mem_rsp_ready[lane]) begin
        read_address[lane] <= read_address[lane] + (reading_wide[lane] ? 64'd64 : 64'd8);
        read_remaining[lane] <= read_remaining[lane] - 1;
        reading[lane] <= read_remaining[lane] != 1;
      end
    end

    if (peer_write_valid && peer_write_ready) begin
      int offset, column;
      if (in_region(peer_write_address, ActivationBase, Tokens * ActivationStride)) begin
        if (peer_write_address !== ActivationBase + 64'((activation_bytes / Hidden) * ActivationStride +
                                                       activation_bytes % Hidden) || peer_write_length != 16 ||
            (activation_bytes & 127) != 0 || activation_bytes >= ActivationBytes)
          $fatal(1, "FEEDFORWARD_PHYSICAL_ACTIVATION_WRITE address=%h", peer_write_address);
        activation_write <= 1;
      end else begin
        offset = int'(peer_write_address - ScratchBase);
        column = offset % Intermediate;
        if (activation_acks != ActivationBytes / 128 ||
            !in_region(peer_write_address, ScratchBase, IntermediateBytes) || column % 80 != 0 ||
            int'(peer_write_length) * 8 != (column + 80 > Intermediate ? Intermediate - column : 80))
          $fatal(1, "FEEDFORWARD_PHYSICAL_INTERMEDIATE_WRITE address=%h", peer_write_address);
        activation_write <= 0;
      end
      writing <= 1;
      write_address <= peer_write_address;
      write_offset <= 0;
      write_length <= int'(peer_write_length);
    end
    if (peer_word_valid && peer_word_ready) begin
      int offset;
      logic [63:0] expected;
      offset = (activation_write ? activation_offset(write_address) : int'(write_address - ScratchBase)) + write_offset * 8;
      for (int lane = 0; lane < 8; lane++)
        expected[8 * lane +: 8] = activation_write ? activation[offset + lane] : intermediate[offset + lane];
      if ({peer_write_strobe, peer_write_last, peer_write_data} !== {8'hff, write_offset + 1 == write_length, expected})
        $fatal(1, "FEEDFORWARD_PHYSICAL_WRITE_DATA address=%h word=%0d got=%h expected=%h",
               write_address, write_offset, peer_write_data, expected);
      if (activation_write) activation_bytes += 8;
      else scratch_bytes += 8;
      if (peer_write_last) begin
        writing <= 0;
        ack_delay <= 4;
      end else write_offset <= write_offset + 1;
    end
    if (ack_delay > 1) ack_delay <= ack_delay - 1;
    if (ack_delay == 1 && memory_mem_rsp_ready[0]) begin
      if (activation_write) begin
        activation_acks++;
        if (activation_acks == ActivationBytes / 128)
          $display("FEEDFORWARD_PHYSICAL_ACTIVATIONS_COMMITTED bytes=%0d", ActivationBytes);
      end
      else begin
        int first_word;
        first_word = int'((write_address - ScratchBase) >> 3);
        for (int word = 0; word < write_length; word++) begin
          if (scratch_committed[first_word + word]) $fatal(1, "FEEDFORWARD_PHYSICAL_DUPLICATE_WRITE");
          scratch_committed[first_word + word] = 1;
        end
        scratch_acks++;
        if (scratch_acks == Tokens * ((Intermediate + 79) / 80))
          $display("FEEDFORWARD_PHYSICAL_INTERMEDIATES_COMMITTED bytes=%0d", IntermediateBytes);
      end
      ack_delay <= 0;
    end
  end

  assign host_tx_ready = cycles % 11 >= 5;
  always @(posedge clk) if (rst_n) begin
    if (held_reply && {host_tx_valid, host_tx_last, host_tx_data} !== {1'b1, held_word})
      $fatal(1, "FEEDFORWARD_PHYSICAL_HOST_CHANGED_UNDER_STALL");
    held_reply = host_tx_valid && !host_tx_ready;
    if (held_reply) begin
      held_word = {host_tx_last, host_tx_data};
      host_stalls++;
    end
    if (host_tx_valid && host_tx_ready) begin
      if (host_words >= 13) $fatal(1, "FEEDFORWARD_PHYSICAL_HOST_MISSING_LAST");
      reply[16 * host_words +: 16] = host_tx_data;
      host_words++;
      if (host_tx_last) begin
        case (host_words)
          3: begin
            if (host_responses != 0 || reply[47:0] !== {16'd0, Tag})
              $fatal(1, "FEEDFORWARD_PHYSICAL_COMMAND_RESPONSE data=%h", reply[47:0]);
            host_responses++;
          end
          13: begin
            if (host_strips >= Strips || reply !== expected_replies[host_strips])
              $fatal(1, "FEEDFORWARD_PHYSICAL_HOST_WRITEBACK strip=%0d got=%h expected=%h",
                     host_strips, reply, expected_replies[host_strips]);
            $fdisplay(transcript, "%052h", reply);
            host_strips++;
            if (host_strips % 32 == 0) begin
              $fflush(transcript);
              $display("FEEDFORWARD_PHYSICAL_WRITEBACK_PROGRESS strips=%0d", host_strips);
            end
          end
          default: $fatal(1, "FEEDFORWARD_PHYSICAL_HOST_RECORD_LENGTH words=%0d", host_words);
        endcase
        host_words = 0;
      end
    end
  end

  initial begin : run
    integer input_file;
    if (!$value$plusargs("REPLAY=%s", fixtures) || !$value$plusargs("ARCHIVE=%s", archive) ||
        !$value$plusargs("PACKETS=%s", packets)) $fatal(1, "FEEDFORWARD_PHYSICAL_MISSING_FIXTURE");
    transcript = $fopen({fixtures, "/observed_writeback.hex"}, "w");
    if (!transcript) $fatal(1, "FEEDFORWARD_PHYSICAL_MISSING_TRANSCRIPT");
    $readmemh({fixtures, "/host_input.hex"}, stimulus);
    $readmemh({fixtures, "/host_writeback.hex"}, expected_replies);
    $readmemh({archive, "/learned/activation.hex"}, activation);
    $readmemh({archive, "/fixture/intermediate.hex"}, intermediate);
    $readmemh({archive, "/sign_reads.hex"}, sign_request_fixture);
    $readmemh(packets, projection_packets);
    foreach (sign_request_fixture[index]) begin
      int lane;
      case (sign_request_fixture[index][65:64])
        2'b01: lane = 0;
        2'b10: lane = 1;
        default: $fatal(1, "FEEDFORWARD_PHYSICAL_SIGN_FIXTURE_LANE index=%0d", index);
      endcase
      expected_sign_address[lane][sign_requests_by_lane[lane]] = sign_request_fixture[index][63:0];
      sign_requests_by_lane[lane]++;
    end
    input_file = $fopen({archive, "/pair.bin"}, "rb");
    if (!input_file || $fread(pair_weights, input_file) != 2 * WeightBytes)
      $fatal(1, "FEEDFORWARD_PHYSICAL_PAIR_FIXTURE");
    $fclose(input_file);
    input_file = $fopen({archive, "/down.bin"}, "rb");
    if (!input_file || $fread(down_weights, input_file) != WeightBytes)
      $fatal(1, "FEEDFORWARD_PHYSICAL_DOWN_FIXTURE");
    $fclose(input_file);
    input_file = $fopen({fixtures, "/packed_sign.bin"}, "rb");
    if (!input_file || $fread(signs, input_file) != SignBytes)
      $fatal(1, "FEEDFORWARD_PHYSICAL_SIGN_FIXTURE");
    $fclose(input_file);
    $display("FEEDFORWARD_PHYSICAL_FIXTURES_LOADED");
    repeat (8) @(negedge clk);
    rst_n = 1;
    repeat (8) @(negedge clk);
    foreach (stimulus[index]) begin
      host_rx_valid = 1;
      {host_rx_payload_last, host_rx_is_payload, host_rx_data} = stimulus[index];
      do begin
        @(posedge clk);
        if ($isunknown(host_rx_ready)) $fatal(1, "FEEDFORWARD_PHYSICAL_HOST_UNKNOWN_READY index=%0d", index);
      end while (!host_rx_ready);
      @(negedge clk);
    end
    host_rx_valid = 0;
    wait (host_strips == Strips && host_responses == 1);
    repeat (32) @(negedge clk);
    if (projection_requests != 64 || activation_bytes != ActivationBytes || scratch_bytes != IntermediateBytes ||
        scratch_acks != 2 * ((Intermediate + 79) / 80) ||
        sign_reads[0] != sign_requests_by_lane[0] || sign_reads[1] != sign_requests_by_lane[1] ||
        wide_reads[0] + wide_reads[1] != 540672 || host_stalls == 0 || reading != 0 || writing || ack_delay != 0)
      $fatal(1, "FEEDFORWARD_PHYSICAL_FINAL_TOTALS projections=%0d activation=%0d scratch=%0d sign=%0d wide=%0d",
             projection_requests, activation_bytes, scratch_bytes, sign_reads[0] + sign_reads[1],
             wide_reads[0] + wide_reads[1]);
    foreach (scratch_reads[word])
      if (scratch_reads[word] != 13) $fatal(1, "FEEDFORWARD_PHYSICAL_INTERMEDIATE_READ_COUNT word=%0d", word);
    $display("FEEDFORWARD_PHYSICAL_PASS strips=%0d outputs=%0d responses=%0d cycles=%0d",
             host_strips, host_strips * 8, host_responses, cycles);
    $fclose(transcript);
    $finish;
  end

  initial begin
    #100000000;
    $fatal(1, "FEEDFORWARD_PHYSICAL_TIMEOUT projections=%0d activation=%0d scratch=%0d strips=%0d replies=%0d",
           projection_requests, activation_bytes, scratch_bytes, host_strips, host_responses);
  end
endmodule
