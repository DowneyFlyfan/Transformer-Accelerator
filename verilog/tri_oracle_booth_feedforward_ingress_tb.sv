`timescale 1ns/1ps

module tri_oracle_booth_feedforward_ingress_tb;
  localparam int Strips = 512;
  localparam int Flits = 3 + 15 * 4 + Strips * (9 + 17);
  bit clk = 0, rst_n = 0;
  always #5 clk = !clk;
  logic [17:0] stimulus[Flits], flit_word;
  logic [959:0] expected_descriptor[1];
  logic [128:0] expected_stats[Strips];
  logic [256:0] expected_replay[Strips];
  logic in_valid, in_ready, pad_valid, pad_ready, rx_valid, rx_ready;
  logic [3:0] pad_data;
  logic rx_payload_last, rx_is_payload;
  logic [15:0] rx_data;
  logic forward_valid, forward_ready, command_valid, command_ready, payload_valid, payload_ready, payload_last;
  logic [2:0] command_opcode, response_opcode;
  logic [31:0] command_tag, response_tag, layer_command_tag;
  logic [63:0] payload_data;
  logic response_valid, response_ready, response_error;
  logic [5:0] layer_command_valid;
  logic [1663:0] layer_command_payload;
  logic control_valid, operand_valid, gamma_valid, stats_valid, stats_last, replay_valid, replay_last;
  logic [127:0] stats_data, replay_data, replay_gamma;
  int cycles = 0, commands = 0, stats = 0, replays = 0;
  int stats_stalls = 0, replay_stalls = 0;
  wire stats_ready = cycles % 13 >= 8;
  wire replay_ready = cycles % 17 >= 10;
  string fixture;

  tb_tri_oracle_flit_to_pads #(.WORD_BITS(18), .PAD_BITS(4)) source (
    .clk, .rst_n, .in_valid, .in_ready, .in_word(flit_word),
    .pad_valid, .pad_ready, .pad_data
  );
  tri_oracle_host_serial_pads ingress (
    .clk, .rst_n, .host_rx_valid(pad_valid), .host_rx_ready(pad_ready), .host_rx_data(pad_data),
    .wide_host_rx_valid(rx_valid), .wide_host_rx_ready(rx_ready),
    .wide_host_rx_payload_last(rx_payload_last), .wide_host_rx_is_payload(rx_is_payload),
    .wide_host_rx_data(rx_data),
    .host_tx_valid(), .host_tx_ready(1'b1), .host_tx_data(),
    .wide_host_tx_valid(1'b0), .wide_host_tx_ready(), .wide_host_tx_last(1'b0), .wide_host_tx_data(16'd0)
  );
  tri_oracle_host_boundary_rx boundary (
    .clk, .rst_n, .rx_valid, .rx_ready, .rx_is_payload, .rx_payload_last, .rx_data,
    .forward_valid, .forward_ready, .control_valid, .control_ready(1'b1), .control_action(),
    .operand_valid, .operand_ready(1'b1), .residual_q32(), .projection_shift(),
    .gamma_valid, .gamma_ready(1'b1), .gamma_data(),
    .stats_valid, .stats_ready, .stats_last, .stats_data,
    .replay_valid, .replay_ready, .replay_last, .replay_data, .replay_gamma
  );
  tri_oracle_host_command_link command_link (
    .clk, .rst_n, .rx_valid(forward_valid), .rx_ready(forward_ready),
    .rx_is_payload, .rx_payload_last, .rx_data,
    .tx_valid(), .tx_ready(1'b1), .tx_last(), .tx_data(),
    .command_valid, .command_ready, .command_opcode, .command_tag,
    .payload_valid, .payload_ready, .payload_data, .payload_last,
    .response_valid, .response_ready, .response_error, .response_opcode, .response_tag
  );
  tri_oracle_indexed_chip_dispatch dispatch (
    .clk, .rst_n, .command_valid, .command_ready, .command_opcode, .command_tag,
    .payload_valid, .payload_ready, .payload_data, .payload_last,
    .response_valid, .response_ready, .response_error, .response_opcode, .response_tag,
    .layer_command_valid, .layer_command_ready(6'b000001), .layer_command_tag, .layer_command_payload,
    .layer_done_valid(6'd0), .layer_done_ready(), .layer_done_error(6'd0), .layer_done_tag(192'd0)
  );

  always @(posedge clk) if (rst_n) begin
    cycles <= cycles + 1;
    if (control_valid || operand_valid || gamma_valid || response_valid)
      $fatal(1, "FEEDFORWARD_INGRESS_UNEXPECTED_CHANNEL");
    if (layer_command_valid != 0) begin
      if (commands != 0 || layer_command_valid !== 6'b000001 || layer_command_tag !== 32'h39300001 ||
          layer_command_payload[959:0] !== expected_descriptor[0])
        $fatal(1, "FEEDFORWARD_INGRESS_DESCRIPTOR");
      commands++;
    end
    if (stats_valid) begin
      if (stats >= Strips || {stats_last, stats_data} !== expected_stats[stats])
        $fatal(1, "FEEDFORWARD_INGRESS_STATS strip=%0d", stats);
      if (stats_ready) stats++;
      else stats_stalls++;
    end
    if (replay_valid) begin
      if (replays >= Strips || {replay_last, replay_gamma, replay_data} !== expected_replay[replays])
        $fatal(1, "FEEDFORWARD_INGRESS_REPLAY strip=%0d", replays);
      if (replay_ready) replays++;
      else replay_stalls++;
    end
  end

  initial begin
    if (!$value$plusargs("FIXTURE=%s", fixture)) $fatal(1, "FEEDFORWARD_INGRESS_FIXTURE");
    $readmemh({fixture, "/flits.hex"}, stimulus);
    $readmemh({fixture, "/descriptor.hex"}, expected_descriptor);
    $readmemh({fixture, "/stats.hex"}, expected_stats);
    $readmemh({fixture, "/replay.hex"}, expected_replay);
    in_valid = 0;
    repeat (4) @(negedge clk);
    rst_n = 1;
    repeat (4) @(negedge clk);
    foreach (stimulus[index]) begin
      in_valid = 1;
      flit_word = stimulus[index];
      do begin
        @(posedge clk);
        if ($isunknown(in_ready))
          $fatal(1, "FEEDFORWARD_INGRESS_READY_UNKNOWN flit=%0d", index);
      end while (!in_ready);
      @(negedge clk);
    end
    in_valid = 0;
    repeat (40) @(negedge clk);
    if (commands != 1 || stats != Strips || replays != Strips || stats_stalls == 0 || replay_stalls == 0)
      $fatal(1, "FEEDFORWARD_INGRESS_TOTALS command=%0d stats=%0d replay=%0d stalls=%0d,%0d",
             commands, stats, replays, stats_stalls, replay_stalls);
    $display("BOOTH_FEEDFORWARD_INGRESS_PASS commands=%0d flits=%0d stats=%0d replay=%0d stalls=%0d,%0d",
             commands, Flits, stats, replays, stats_stalls, replay_stalls);
    $finish;
  end

  initial begin
    #2000000;
    $fatal(1, "FEEDFORWARD_INGRESS_TIMEOUT command=%0d stats=%0d replay=%0d", commands, stats, replays);
  end
endmodule
