`timescale 1ns/1ps
// One direct computational-block case. Encoded raw/gain are actual encoder
// producer outputs; normalized codes/three planar feature masks are checker-only.
module tri_oracle_prefix_normalizer_tb_v1;
  localparam int Strips = 256;
  localparam logic [31:0] Tag = 32'h50524630;
  localparam logic [63:0] Epsilon = 64'd12089258196146291747;
  localparam logic signed [7:0] GammaExponent = -8'sd23;
  localparam logic signed [8:0] ActivationExponent = -9'sd8;
  logic clk = 0, rst_n = 0, cfg_valid = 0, cfg_ready;
  logic [31:0] cfg_tag = Tag;
  logic [9:0] cfg_strips = 10'd256;
  logic [63:0] cfg_epsilon_q16 = Epsilon;
  logic signed [7:0] cfg_gamma_exponent = GammaExponent;
  logic stats_valid = 0, stats_ready, stats_last = 0;
  logic replay_valid = 0, replay_ready, replay_last = 0;
  logic [255:0] stats_data = 0, replay_data = 0;
  logic [191:0] stats_gamma = 0, replay_gamma = 0;
  logic out_valid, out_ready, out_last, out_error;
  logic [31:0] out_tag;
  logic [9:0] out_index;
  logic [3:0] out_count;
  logic [63:0] out_activation;
  logic signed [8:0] out_exponent;
  logic [7:0] out_outlier_mask, out_outlier_negative, out_normalized_negative;
  byte unsigned raw_bytes[], gain_bytes[], code_bytes[], feature_bytes[];
  logic [2:0] first_output_hold_samples = 0;
  logic held_output = 0;
  logic [144:0] held_output_payload = 0;
  int cycles = 0, configs = 0, stats_count = 0, replay_count = 0;
  int output_count = 0, output_stalls = 0, outlier_count = 0;
  bit omit_input_valid;
  string input_root, gold_root, source_manifest_sha, packing_sha;

  tri_oracle_fused_input_sign_normalizer_wide_v1 #(.GAMMA_BITS(24)) dut (.*);
  always #5 clk = ~clk;
  // Progress before any offer, then four sampled holds of the first real offer.
  // The real block's out_valid depends on its Output/Error state, not out_ready.
  always_comb begin
    out_ready = rst_n && (!out_valid || first_output_hold_samples == 3'd4);
  end

  function automatic logic [255:0] raw_packet(input int strip);
    logic [255:0] packet;
    for (int b = 0; b < 32; b++) packet[b*8+:8] = raw_bytes[strip*32+b];
    return packet;
  endfunction
  function automatic logic [191:0] gain_packet(input int strip);
    logic [191:0] packet;
    for (int b = 0; b < 24; b++) packet[b*8+:8] = gain_bytes[strip*24+b];
    return packet;
  endfunction
  function automatic logic [63:0] expected_codes(input int strip);
    logic [63:0] packet;
    for (int b = 0; b < 8; b++) packet[b*8+:8] = code_bytes[strip*8+b];
    return packet;
  endfunction
  // Dynamic target + allocation matches the independently exercised loader API.
  task automatic load_exact(input string path, input int count, ref byte unsigned target[]);
    int handle, n, tail;
    handle = $fopen(path, "rb");
    if (handle == 0) $fatal(1, "PREFIX_NORMALIZER_REQUIRED_FILE_MISSING path=%s", path);
    target = new[count];
    n = $fread(target, handle);
    tail = $fgetc(handle);
    $fclose(handle);
    if (n != count || tail != -1)
      $fatal(1, "PREFIX_NORMALIZER_REQUIRED_FILE_WRONG_SIZE path=%s got=%0d", path, n);
  endtask

  // All checks sample the pre-update rising-edge offers and handshakes.
  always @(posedge clk) begin
    cycles++;
    if (cycles > 100000) $fatal(1, "PREFIX_NORMALIZER_WATCHDOG");
    if (rst_n) begin
      if ($isunknown({cfg_ready, stats_ready, replay_ready, out_valid, out_ready}))
        $fatal(1, "PREFIX_NORMALIZER_UNKNOWN_CONTROL");
      if (held_output && (!out_valid || {out_last, out_error, out_tag, out_index,
          out_count, out_activation, out_exponent, out_outlier_mask,
          out_outlier_negative, out_normalized_negative} !== held_output_payload))
        $fatal(1, "PREFIX_NORMALIZER_HELD_OUTPUT_CHANGED");
      held_output = out_valid && !out_ready;
      held_output_payload = {out_last, out_error, out_tag, out_index, out_count,
          out_activation, out_exponent, out_outlier_mask, out_outlier_negative,
          out_normalized_negative};
      if (out_valid) begin
        if ($isunknown(held_output_payload) || out_error)
          $fatal(1, "PREFIX_NORMALIZER_UNKNOWN_OR_ERROR_OUTPUT");
        if (!out_ready) begin
          output_stalls++;
          if (first_output_hold_samples < 3'd4)
            first_output_hold_samples <= first_output_hold_samples + 3'd1;
        end
      end
      if (cfg_valid && cfg_ready) begin
        if (configs != 0 || cfg_tag !== Tag || cfg_strips !== 10'd256 ||
            cfg_epsilon_q16 !== Epsilon || !cfg_epsilon_q16[63] ||
            cfg_gamma_exponent !== GammaExponent)
          $fatal(1, "PREFIX_NORMALIZER_CONFIG_MISMATCH");
        configs++;
        $display("PREFIX_NORMALIZER_CONFIG tag=%08h strips=%0d epsilon=%016h gamma_exponent=%0d", cfg_tag, cfg_strips, cfg_epsilon_q16, $signed(cfg_gamma_exponent));
      end
      if (stats_valid && stats_ready) begin
        if (configs != 1 || stats_count >= Strips || replay_count != 0 ||
            stats_data !== raw_packet(stats_count) || stats_gamma !== gain_packet(stats_count) ||
            stats_last !== (stats_count == Strips-1))
          $fatal(1, "PREFIX_NORMALIZER_STATS_MISMATCH");
        $display("PREFIX_NORMALIZER_STATS index=%0d raw=%064h gain=%048h last=%0b", stats_count, stats_data, stats_gamma, stats_last);
        stats_count++;
      end
      if (replay_valid && replay_ready) begin
        if (stats_count != Strips || replay_count >= Strips ||
            replay_data !== raw_packet(replay_count) || replay_gamma !== gain_packet(replay_count) ||
            replay_last !== (replay_count == Strips-1))
          $fatal(1, "PREFIX_NORMALIZER_REPLAY_MISMATCH");
        $display("PREFIX_NORMALIZER_REPLAY index=%0d raw=%064h gain=%048h last=%0b", replay_count, replay_data, replay_gamma, replay_last);
        replay_count++;
      end
      if (out_valid && out_ready) begin
        if (configs != 1 || stats_count != Strips || output_count >= Strips ||
            replay_count != output_count+1 || out_tag !== Tag ||
            out_index !== 10'(output_count) || out_count !== 4'd8 ||
            out_last !== (output_count == Strips-1) || out_exponent !== ActivationExponent)
          $fatal(1, "PREFIX_NORMALIZER_OUTPUT_METADATA_MISMATCH");
        // Planes: outliers[0:256], normalized-negative[256:512], outlier-negative[512:768].
        if (out_activation !== expected_codes(output_count) ||
            out_outlier_mask !== feature_bytes[output_count] ||
            out_normalized_negative !== feature_bytes[256+output_count] ||
            out_outlier_negative !== feature_bytes[512+output_count])
          $fatal(1, "PREFIX_NORMALIZER_OUTPUT_BYTES_MISMATCH index=%0d", output_count);
        for (int lane = 0; lane < 8; lane++) if (out_outlier_mask[lane]) outlier_count++;
        $display("PREFIX_NORMALIZER_OUTPUT index=%0d count=%0d last=%0b error=%0b exponent=%0d codes=%016h outliers=%02h signs=%02h outlier_negative=%02h", out_index, out_count, out_last, out_error, $signed(out_exponent), out_activation, out_outlier_mask, out_normalized_negative, out_outlier_negative);
        output_count++;
      end
    end
  end

  task automatic provide_pass(input bit replay_pass);
    for (int strip = 0; strip < Strips; strip++) begin
      @(negedge clk);
      if (replay_pass) begin
        replay_valid = 1; replay_data = raw_packet(strip);
        replay_gamma = gain_packet(strip); replay_last = strip == Strips-1;
      end else begin
        stats_valid = 1; stats_data = raw_packet(strip);
        stats_gamma = gain_packet(strip); stats_last = strip == Strips-1;
      end
      do @(posedge clk); while (replay_pass ? !replay_ready : !stats_ready);
      @(negedge clk);
      if (replay_pass) replay_valid = 0; else stats_valid = 0;
    end
  endtask

  initial begin
    if (!$value$plusargs("PREFIX_INPUT_ROOT=%s", input_root) ||
        !$value$plusargs("PREFIX_GOLD_ROOT=%s", gold_root) ||
        !$value$plusargs("PREFIX_SOURCE_MANIFEST_SHA=%s", source_manifest_sha) ||
        !$value$plusargs("PREFIX_PACKING_SHA=%s", packing_sha))
      $fatal(1, "PREFIX_NORMALIZER_AUTHENTICATED_CONTEXT_REQUIRED");
    if (source_manifest_sha != "3c7768f3ac08cfcc34ec8211c60140c136bf9f10dc14de6aacfaa3d0ad70ba53" ||
        packing_sha != "5481866dac040b76e6b7eb5393140e5aabe88cb5881e72786074ba70a9f1055d")
      $fatal(1, "PREFIX_NORMALIZER_CONTEXT_DIGEST_MISMATCH");
    omit_input_valid = $test$plusargs("PREFIX_OMIT_INPUT_VALID");
    load_exact({input_root, "/actual_encoder_raw_i32_le.bin"}, 8192, raw_bytes);
    load_exact({input_root, "/actual_encoder_gamma_i24_le.bin"}, 6144, gain_bytes);
    load_exact({gold_root, "/expected_C_codes_i8.bin"}, 2048, code_bytes);
    load_exact({gold_root, "/expected_C_features_planes.bin"}, 768, feature_bytes);
    $display("PREFIX_NORMALIZER_BEGIN manifest=%s packing=%s omitted_inputs=%0b features=2048 gamma_bits=24", source_manifest_sha, packing_sha, omit_input_valid);
    repeat (4) @(negedge clk);
    rst_n = 1;
    @(negedge clk); cfg_valid = 1;
    do @(posedge clk); while (!cfg_ready);
    @(negedge clk); cfg_valid = 0;
    if (omit_input_valid) begin
      repeat (512) @(negedge clk);
      if (configs != 1 || stats_count != 0 || replay_count != 0 || output_count != 0 ||
          !stats_ready || cfg_ready || out_valid)
        $fatal(1, "PREFIX_NORMALIZER_OMIT_GUARD_PRECONDITION_FAILED");
      $fatal(1, "PREFIX_NORMALIZER_EXPECTED_COMPLETE_OUTPUT cfg=%0d stats=%0d replay=%0d outputs=%0d", configs, stats_count, replay_count, output_count);
    end
    provide_pass(0);
    provide_pass(1);
    do @(negedge clk); while (output_count != Strips);
    repeat (2) @(negedge clk);
    if (configs != 1 || stats_count != Strips || replay_count != Strips ||
        output_count != Strips || outlier_count != 0 || first_output_hold_samples != 3'd4 ||
        output_stalls < 4 || !cfg_ready || out_valid || held_output)
      $fatal(1, "PREFIX_NORMALIZER_FINAL_COUNTS_OR_IDLE_FAILED");
    $display("PREFIX_NORMALIZER_PASS configs=%0d stats=%0d replay=%0d outputs=%0d lanes=2048 outliers=%0d exponent=-8 held_samples=%0d stalls=%0d epsilon_msb=1", configs, stats_count, replay_count, output_count, outlier_count, first_output_hold_samples, output_stalls);
    $finish;
  end
endmodule
