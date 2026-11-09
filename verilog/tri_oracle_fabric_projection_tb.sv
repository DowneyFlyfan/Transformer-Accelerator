`timescale 1ns / 1ps
// Updated to modern SystemVerilog
// Independent signed dot products through the real five four-core clusters.
module tri_oracle_fabric_projection_tb;
  localparam int Rows = 160;
  localparam int Lanes = 8;
  localparam int SumBits = 32;
  localparam int IdBits = 16;
  localparam int TimeoutCycles = 1500000;
  localparam int HoldCycles = 6;
  localparam int MaxBurst = 16;
  localparam logic [63:0] ActBase = 64'h100002000;
  localparam logic [63:0] WeightBase = 64'h200004000;
  logic clk = 0;
  always #5 clk = ~clk;
  logic rst_n = 0, in_valid = 0, in_last = 0, in_fallback = 0, out_ready = 0;
  logic [31:0] in_tag = 0;
  logic [7:0] in_count = 0;
  logic [2559:0] in_channels = 0;
  logic [63:0] in_activation_base = ActBase, in_weight_base = WeightBase;
  logic [9:0] in_features = 0;
  logic in_ready, out_valid, out_last, out_fallback, out_error;
  logic [31:0] out_tag;
  logic [7:0] out_count;
  logic [2559:0] out_channels;
  logic [5119:0] out_data;
  logic req_valid, req_ready, rsp_ready;
  logic [63:0] req_address;
  logic [ 4:0] req_length;
  logic rsp_valid = 0, rsp_last = 0, rsp_error = 0;
  logic [63:0] rsp_data = 0;
  int cycle = 0, strips = 0, rows = 0, seed = 0, fault_mode = 0;
  int fault_style = 0, fault_scope = 0;
  int checked = 0, requests = 0, activation_bytes = 0, weight_bytes = 0;
  int commands = 0, request_stalls = 0;
  int beat = 0, burst_length = 0;
  logic memory_active = 0, request_waited = 0, inject_burst = 0, fault_fired = 0;
  logic [  63:0] address = 0;
  logic [2559:0] expected_channels;
  logic [63:0] expected_activation_base, expected_weight_base;
  logic weight_burst = 0;
  logic [31:0] expected_tag;
  logic expected_last, expected_fallback;
  longint signed expected[Rows];
  logic request_held = 0;
  logic [68:0] held_request;
  int cluster_commands[5];
  int owner_requests[5];
  bit abort_offer_seen = 0, abort_accept_seen = 0;
  int after_fault_wait = 0;

  always_comb
    req_ready = !memory_active && !rsp_valid &&
      (request_waited || (fault_mode == 11 && fault_fired)) && cycle % 4 != 0 &&
      !(fault_mode == 10 && fault_fired && after_fault_wait < 8);
  for (genvar cluster = 0; cluster < 5; cluster++) begin : command_monitors
    always @(posedge clk) begin
      if (rst_n && dut.clusters[cluster].unit.cluster_cmd_valid &&
          dut.clusters[cluster].unit.cluster_cmd_ready) begin
        if (dut.clusters[cluster].unit.cluster_cmd_output !==
            4'(cluster_commands[cluster] % MaxBurst))
          $fatal(1, "WRONG_CLUSTER_DESTINATION_SLOT");
        cluster_commands[cluster]++;
        commands++;
      end
    end
  end
  tri_oracle_fabric_projection dut (.*);

  function automatic int activation_value(input int feature);
    return ((feature * 17 + seed * 11) % 256) - 128;
  endfunction
  function automatic int weight_value(input int channel, feature);
    return ((channel * 7 + feature * 13 + seed * 3) % 256) - 128;
  endfunction
  function automatic bit selected(input int channel);
    selected = 0;
    for (int row = 0; row < rows && row < Rows; row++)
    if (channel == int'(expected_channels[row*IdBits+:IdBits])) selected = 1;
  endfunction

  always @(posedge clk) begin : memory_peer
    logic [63:0] offset, cursor;
    logic activation_request, inject_now;
    int channel, feature;
    if (!rst_n) begin
      cycle <= 0;
      memory_active <= 0;
      rsp_valid <= 0;
      request_waited <= 0;
    end else begin
      cycle <= cycle + 1;
      // This wait count drives ready; commit it after all clock-edge sampling.
      if (fault_fired && !memory_active) after_fault_wait <= after_fault_wait + 1;
      if (dut.fault_now && req_valid && !req_ready) abort_offer_seen = 1;
      if (dut.fault_now && ((req_valid && req_ready) || dut.busy)) abort_accept_seen = 1;
      if (out_valid && (memory_active || rsp_valid))
        $fatal(1, "EARLY_FABRIC_RESULT_WITH_OWNED_RESPONSE");
      if (req_valid !== 1'b0 && req_valid !== 1'b1) $fatal(1, "UNKNOWN_REQUEST_VALID");
      if (request_held && (req_valid !== 1'b1 || {req_address, req_length} !== held_request))
        $fatal(1, "UNSTABLE_MEMORY_REQUEST");
      request_held = req_valid && !req_ready;
      held_request = {req_address, req_length};
      if (request_held) request_stalls++;
      if (req_valid && !request_waited) request_waited <= 1;
      if (req_valid && req_ready) begin
        if (req_length == 0 || req_length > MaxBurst || req_address[2:0] != 0)
          $fatal(1, "BAD_REQUEST_SHAPE");
        request_waited <= 0;
        memory_active <= 1;
        address <= req_address;
        burst_length <= int'(req_length);
        beat <= 0;
        activation_request = req_address >= expected_activation_base &&
            {1'b0, req_address} < {1'b0, expected_activation_base} + 65'(strips * Lanes);
        weight_burst <= !activation_request;
        inject_now = fault_mode != 0 && !fault_fired &&
            ((fault_scope == 0 && activation_request) ||
             (fault_scope == 1 && !activation_request) ||
             (fault_scope == 2 && !activation_request && commands >= MaxBurst));
        inject_burst <= inject_now;
        fault_fired  <= fault_fired || inject_now;
        if (dut.offer_owner >= 5) $fatal(1, "BAD_MEMORY_OWNER");
        if (fault_mode == 0 && requests < (rows + 31) / 32 && dut.offer_owner !== 3'(requests))
          $fatal(1, "UNFAIR_INITIAL_MEMORY_OWNERS");
        requests++;
        owner_requests[dut.offer_owner]++;
        if (!activation_request) begin
          if (req_address < expected_weight_base) $fatal(1, "ALIASED_WEIGHT_BASE");
          offset  = req_address - expected_weight_base;
          channel = int'(offset / 64'(strips * Lanes));
          if (!selected(
                  channel
              ) || offset % 64'(strips * Lanes) + 64'(req_length * Lanes) > 64'(strips * Lanes))
            $fatal(1, "WRONG_ORIGINAL_WEIGHT_ROW_OR_STRIDE");
          weight_bytes += int'(req_length) * Lanes;
        end else begin
          if ({1'b0, req_address} + 65'(req_length * Lanes) >
              {1'b0, expected_activation_base} + 65'(strips * Lanes))
            $fatal(1, "PADDING_OR_ALIASED_ACTIVATION_READ");
          activation_bytes += int'(req_length) * Lanes;
        end
      end
      if (memory_active && !rsp_valid && cycle % 3 != 0) begin
        rsp_valid <= 1;
        rsp_error <= inject_burst && fault_style == 1 && beat == 0;
        if (inject_burst && fault_style == 2) rsp_last <= 1;
        else if (inject_burst && fault_style == 3) rsp_last <= beat == burst_length;
        else rsp_last <= beat == burst_length - 1;
        for (int lane = 0; lane < Lanes; lane++) begin
          cursor = address + 64'(beat * Lanes + lane);
          if (weight_burst) begin
            offset  = cursor - expected_weight_base;
            channel = int'(offset / 64'(strips * Lanes));
            feature = int'(offset % 64'(strips * Lanes));
            rsp_data[lane*8+:8] <= 8'(weight_value(channel, feature));
          end else
            rsp_data[lane*8+:8] <= 8'(activation_value(int'(cursor - expected_activation_base)));
        end
      end
      if (rsp_valid && rsp_ready) begin
        rsp_valid <= 0;
        if (rsp_last) memory_active <= 0;
        else beat <= beat + 1;
      end

    end
  end

  task automatic launch(input int feature_strips, row_count, fault, bad_config, case_seed);
    int channel;
    begin
      @(negedge clk);
      if (!in_ready || memory_active || rsp_valid) $fatal(1, "CONTEXT_NOT_IDLE");
      strips = feature_strips;
      rows = row_count;
      seed = case_seed;
      fault_mode = fault;
      fault_style = fault >= 10 ? 1 : (fault == 0 ? 0 : (fault - 1) % 3 + 1);
      fault_scope = fault >= 10 ? 0 : (fault == 0 ? 0 : (fault - 1) / 3);
      fault_fired = 0;
      abort_offer_seen = 0;
      abort_accept_seen = 0;
      after_fault_wait = 0;
      for (int cluster = 0; cluster < 5; cluster++) begin
        cluster_commands[cluster] = 0;
        owner_requests[cluster]   = 0;
      end
      requests = 0;
      activation_bytes = 0;
      weight_bytes = 0;
      commands = 0;
      request_stalls = 0;
      in_channels = 0;
      for (int row = 0; row < Rows; row++) begin
        channel = row % 3 == 0 ? 65535 - row : (row % 3 == 1 ? row * 17 : 500 + row);
        in_channels[row*IdBits+:IdBits] = IdBits'(channel);
        expected[row] = 0;
        if (row < row_count && !(bad_config > 0 && bad_config < 6) &&
            bad_config != 8 && bad_config != 9 && fault == 0)
          for (int feature = 0; feature < feature_strips * Lanes; feature++)
          expected[row] += longint'(activation_value(
              feature
          )) * longint'(weight_value(
              channel, feature
          ));
      end
      expected_channels = in_channels;
      expected_tag = 32'hc1000000 + 32'(case_seed);
      expected_last = case_seed % 2 != 0;
      expected_fallback = case_seed % 3 == 0;
      in_tag = expected_tag;
      in_last = expected_last;
      in_fallback = expected_fallback;
      in_features = 10'(feature_strips);
      in_count = 8'(row_count);
      in_activation_base = ActBase;
      in_weight_base = WeightBase;
      case (bad_config)
        1: in_features = 513;
        2: in_count = 161;
        3: in_activation_base = ActBase + 1;
        4: in_weight_base = 64'hfffffffffffffff8;
        5: in_activation_base = 64'hfffffffffffffff8;
        6: in_activation_base = 64'hffffffffffffffff - 64'(feature_strips * Lanes) + 1;
        7: in_weight_base = 64'hffffffffffffffff - 64'(65536 * feature_strips * Lanes) + 1;
        8: in_features = 0;
        9: in_weight_base = WeightBase + 1;
        default: begin
        end
      endcase
      expected_activation_base = in_activation_base;
      expected_weight_base = in_weight_base;
      in_valid = 1;
      @(posedge clk);
      if (!in_ready) $fatal(1, "PACKET_NOT_ACCEPTED");
      @(negedge clk);
      in_valid = 0;
      in_features = '1;
      in_count = '1;
      in_tag = '1;
      in_channels = '1;
      in_activation_base = 0;
      in_weight_base = 0;
      in_last = !expected_last;
      in_fallback = !expected_fallback;
    end
  endtask

  task automatic run_case(input int feature_strips, row_count, fault, bad_config, case_seed);
    int timeout;
    logic expect_error;
    logic [7722:0] old;  // Held output packet before applying backpressure.
    begin
      launch(feature_strips, row_count, fault, bad_config, case_seed);
      timeout = 0;
      expect_error = fault != 0 || (bad_config > 0 && bad_config < 6) ||
                     bad_config == 8 || bad_config == 9;
      while (!out_valid && timeout < TimeoutCycles) begin
        @(negedge clk);
        timeout++;
      end
      if (out_valid !== 1'b1) $fatal(1, "PROJECTION_NOT_COMPLETED");
      if (memory_active || rsp_valid) $fatal(1, "EARLY_RESULT_WITH_OWNED_MEMORY_RESPONSE");
      if (fault != 0 && !fault_fired) $fatal(1, "MEMORY_FAULT_NOT_EXERCISED");
      if (fault >= 7 && fault <= 9 && commands < MaxBurst)
        $fatal(1, "LATER_TILE_FAULT_NOT_REACHED");
      if (fault == 10 && !abort_offer_seen) $fatal(1, "ABORT_DID_NOT_PRESERVE_OFFER");
      if (fault == 11 && !abort_accept_seen) $fatal(1, "ABORT_DID_NOT_DRAIN_ACCEPTED_REQUEST");
      if (out_error !== expect_error || out_tag !== expected_tag ||
          out_last !== expected_last || out_fallback !== expected_fallback ||
          out_count !== 8'(expect_error ? 0 : row_count) || out_channels !== expected_channels)
        $fatal(1, "PROJECTION_METADATA_MISMATCH");
      for (int row = 0; row < Rows; row++)
      if (out_data[row*SumBits+:SumBits] !== (expect_error ? SumBits'(0) : SumBits'(expected[row])))
        $fatal(1, "PROJECTION_SUM_MISMATCH case=%0d row=%0d", case_seed, row);
      if (!expect_error && row_count != 0) begin
        if (activation_bytes != feature_strips * Lanes * ((row_count + 31) / 32) ||
            weight_bytes != feature_strips * Lanes * row_count)
          $fatal(1, "PROJECTION_TRAFFIC_MISMATCH");
        if (commands != ((feature_strips + 3) / 4) * ((row_count + 31) / 32) || request_stalls == 0)
          $fatal(1, "MISSING_REAL_CLUSTER_COMMANDS_OR_STALLS");
        for (int cluster = 0; cluster < 5; cluster++) begin
          if (cluster_commands[cluster] !=
              (row_count > cluster * 32 ? (feature_strips + 3) / 4 : 0))
            $fatal(1, "MISSING_CLUSTER_EXECUTION %0d", cluster);
          if (row_count > cluster * 32 && owner_requests[cluster] == 0)
            $fatal(1, "STARVED_MEMORY_OWNER %0d", cluster);
        end
      end else if (bad_config != 0 || row_count == 0)
        if (requests != 0) $fatal(1, "INVALID_OR_EMPTY_PACKET_READ_MEMORY");
      old = {out_count, out_last, out_error, out_fallback, out_tag, out_channels, out_data};
      repeat (HoldCycles) begin
        @(negedge clk);
        if (out_valid !== 1'b1) $fatal(1, "UNSTABLE_PROJECTION_OUTPUT");
        if ({out_count, out_last, out_error, out_fallback, out_tag, out_channels, out_data} !== old)
          $fatal(1, "UNSTABLE_PROJECTION_OUTPUT");
      end
      out_ready = 1;
      @(posedge clk);
      @(negedge clk);
      out_ready = 0;
      checked++;
      $display("FABRIC_PROJECTION_CASE_PASS seed=%0d error=%0d commands=%0d", case_seed,
               expect_error, commands);
      $fflush();
    end
  endtask

  initial begin
    repeat (2) @(negedge clk);
    rst_n = 1;
    run_case(0, 0, 0, 0, 0);
    run_case(1, 1, 0, 0, 1);
    run_case(2, 31, 0, 0, 2);
    run_case(3, 32, 0, 0, 3);
    run_case(5, 33, 0, 0, 4);
    run_case(63, 64, 0, 0, 5);
    run_case(64, 65, 0, 0, 6);
    run_case(65, 129, 0, 0, 7);
    run_case(67, 160, 0, 0, 8);
    run_case(512, 160, 0, 0, 9);
    run_case(1, 1, 0, 0, 10);
    for (int fault = 1; fault <= 9; fault++) begin
      run_case(fault >= 7 ? 129 : 67, 65, fault, 0, 20 + fault);
      run_case(5, 33, 0, 0, 40 + fault);
    end
    for (int bad = 1; bad <= 5; bad++) run_case(67, 65, 0, bad, 60 + bad);
    run_case(3, 65, 0, 6, 70);
    run_case(67, 65, 0, 7, 71);
    for (int fault = 10; fault <= 11; fault++) begin
      run_case(67, 65, fault, 0, 80 + fault);
      run_case(5, 160, 0, 0, 90 + fault);
    end
    launch(67, 160, 0, 0, 110);
    wait (memory_active);
    @(negedge clk);
    rst_n = 0;
    request_held = 0;
    repeat (2) @(negedge clk);
    rst_n = 1;
    run_case(5, 160, 0, 0, 111);
    run_case(67, 65, 0, 8, 120);
    run_case(67, 65, 0, 9, 121);
    if (checked != 43) $fatal(1, "WRONG_CLUSTER_CASE_INVENTORY");
    $display("FABRIC_PROJECTION_PASS cases=%0d", checked);
    $finish;
  end
  initial begin
    #300000000;
    $fatal(1, "FABRIC_PROJECTION_WATCHDOG");
  end
endmodule
