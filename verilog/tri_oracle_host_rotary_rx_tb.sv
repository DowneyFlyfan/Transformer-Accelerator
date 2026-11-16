`timescale 1ns/1ps

module tri_oracle_host_rotary_rx_tb;
  bit clk = 0, rst_n = 0;
  always #5 clk = !clk;
  logic rx_valid = 0, rx_ready, rx_is_payload = 0, rx_payload_last = 0;
  logic [15:0] rx_data = 0;
  logic link_valid, link_ready, angle_valid, angle_ready = 0, angle_last;
  logic [1023:0] angle_data;
  logic command_valid, command_ready = 0, payload_valid, payload_ready = 0, payload_last;
  logic [2:0] command_opcode;
  logic [31:0] command_tag;
  logic [63:0] payload_data;
  logic [1023:0] expected;
  int vectors, commands, payloads, blocked_cycles;

  tri_oracle_host_rotary_rx dut (
    .clk, .rst_n, .rx_valid, .rx_ready, .rx_is_payload, .rx_payload_last, .rx_data,
    .link_valid, .link_ready, .angle_valid, .angle_ready, .angle_last, .angle_data
  );
  tri_oracle_host_command_link host_link (
    .clk, .rst_n, .rx_valid(link_valid), .rx_ready(link_ready),
    .rx_is_payload, .rx_payload_last, .rx_data,
    .tx_valid(), .tx_ready(1'b0), .tx_last(), .tx_data(),
    .command_valid, .command_ready, .command_opcode, .command_tag,
    .payload_valid, .payload_ready, .payload_data, .payload_last,
    .response_valid(1'b0), .response_ready(), .response_error(1'b0),
    .response_opcode(3'd0), .response_tag(32'd0)
  );

  always @(posedge clk) if (rst_n) begin
    if (angle_valid && angle_ready) vectors++;
    if (command_valid && command_ready) commands++;
    if (payload_valid && payload_ready) payloads++;
    if (rx_valid && !rx_ready) blocked_cycles++;
  end

  task automatic word(input logic [15:0] value, input bit payload, last);
    rx_valid = 1;
    rx_data = value;
    rx_is_payload = payload;
    rx_payload_last = last;
    do @(posedge clk); while (!rx_ready);
    @(negedge clk);
    rx_valid = 0;
  endtask

  task automatic rotary(input bit last, input int seed);
    word(last ? 16'hA671 : 16'hA670, 0, 1);
    for (int part = 0; part < 64; part++) begin
      expected[part * 16 +: 16] = 16'(seed + part * 313);
      // Header-like controls within a record are ordinary body data.
      if (angle_valid || link_valid) $fatal(1, "ROTARY_EXPOSED_PARTIAL_RECORD");
      word(expected[part * 16 +: 16], part % 2 != 0, 1);
      if (part % 5 == 0) @(negedge clk);
    end
    if ({angle_valid, angle_last, angle_data} !== {1'b1, last, expected})
      $fatal(1, "ROTARY_WRONG_COMPLETE_VECTOR");
  endtask

  initial begin
    repeat (3) @(negedge clk);
    rst_n = 1;
    word(16'h1234, 0, 0);
    word(16'hA670, 0, 1);
    word(16'd3, 0, 0);
    if (!command_valid || {command_opcode, command_tag} !== {3'd3, 32'hA6701234})
      $fatal(1, "ROTARY_CHANGED_LEGACY_COMMAND");

    // Rotary data must bypass a completed command that is still queued.
    rotary(0, 32'hA671);
    fork
      begin
        word(16'hABCD, 1, 1);
        word(16'h5678, 0, 0);
        word(16'hA671, 0, 1);
        word(16'hDEAD, 0, 0);
      end
      begin
        repeat (4) begin
          @(posedge clk);
          if ({angle_valid, angle_last, angle_data} !== {1'b1, 1'b0, expected} || rx_ready)
            $fatal(1, "ROTARY_CHANGED_STALLED_VECTOR");
        end
        @(negedge clk);
        command_ready = 1;
        angle_ready = 1;
        @(negedge clk);
        command_ready = 0;
        angle_ready = 0;
      end
    join
    if (!payload_valid || !payload_last || payload_data !== 64'hDEADA6715678ABCD)
      $fatal(1, "ROTARY_CHANGED_LEGACY_PAYLOAD");
    payload_ready = 1;
    @(negedge clk);
    payload_ready = 0;

    word(16'hA671, 0, 1);
    repeat (7) word(16'hFFFF, 0, 0);
    rst_n = 0;
    repeat (3) @(negedge clk);
    if (angle_valid || rx_ready || link_valid) $fatal(1, "ROTARY_RESET_DID_NOT_DROP_RECORD");
    rst_n = 1;
    rotary(1, 7103);
    angle_ready = 1;
    @(negedge clk);
    if (vectors != 2 || commands != 1 || payloads != 1 || blocked_cycles < 4 || angle_valid)
      $fatal(1, "ROTARY_INVENTORY");
    $display("HOST_ROTARY_RX_PASS vectors=%0d commands=%0d payloads=%0d blocked=%0d",
             vectors, commands, payloads, blocked_cycles);
    $finish;
  end

  initial begin
    #20000;
    $fatal(1, "HOST_ROTARY_RX_TIMEOUT");
  end
endmodule
