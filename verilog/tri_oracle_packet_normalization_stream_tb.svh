`timescale 1ns/1ps

module tri_oracle_packet_normalization_stream_tb;
  bit clk = 0, rst_n = 0;
  always #5 clk = !clk;
  logic cfg_valid = 0, cfg_ready;
  logic [31:0] cfg_tag, cfg_epsilon_q16 = 32'd43980465;
  logic [9:0] cfg_strips = 10'd256;
  logic [5:0] cfg_shift = 6'd17;
  logic stats_valid, stats_last, stats_ready;
  logic [127:0] stats_data;
  logic replay_valid, replay_last, replay_ready;
  logic [127:0] replay_data, replay_gamma;
  logic out_valid, out_ready, out_last, out_error;
  logic [31:0] out_tag;
  logic [9:0] out_index;
  logic [3:0] out_count;
  logic [127:0] out_norm_q8;
  logic [7:0] out_outlier_mask;
  logic [63:0] out_activation;
  logic rx_valid = 0, rx_ready, rx_is_payload = 0, rx_payload_last = 0;
  logic [15:0] rx_data = 0;
  logic forward_valid;
  logic [255:0] input_rows[512];
  logic [247:0] expected[512];
  string input_path, expected_path, dump;
  int file, cycle, stats_received, replay_received, rows, host_words, held_outputs;

  tri_oracle_host_normalization_rx port_rx (.*, .forward_ready(1'b1),
    .operand_ready(1'b0),.gamma_ready(1'b0),.operand_valid(),.gamma_valid(),.residual_q32(),
    .projection_shift(),.gamma_data());
  // RMS_INSTANCE
  assign out_ready = cycle % 19 > 3;

  always @(posedge clk) if (rst_n) begin
    cycle <= cycle + 1;
    if (rx_valid && rx_ready) host_words++;
    if (forward_valid) $fatal(1,"NORMALIZATION_STREAM_MISROUTED_FRAME");
    if (stats_valid && stats_ready) begin
      if (stats_received >= 512 || {stats_last,stats_data} !==
          {stats_received % 256 == 255,input_rows[stats_received][127:0]})
        $fatal(1,"NORMALIZATION_STATS_PACKET index=%0d",stats_received);
      stats_received++;
    end
    if (replay_valid && replay_ready) begin
      if (replay_received >= 512 || {replay_last,replay_gamma,replay_data} !==
          {replay_received % 256 == 255,input_rows[replay_received]})
        $fatal(1,"NORMALIZATION_REPLAY_PACKET index=%0d",replay_received);
      replay_received++;
    end
    if (out_valid && !out_ready) held_outputs++;
    if (out_valid && out_ready) begin
      if (rows >= 512 || out_tag !== cfg_tag ||
          {out_index,out_count,out_last,out_error,out_norm_q8,out_outlier_mask,out_activation} !== expected[rows][215:0])
        $fatal(1,"NORMALIZATION_STREAM_OUTPUT row=%0d got=%h expected=%h",rows,
               {out_index,out_count,out_last,out_error,out_norm_q8,out_outlier_mask,out_activation},expected[rows][215:0]);
      $fdisplay(file,"%054h",{out_index,out_count,out_last,out_error,out_norm_q8,out_outlier_mask,out_activation});
      rows++;
    end
  end

  task automatic word(input logic [15:0] data, input bit header);
    rx_valid = 1;
    rx_payload_last = header;
    rx_data = data;
    do @(posedge clk); while (!rx_ready);
    @(negedge clk);
    rx_valid = 0;
  endtask

  initial begin
    if (!$value$plusargs("NORM_INPUTS=%s",input_path) || !$value$plusargs("NORM_EXPECTED=%s",expected_path) ||
        !$value$plusargs("DUMP=%s",dump)) $fatal(1,"NORMALIZATION_STREAM_FIXTURE");
    $readmemh(input_path,input_rows);
    $readmemh(expected_path,expected);
    file = $fopen(dump,"w");
    if (!file) $fatal(1,"NORMALIZATION_STREAM_DUMP");
    repeat (8) @(negedge clk);
    rst_n = 1;
    repeat (4) @(negedge clk);
    for (int token=0;token<2;token++) begin
      cfg_valid = 1;
      cfg_tag = 32'h63a10000 + 32'(token);
      do @(posedge clk); while (!cfg_ready);
      @(negedge clk);
      cfg_valid = 0;
      for (int strip=0;strip<256;strip++) begin
        word(strip == 255 ? 16'hA67B : 16'hA67A,1);
        for (int part=0;part<8;part++) word(input_rows[token*256+strip][part*16+:16],0);
      end
      for (int strip=0;strip<256;strip++) begin
        word(strip == 255 ? 16'hA67D : 16'hA67C,1);
        for (int part=0;part<16;part++) word(input_rows[token*256+strip][part*16+:16],0);
      end
      while (rows != 256*(token+1)) @(negedge clk);
    end
    $fclose(file);
    if (stats_received != 512 || replay_received != 512 || host_words != 13312 || held_outputs == 0)
      $fatal(1,"NORMALIZATION_STREAM_COUNTS");
    $display("PACKET_NORMALIZATION_STREAM_PASS stats=512 replay=512 rows=512 host_words=13312 held=%0d",held_outputs);
    $finish;
  end
  initial begin
    #900000;
    $fatal(1,"NORMALIZATION_STREAM_TIMEOUT stats=%0d replay=%0d rows=%0d",stats_received,replay_received,rows);
  end
endmodule
