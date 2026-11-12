`timescale 1ns/1ps

module tri_oracle_channel_weight_repack_tb;
  localparam int HIDDEN = 2048;
  localparam int CHANNELS = 5632;
  localparam int BYTES_PER_MATRIX = HIDDEN * CHANNELS;

  logic clk = 0;
  always #5 clk = ~clk;
  logic rst_n = 0;
  logic cfg_valid = 0, cfg_down = 0, cfg_ready;
  logic [7:0] cfg_keep = 0;
  logic lane_valid = 0, lane_ready;
  logic [2:0] lane_index;
  logic [511:0] lane_data = 0;
  logic beat_valid, beat_ready = 0, beat_last;
  logic [2:0] beat_index;
  logic [511:0] beat_data;
  int requests = 0, outputs = 0;
  string images, pair_path, down_path;

  tri_oracle_channel_weight_repack dut (.*);

  function automatic logic [511:0] read_beat(input int file, input int offset);
    byte unsigned bytes [0:63];
    logic [511:0] value;
    if ($fseek(file, offset, 0) != 0 || $fread(bytes, file) != 64)
      $fatal(1, "CHANNEL_WEIGHT_IMAGE_READ offset=%0d", offset);
    for (int index = 0; index < 64; index++)
      value[index * 8 +: 8] = bytes[index];
    return value;
  endfunction

  task automatic configure(input bit down, input logic [7:0] keep);
    if (!cfg_ready) $fatal(1, "CHANNEL_WEIGHT_CONFIGURATION_BUSY");
    cfg_valid = 1;
    cfg_down = down;
    cfg_keep = keep;
    @(negedge clk);
    cfg_valid = 0;
  endtask

  task automatic offer(input int channel, input logic [511:0] data);
    repeat (2) begin
      if (!lane_ready || lane_index !== 3'(channel) || beat_valid || cfg_ready)
        $fatal(1, "CHANNEL_WEIGHT_REQUEST_EXPECTED channel=%0d", channel);
      @(negedge clk);
    end
    lane_valid = 1;
    lane_data = data;
    @(negedge clk);
    lane_valid = 0;
    requests++;
  endtask

  task automatic replay(input string branch, input int first_channel, input int chunk, input logic [7:0] keep);
    bit down, up;
    int channel_file, legacy_file, address;
    logic [511:0] expected;
    down = branch == "down";
    up = branch == "up";
    channel_file = $fopen({images, "/", branch, ".bin"}, "rb");
    legacy_file = $fopen(down ? down_path : pair_path, "rb");
    if (!channel_file || !legacy_file) $fatal(1, "CHANNEL_WEIGHT_OPEN %s", branch);
    configure(down, keep);
    for (int lane = 0; lane < 8; lane++) begin
      if (keep[lane])
        offer(lane, read_beat(channel_file, (first_channel + lane) * HIDDEN + chunk * 64));
    end
    for (int beat = 0; beat < 8; beat++) begin
      if (down)
        address = ((chunk * 8 + beat) * (CHANNELS / 8) + first_channel / 8) * 64;
      else
        address = (up ? BYTES_PER_MATRIX : 0) + ((first_channel / 8) * (HIDDEN / 8) + chunk * 8 + beat) * 64;
      expected = read_beat(legacy_file, address);
      for (int row = 0; row < 8; row++)
        for (int feature = 0; feature < 8; feature++)
          if (!keep[down ? feature : row]) expected[(row * 8 + feature) * 8 +: 8] = 0;
      repeat (2) begin
        if (!beat_valid || beat_index !== 3'(beat) || beat_last !== (beat == 7) || cfg_ready || lane_ready)
          $fatal(1, "CHANNEL_WEIGHT_BEAT_EXPECTED branch=%s beat=%0d", branch, beat);
        if (beat_data !== expected)
          $fatal(1, "CHANNEL_WEIGHT_PAYLOAD branch=%s beat=%0d keep=%h", branch, beat, keep);
        @(negedge clk);
      end
      beat_ready = 1;
      @(negedge clk);
      beat_ready = 0;
      outputs++;
    end
    $fclose(channel_file);
    $fclose(legacy_file);
    if (!cfg_ready || lane_ready || beat_valid) $fatal(1, "CHANNEL_WEIGHT_TILE_DID_NOT_RELEASE");
  endtask

  initial begin
    if (!$value$plusargs("IMAGES=%s", images) ||
        !$value$plusargs("LEGACY_PAIR=%s", pair_path) ||
        !$value$plusargs("LEGACY_DOWN=%s", down_path))
      $fatal(1, "CHANNEL_WEIGHT_FIXTURES_REQUIRED");
    repeat (2) @(negedge clk);
    rst_n = 1;
    @(negedge clk);
    replay("gate", 0, 0, 8'hff);
    replay("gate", 5624, 31, 8'h85);
    replay("up", 1168, 11, 8'h5a);
    replay("down", 1760, 27, 8'ha5);
    replay("down", 5624, 31, 8'h80);
    replay("down", 0, 0, 8'h00);
    configure(0, 8'h83);
    offer(0, '1);
    rst_n = 0;
    @(negedge clk);
    if (cfg_ready || lane_ready || beat_valid) $fatal(1, "CHANNEL_WEIGHT_RESET_HANDSHAKE");
    rst_n = 1;
    @(negedge clk);
    replay("gate", 8, 2, 8'h02);
    if (requests != 22 || outputs != 56) $fatal(1, "CHANNEL_WEIGHT_COUNTS %0d %0d", requests, outputs);
    $display("CHANNEL_WEIGHT_REPACK_PASS tiles=7 requests=%0d beats=%0d", requests, outputs);
    $finish;
  end

  initial begin
    #100000;
    $fatal(1, "CHANNEL_WEIGHT_TIMEOUT");
  end
endmodule
