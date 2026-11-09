`timescale 1ns / 1ps
module tri_oracle_predicted_gated_fabric_tb;
  localparam int Rows = 160;
  localparam int MaxChannels = 65536;
  localparam int WatchdogCycles = 2000000;
  localparam logic [63:0] ActBase = 64'h100002000;
  localparam logic [63:0] WeightBase = 64'h200004000;
  localparam logic [63:0] UpWeightBase = 64'h400006000;
  logic clk = 0;
  always #5 clk = ~clk;
  logic rst_n = 0, cfg_valid = 0, cfg_ready;
  logic [31:0] cfg_tag = 0;
  logic [63:0] cfg_activation_base = ActBase, cfg_weight_base = WeightBase;
  logic [63:0] cfg_up_weight_base = UpWeightBase;
  logic [5:0] cfg_gate_shift = 8, cfg_up_shift = 8;
  logic [ 9:0] cfg_features = 0;
  logic [16:0] cfg_dense_rows = 0;
  logic in_valid = 0, in_last = 0, in_group_last = 0, in_ready;
  logic [ 10:0] in_group = 0;
  logic [127:0] norm_activations = 0;
  logic [255:0] gate_weight_signs = 0, up_weight_signs = 0;
  logic out_valid, out_ready, out_last, out_fallback, out_error;
  logic [31:0] out_tag;
  logic [7:0] out_count;
  logic [2559:0] out_channels;
  logic [5119:0] out_data;
  logic req_valid, req_ready, rsp_valid = 0, rsp_ready, rsp_last = 0, rsp_error = 0;
  logic [63:0] req_address, rsp_data = 0;
  logic [4:0] req_length;
  int cycle = 0, case_start = 0, checked = 0, seed = 0;
  int strips = 0, dense_rows = 0, mode = 0, keep_limit = 0, fault = 0;
  int expected_total = 0, output_cursor = 0, packets = 0, requests = 0;
  int activation_bytes = 0, weight_bytes = 0, output_age = 0, hold_cycles = 0;
  int expected_ids[MaxChannels];
  logic [31:0] expected_tag;
  logic [63:0] expected_act_base, expected_weight_base, expected_up_base, burst_weight_base;
  int expected_gate_shift = 0, expected_up_shift = 0;
  bit up_weight_burst = 0;
  int pending_matrix = -1, projection_rows = 0, exact_dot_values = 0;
  int projection_reference[Rows];
  int core_instances = 0, cluster_instances = 0;
  int weight_mask_memories = 0, activation_memories = 0, result_memories = 0;
  bit allow_prefix_error = 0;
  bit expect_error = 0, terminal_seen = 0, fault_fired = 0;
  bit memory_active = 0, request_waited = 0, weight_burst = 0, inject_burst = 0;
  int beat = 0, burst_length = 0;
  logic [63:0] address = 0;
  bit request_held = 0, output_held = 0;
  logic [  68:0] held_request;
  logic [7722:0] held_output;
  logic [  19:0] active_cores = 0;

  always_comb begin
    req_ready = !memory_active && !rsp_valid && request_waited && cycle % 4 != 0;
    out_ready = out_valid && output_age >= 4 && cycle % 5 != 0;
  end

  tri_oracle_predicted_gated_fabric dut (.*);
  for (genvar cluster = 0; cluster < 5; cluster++) begin : monitor_clusters
    for (genvar core = 0; core < 4; core++) begin : monitor_cores
`ifdef TRI_ORACLE_SRAM_CLUSTER_BIND_PUBLIC
      always @(posedge clk)
        if (rst_n &&
            dut.fabric.fabric.clusters[cluster].unit.cluster.implementation.cores[core].cmd_valid &&
            dut.fabric.fabric.clusters[cluster].unit.cluster.implementation.cores[core].cmd_ready)
          active_cores[cluster*4+core] = 1;
`else
      always @(posedge clk)
        if (rst_n && dut.fabric.fabric.clusters[cluster].unit.cluster.cores[core].unit.cmd_valid &&
            dut.fabric.fabric.clusters[cluster].unit.cluster.cores[core].unit.cmd_ready)
          active_cores[cluster*4+core] = 1;
`endif
    end
  end

  function automatic int activation_value(input int feature);
    return ((feature * 17 + seed * 11) % 256) - 128;
  endfunction
  function automatic int weight_value(input int channel, feature, phase = 0);
    return phase == 0 ? ((channel*7+feature*13+seed*3) % 256)-128 :
                        ((channel*11+feature*5+seed*7) % 256)-128;
  endfunction
  function automatic int code_value(input longint signed value, input int shift);
    real scaled;
    longint signed rounded;
    scaled = real'(value)/(2.0**shift);
    rounded = scaled < 0 ? -longint'($floor(-scaled+0.5)) :
                           longint'($floor(scaled+0.5));
    return rounded > 32767 ? 32767 : rounded < -32768 ? -32768 : int'(rounded);
  endfunction
  function automatic int gated_value(input longint signed gate_sum, up_sum);
    int g, u, rounded;
    real x, value;
    g = code_value(gate_sum, expected_gate_shift);
    u = code_value(up_sum, expected_up_shift);
    x = real'(g)/256.0;
    value = x/(1.0+$exp(-x))*real'(u);
    rounded = value < 0 ? -$rtoi(-value+0.5) : $rtoi(value+0.5);
    return rounded > 32767 ? 32767 : rounded < -32768 ? -32768 : rounded;
  endfunction

  // Exact scalar sums precede the approximate nonlinear arithmetic check.
  always @(posedge clk) begin : exact_projection_sums
    int channel, reference_sum;
    longint signed scalar;
    if (!rst_n) pending_matrix = -1;
    else begin
      if (dut.fabric.projection_in_valid && dut.fabric.projection_in_ready) begin
        if (dut.fabric.in_gate_shift !== 6'(expected_gate_shift) ||
            dut.fabric.in_up_shift !== 6'(expected_up_shift))
          $fatal(1, "captured gate/up shifts did not reach the shared backend");
        if (dut.fabric.projection_in_weight_base == expected_weight_base) pending_matrix = 0;
        else if (dut.fabric.projection_in_weight_base == expected_up_base) pending_matrix = 1;
        else $fatal(1, "unknown gate/up matrix owner");
        projection_rows = int'(dut.fabric.projection_in_count);
        for (int r = 0; r < projection_rows; r++) begin
          channel = int'(dut.fabric.projection_in_channels[r*16+:16]);
          scalar = 0;
          for (int f = 0; f < strips*8; f++)
            scalar += longint'(activation_value(f))*
                      longint'(weight_value(channel, f, pending_matrix));
          projection_reference[r] = int'(scalar);
        end
      end
      if (dut.fabric.projection_out_valid && dut.fabric.projection_out_ready &&
          !dut.fabric.projection_out_error) begin
        if (pending_matrix < 0) $fatal(1, "projection response has no matrix owner");
        for (int r = 0; r < projection_rows; r++) begin
          reference_sum = projection_reference[r];
          if ($test$plusargs("CORRUPT_DOT_REFERENCE") && pending_matrix == 0 && r == 0)
            reference_sum++;
          if (dut.fabric.projection_out_data[r*32+:32] !== 32'(reference_sum))
            $fatal(1, "exact predicted gated dot mismatch matrix=%0d row=%0d", pending_matrix, r);
          exact_dot_values++;
        end
      end
    end
  end
  // Independent expected prediction outcomes for deliberately constructed signs.
  function automatic bit keep_row(input int channel);
    case (mode)
      0: return 1;
      1: return 0;
      2: return channel % 7 == 0 || channel % 17 == 3;
      3: return channel % 2 == 0;
      4: return channel < keep_limit;
      5: return channel == 65535;
      default: return 0;
    endcase
  endfunction
  function automatic int normalized_value(input int lane, strip);
    if (mode == 0) return 0;
    if (mode == 3) begin
      case (lane)
        0: return 768;
        1: return -768;
        2: return 769;
        3: return -769;
        4: return -32768;
        5: return 32767;
        default: return 0;
      endcase
    end
    if (strip != 0) return 0;
    return lane == 0 ? 1024 : lane == 1 ? -1024 : 0;
  endfunction
  function automatic bit sign_value(input int channel, lane, strip, branch);
    int value;
    bit match_sign;
    value = normalized_value(lane, strip);
    if (mode == 3) begin
      case (channel % 4)
        0: match_sign = 1;
        1: match_sign = branch == 0 ? 0 : lane == 2 || lane == 3;
        2: match_sign = branch == 1;
        default: match_sign = lane == 2 || lane == 3;
      endcase
    end else match_sign = keep_row(channel) || lane == 0;
    return match_sign ? value < 0 : value >= 0;
  endfunction

  always @(posedge clk) begin : peer_and_scoreboard
    logic [63:0] offset, cursor;
    logic activation_request, inject_now, gate_request, up_request;
    logic [63:0] matrix_base;
    int channel, feature;
    longint signed golden, up_golden;
    int wanted, actual, tolerance, up_code;
    if (!rst_n) begin
      cycle <= 0;
      memory_active <= 0;
      rsp_valid <= 0;
      request_waited <= 0;
      request_held = 0;
      output_held  = 0;
      output_age <= 0;
    end else begin
      cycle <= cycle + 1;
      if (cycle - case_start > WatchdogCycles)
        $fatal(1, "PREDICTED_GATED_FABRIC_WATCHDOG seed=%0d cursor=%0d", seed, output_cursor);
      if (request_held && (req_valid !== 1 || {req_address, req_length} !== held_request))
        $fatal(1, "PREDICTED_GATED_FABRIC_REQUEST_CHANGED");
      request_held = req_valid && !req_ready;
      held_request = {req_address, req_length};
      if (req_valid && !request_waited) request_waited <= 1;
      if (req_valid && req_ready) begin
        if (memory_active || req_length == 0 || req_length > 16 || req_address[2:0] != 0)
          $fatal(1, "PREDICTED_GATED_FABRIC_BAD_REQUEST");
        request_waited <= 0;
        memory_active <= 1;
        address <= req_address;
        burst_length <= int'(req_length);
        beat <= 0;
        activation_request = req_address >= expected_act_base &&
            {1'b0, req_address} < {1'b0, expected_act_base} + 65'(strips * 8);
        gate_request = req_address >= expected_weight_base &&
            {1'b0, req_address} < {1'b0, expected_weight_base}+65'(dense_rows*strips*8);
        up_request = req_address >= expected_up_base &&
            {1'b0, req_address} < {1'b0, expected_up_base}+65'(dense_rows*strips*8);
        if (!activation_request && gate_request == up_request)
          $fatal(1, "ambiguous or out-of-range gate/up request");
        matrix_base = up_request ? expected_up_base : expected_weight_base;
        burst_weight_base <= matrix_base;
        up_weight_burst <= up_request;
        weight_burst <= !activation_request;
        inject_now = fault != 0 && !fault_fired && (fault != 4 || output_cursor >= 160) &&
                     (fault != 5 || up_request);
        inject_burst <= inject_now;
        if (inject_now) fault_fired = 1;
        requests++;
        if (activation_request) begin
          activation_bytes += int'(req_length) * 8;
          if ({1'b0, req_address} + 65'(req_length * 8) >
              {1'b0, expected_act_base} + 65'(strips * 8))
            $fatal(1, "PREDICTED_GATED_FABRIC_ACTIVATION_RANGE");
        end else begin
          if (req_address < matrix_base) $fatal(1, "PREDICTED_GATED_FABRIC_WEIGHT_BASE");
          offset  = req_address - matrix_base;
          channel = int'(offset / 64'(strips * 8));
          if (channel >= dense_rows || !keep_row(
                  channel
              ) || offset % 64'(strips * 8) + 64'(req_length * 8) > 64'(strips * 8))
            $fatal(1, "PREDICTED_GATED_FABRIC_UNSELECTED_WEIGHT_READ channel=%0d", channel);
          weight_bytes += int'(req_length) * 8;
        end
      end
      if (memory_active && !rsp_valid && cycle % 3 != 0) begin
        if (inject_burst && fault == 2 && burst_length < 2)
          $fatal(1, "PREDICTED_GATED_FABRIC_EARLY_LAST_CONTROL_NOT_MALFORMED");
        rsp_valid <= 1;
        rsp_error <= inject_burst && (fault == 1 || fault == 4 || fault == 5) && beat == 0;
        rsp_last <= inject_burst && fault == 2 ? 1 :
            beat == burst_length - (inject_burst && fault == 3 ? 0 : 1);
        rsp_data <= 0;
        if (beat < burst_length)
          for (int lane = 0; lane < 8; lane++) begin
            cursor = address + 64'(beat * 8 + lane);
            if (weight_burst) begin
              offset  = cursor - burst_weight_base;
              channel = int'(offset / 64'(strips * 8));
              feature = int'(offset % 64'(strips * 8));
              rsp_data[lane*8+:8] <= 8'(weight_value(channel, feature, up_weight_burst ? 1 : 0));
            end else rsp_data[lane*8+:8] <= 8'(activation_value(int'(cursor - expected_act_base)));
          end
      end
      if (rsp_valid && rsp_ready) begin
        rsp_valid <= 0;
        if (rsp_last) memory_active <= 0;
        else beat <= beat + 1;
      end

      if (output_held &&
          (out_valid !== 1'b1 ||
           {out_count, out_last, out_error, out_fallback, out_tag, out_channels, out_data}
              !== held_output))
        $fatal(1, "PREDICTED_GATED_FABRIC_OUTPUT_CHANGED");
      output_held = out_valid && !out_ready;
      held_output = {out_count, out_last, out_error, out_fallback, out_tag, out_channels, out_data};
      // This counter drives ready; update it after device and checker sampling.
      if (out_valid) output_age <= output_age + 1;
      else output_age <= 0;
      if (output_held) hold_cycles++;
      if (out_valid && out_ready) begin
        if (memory_active || rsp_valid) $fatal(1, "PREDICTED_GATED_FABRIC_EARLY_RESULT");
        if (out_tag !== expected_tag || out_fallback !== 0 || out_count > 160)
          $fatal(1, "PREDICTED_GATED_FABRIC_METADATA");
        if (expect_error && out_error) begin
          if (!out_error || !out_last || out_count != 0 || out_data != 0 || out_channels != 0)
            $fatal(1, "PREDICTED_GATED_FABRIC_ERROR_PACKET");
        end else begin
          if (expect_error && (!allow_prefix_error || out_last))
            $fatal(1, "PREDICTED_GATED_FABRIC_MISSING_TERMINAL_ERROR");
          if (out_error || out_last !== (output_cursor + int'(out_count) == expected_total))
            $fatal(1, "PREDICTED_GATED_FABRIC_LAST_OR_ERROR");
          for (int row = 0; row < Rows; row++) begin
            golden  = 0;
            channel = row < int'(out_count) ? expected_ids[output_cursor+row] : 0;
            if (row < int'(out_count))
              for (int feature_index = 0; feature_index < strips * 8; feature_index++)
              golden += longint'(activation_value(
                  feature_index
              )) * longint'(weight_value(
                  channel, feature_index
              ));
            up_golden = 0;
            if (row < int'(out_count))
              for (int f = 0; f < strips*8; f++)
                up_golden += longint'(activation_value(f))*longint'(weight_value(channel, f, 1));
            wanted = gated_value(golden, up_golden);
            actual = int'($signed(out_data[row*32+:32]));
            up_code = code_value(up_golden, expected_up_shift);
            tolerance = (2*(up_code < 0 ? -up_code : up_code)+255)/256+1;
            if (out_channels[row*16+:16] !== 16'(channel) ||
                (^out_data[row*32+:32]) === 1'bx || actual-wanted > tolerance ||
                wanted-actual > tolerance || (row >= int'(out_count) && actual != 0))
              $fatal(1, "PREDICTED_GATED_FABRIC_REFERENCE row=%0d channel=%0d", row, channel);
          end
          output_cursor += int'(out_count);
        end
        packets++;
        output_age <= 0;
        if (out_last) terminal_seen = 1;
      end
    end
  end

  task automatic send_strip(input int group_index, strip_index, malformed);
    begin : send_one
      @(negedge clk);
      if (terminal_seen) disable send_one;
      in_valid = 1;
      in_group = 11'(group_index);
      in_last = strip_index == strips - 1;
      in_group_last = group_index == dense_rows / 32 - 1;
      if (malformed == 1) in_group = 11'(group_index + 1);
      if (malformed == 2 && strip_index == 0) in_last = 1;
      if (malformed == 3) in_group_last = !in_group_last;
      if (malformed == 4) in_last = strip_index == strips;
      if (malformed == 5 && strip_index != 0) in_group = 11'(group_index + 1);
      if ((malformed == 6 || malformed == 7) && group_index == dense_rows / 32 - 1)
        in_group = 11'(group_index - 1);
      for (int lane = 0; lane < 8; lane++)
      norm_activations[lane*16+:16] = 16'(normalized_value(lane, strip_index));
      for (int row = 0; row < 32; row++)
      for (int lane = 0; lane < 8; lane++) begin
        gate_weight_signs[row*8+lane] = sign_value(group_index * 32 + row, lane, strip_index, 0);
        up_weight_signs[row*8+lane]   = sign_value(group_index * 32 + row, lane, strip_index, 1);
      end
      @(posedge clk);
      while (!in_ready && !terminal_seen) @(posedge clk);
      @(negedge clk);
      in_valid = 0;
    end
  endtask

  task automatic run_case(input int row_count, feature_strips, pattern, limit, bad_config,
                          bus_fault, malformed, case_seed, gate_shift = 8, up_shift = 8);
    int before_cycle;
    begin
      @(negedge clk);
      while (!cfg_ready) @(negedge clk);
      seed = case_seed;
      case_start = cycle;
      strips = feature_strips;
      dense_rows = row_count;
      mode = pattern;
      keep_limit = limit;
      fault = bus_fault;
      expect_error = bad_config != 0 || bus_fault != 0 || malformed != 0;
      allow_prefix_error = malformed == 7 || bus_fault == 4;
      expected_total = 0;
      for (int channel = 0; channel < dense_rows; channel++)
      if (keep_row(channel)) begin
        expected_ids[expected_total] = channel;
        expected_total++;
      end
      output_cursor = 0;
      packets = 0;
      requests = 0;
      weight_bytes = 0;
      activation_bytes = 0;
      hold_cycles = 0;
      active_cores = 0;
      terminal_seen = 0;
      fault_fired = 0;
      expected_tag = 32'hd1000000 + 32'(case_seed);
      cfg_tag = expected_tag;
      cfg_activation_base = ActBase;
      cfg_weight_base = WeightBase;
      cfg_up_weight_base = UpWeightBase;
      cfg_gate_shift = 6'(gate_shift);
      cfg_up_shift = 6'(up_shift);
      cfg_features = 10'(feature_strips);
      cfg_dense_rows = 17'(row_count);
      case (bad_config)
        1: cfg_features = 0;
        2: cfg_features = 513;
        3: cfg_dense_rows = 31;
        4: cfg_dense_rows = 65537;
        5: cfg_activation_base = ActBase + 1;
        6: cfg_weight_base = 64'hfffffffffffffff8;
        7: cfg_activation_base = 64'hfffffffffffffff8;
        8: cfg_activation_base = 64'hffffffffffffffff - 64'(feature_strips * 8) + 1;
        9: cfg_weight_base = 64'hffffffffffffffff - 64'(row_count * feature_strips * 8) + 1;
        10: cfg_up_weight_base = UpWeightBase+1;
        11: cfg_up_weight_base = 64'hfffffffffffffff8;
        12: cfg_up_weight_base = 64'hffffffffffffffff - 64'(row_count*feature_strips*8)+1;
        default: begin
        end
      endcase
      if (bad_config == 8 || bad_config == 9 || bad_config == 12) expect_error = 0;
      expected_act_base = cfg_activation_base;
      expected_weight_base = cfg_weight_base;
      expected_up_base = cfg_up_weight_base;
      expected_gate_shift = int'(cfg_gate_shift);
      expected_up_shift = int'(cfg_up_shift);
      cfg_valid = 1;
      @(posedge clk);
      if (!cfg_ready) $fatal(1, "PREDICTED_GATED_FABRIC_CONFIG_NOT_ACCEPTED");
      @(negedge clk);
      cfg_valid = 0;
      cfg_tag = 0;
      cfg_activation_base = 0;
      cfg_weight_base = 0;
      cfg_up_weight_base = 0;
      cfg_gate_shift = 0;
      cfg_up_shift = 0;
      cfg_features = 0;
      cfg_dense_rows = 0;
      if (bad_config == 0 || bad_config == 8 || bad_config == 9 || bad_config == 12)
        for (int group_index = 0; group_index < dense_rows / 32 && !terminal_seen; group_index++)
        for (
            int strip_index = 0;
            strip_index < strips + (malformed == 4 ? 1 : 0) && !terminal_seen;
            strip_index++
        )
        send_strip(group_index, strip_index, malformed);
      before_cycle = cycle;
      while (!terminal_seen) @(negedge clk);
      @(negedge clk);
      in_valid = 0;
      if (!expect_error) begin
        if (activation_bytes != 2 * (expected_total / 160 * 5 +
            ((expected_total % 160 + 31) / 32)) * strips * 8)
          $fatal(1, "PREDICTED_GATED_FABRIC_ACTIVATION_TRAFFIC");
        if (output_cursor != expected_total || packets != (expected_total == 0 ? 1 :
            (expected_total + 159) / 160) || weight_bytes != 2 * expected_total * strips * 8)
          $fatal(1, "PREDICTED_GATED_FABRIC_COUNT_OR_TRAFFIC");
        if (expected_total >= 160 && strips >= 4 && active_cores !== 20'hfffff)
          $fatal(1, "PREDICTED_GATED_FABRIC_NOT_ALL_TWENTY_CORES");
      end else if (allow_prefix_error && (output_cursor != 160 || weight_bytes != 2 * 160 * strips * 8))
        $fatal(1, "PREDICTED_GATED_FABRIC_PREFIX_ERROR_ACCOUNTING");
      else if (!allow_prefix_error && (bad_config > 0 || malformed > 0) && requests != 0)
        $fatal(1, "PREDICTED_GATED_FABRIC_READ_AFTER_BAD_INPUT");
      if (hold_cycles == 0 || !cfg_ready) $fatal(1, "PREDICTED_GATED_FABRIC_HOLD_OR_RECOVERY");
      checked++;
      $display("PREDICTED_GATED_FABRIC_CASE_PASS seed=%0d selected=%0d packets=%0d error=%0d", seed,
               expected_total, packets, expect_error);
    end
  endtask

  initial begin
    #1;
    if (core_instances != 20 || cluster_instances != 5 || weight_mask_memories != 360 ||
        activation_memories != 40 || result_memories != 200)
      $fatal(1, "prediction/gate/up actual compiled hierarchy mismatch");
    $display("PREDICTED_GATED_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=600");
    repeat (3) @(negedge clk);
    rst_n = 1;
    run_case(192, 4, 0, 0, 0, 0, 0, 0);
    if (!$test$plusargs("SMOKE")) begin
      run_case(352, 5, 0, 0, 0, 0, 0, 1);
      run_case(192, 4, 2, 0, 0, 0, 0, 2);
      run_case(64, 4, 1, 0, 0, 0, 0, 3);
      run_case(64, 5, 3, 0, 0, 0, 0, 4);
      for (int count = 0; count < 7; count++)
      run_case(192, 4, 4,
               count == 0 ? 31 : count == 1 ? 32 : count == 2 ? 33 :
                 count == 3 ? 159 : count == 4 ? 160 : count == 5 ? 161 : 0,
               0, 0, 0, 5 + count);
      run_case(65536, 1, 5, 0, 0, 0, 0, 12);
      run_case(32, 512, 4, 1, 0, 0, 0, 13);
      for (int bad = 1; bad <= 7; bad++) run_case(32, 4, 0, 0, bad, 0, 0, 13 + bad);
      for (int bad = 8; bad <= 9; bad++) run_case(32, 4, 0, 0, bad, 0, 0, 13 + bad);
      for (int bad = 1; bad <= 3; bad++) begin
        run_case(32, 2, 0, 0, 0, 0, bad, 22 + bad);
        run_case(32, 1, 0, 0, 0, 0, 0, 25 + bad);
      end
      for (int bus_fault = 1; bus_fault <= 3; bus_fault++) begin
        run_case(192, 8, 0, 0, 0, bus_fault, 0, 28 + bus_fault);
        run_case(32, 1, 2, 0, 0, 0, 0, 31 + bus_fault);
      end
    end

    if (!$test$plusargs("SMOKE")) begin
      fork : reset_0
        begin
          run_case(192, 8, 0, 0, 0, 0, 0, 35);
          $fatal(1, "PREDICTED_GATED_FABRIC_RESET_TOO_LATE");
        end
        begin
          wait (req_valid && !req_ready);
          @(negedge clk);
          rst_n = 0;
          in_valid = 0;
          cfg_valid = 0;
          repeat (3) @(negedge clk);
          rst_n = 1;
        end
      join_any
      // Cancel the branch and any suspended automatic-task activity it owns.
      disable fork;
      checked++;
      $display("PREDICTED_GATED_FABRIC_CASE_PASS reset=0");
      run_case(32, 1, 2, 0, 0, 0, 0, 36);
    end

    if (!$test$plusargs("SMOKE")) begin
      fork : reset_1
        begin
          run_case(192, 8, 0, 0, 0, 0, 0, 37);
          $fatal(1, "PREDICTED_GATED_FABRIC_RESET_TOO_LATE");
        end
        begin
          wait (memory_active && rsp_valid && !rsp_last);
          @(negedge clk);
          rst_n = 0;
          in_valid = 0;
          cfg_valid = 0;
          repeat (3) @(negedge clk);
          rst_n = 1;
        end
      join_any
      disable fork;
      checked++;
      $display("PREDICTED_GATED_FABRIC_CASE_PASS reset=1");
      run_case(32, 1, 2, 0, 0, 0, 0, 38);
    end

    if (!$test$plusargs("SMOKE")) begin
      fork : reset_2
        begin
          run_case(192, 8, 0, 0, 0, 0, 0, 39);
          $fatal(1, "PREDICTED_GATED_FABRIC_RESET_TOO_LATE");
        end
        begin
          wait (out_valid && !out_ready);
          @(negedge clk);
          rst_n = 0;
          in_valid = 0;
          cfg_valid = 0;
          repeat (3) @(negedge clk);
          rst_n = 1;
        end
      join_any
      disable fork;
      checked++;
      $display("PREDICTED_GATED_FABRIC_CASE_PASS reset=2");
      run_case(32, 1, 2, 0, 0, 0, 0, 40);
    end
    if (!$test$plusargs("SMOKE")) begin
      run_case(32, 1, 0, 0, 0, 0, 4, 41);
      run_case(32, 1, 2, 0, 0, 0, 0, 42);
      run_case(64, 2, 0, 0, 0, 0, 5, 43);
      run_case(32, 1, 2, 0, 0, 0, 0, 44);
      run_case(192, 2, 0, 0, 0, 0, 6, 45);
      run_case(32, 1, 2, 0, 0, 0, 0, 46);
      run_case(352, 4, 0, 0, 0, 0, 7, 47);
      run_case(32, 1, 2, 0, 0, 0, 0, 48);
      run_case(352, 8, 0, 0, 0, 4, 0, 49);
      run_case(32, 1, 2, 0, 0, 0, 0, 50);
    end
    if (!$test$plusargs("SMOKE")) begin
      for (int bad = 10; bad <= 12; bad++)
        run_case(32, 4, 0, 0, bad, 0, 0, 41+bad);
      run_case(5632, 4, 0, 0, 0, 0, 0, 54);
      run_case(5632, 256, 4, 1, 0, 0, 0, 55);
      run_case(192, 8, 0, 0, 0, 5, 0, 56);
      run_case(32, 1, 2, 0, 0, 0, 0, 57);
      run_case(192, 68, 0, 0, 0, 0, 0, 58, 7, 12);
      run_case(192, 68, 0, 0, 0, 0, 0, 59, 12, 7);
      if (exact_dot_values < 11264) $fatal(1, "exact projection comparisons did not execute");
    end
    $display("PREDICTED_GATED_EXACT_DOTS_PASS values=%0d", exact_dot_values);
    $display("PREDICTED_GATED_FABRIC_PASS cases=%0d", checked);
    $finish;
  end
endmodule

module tri_oracle_predicted_gated_instance_count #(parameter int KIND = 0) ();
  initial begin
    case (KIND)
      0: $root.tri_oracle_predicted_gated_fabric_tb.core_instances++;
      1: $root.tri_oracle_predicted_gated_fabric_tb.cluster_instances++;
      2: $root.tri_oracle_predicted_gated_fabric_tb.weight_mask_memories++;
      3: $root.tri_oracle_predicted_gated_fabric_tb.activation_memories++;
      4: $root.tri_oracle_predicted_gated_fabric_tb.result_memories++;
    endcase
  end
endmodule

bind tri_oracle_sram_memory_compute tri_oracle_predicted_gated_instance_count
    #(.KIND(0)) count_actual_core ();
bind tri_oracle_sram_compute_cluster tri_oracle_predicted_gated_instance_count
    #(.KIND(1)) count_actual_cluster ();
bind TS5N28HPCPSVTA32X128M2FW tri_oracle_predicted_gated_instance_count
    #(.KIND(2)) count_actual_weight_mask ();
bind TS5N28HPCPSVTA512X64M4F tri_oracle_predicted_gated_instance_count
    #(.KIND(3)) count_actual_activation ();
bind TS6N28HPCPSVTA16X128M2F tri_oracle_predicted_gated_instance_count
    #(.KIND(4)) count_actual_result ();
