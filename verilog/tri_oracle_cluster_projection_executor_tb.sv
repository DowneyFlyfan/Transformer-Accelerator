`timescale 1ns / 1ps
// Updated to modern SystemVerilog
// Independent signed dot products through the real four-core cluster.
module tri_oracle_cluster_projection_executor_tb;
  localparam int Rows = 32;
  localparam int Lanes = 8;
  localparam int SumBits = 32;
  localparam int IdBits = 16;
  localparam int TimeoutCycles = 300000;
  localparam int HoldCycles = 6;
  localparam int MaxBurst = 16;
  localparam logic [63:0] ActBase = 64'h100002000;
  localparam logic [63:0] WeightBase = 64'h200004000;
  logic clk = 0;
  always #5 clk = ~clk;
  logic rst_n = 0, in_valid = 0, in_last = 0, in_fallback = 0, out_ready = 0;
  logic [ 31:0] in_tag = 0;
  logic [  5:0] in_count = 0;
  logic [511:0] in_channels = 0;
  logic [63:0] in_activation_base = ActBase, in_weight_base = WeightBase;
  logic [9:0] in_features = 0;
  logic in_ready, out_valid, out_last, out_fallback, out_error;
  logic [31:0] out_tag;
  logic [5:0] out_count;
  logic [511:0] out_channels;
  logic [1023:0] out_data;
  logic req_valid, req_ready, rsp_ready;
  logic [63:0] req_address;
  logic [ 4:0] req_length;
  logic rsp_valid = 0, rsp_last = 0, rsp_error = 0;
  logic [63:0] rsp_data = 0;
  int cycle = 0, strips = 0, rows = 0, seed = 0, fault_mode = 0;
  int fault_style = 0, fault_scope = 0;
  int checked = 0, requests = 0, activation_bytes = 0, weight_bytes = 0;
  int commands = 0, issue_run = 0, max_issue_run = 0, request_stalls = 0;
  int beat = 0, burst_length = 0;
  logic memory_active = 0, request_waited = 0, inject_burst = 0, fault_fired = 0;
  logic [ 63:0] address = 0;
  logic [511:0] expected_channels;
  logic [63:0] expected_activation_base, expected_weight_base;
  logic weight_burst = 0;
  logic [31:0] expected_tag;
  logic expected_last, expected_fallback;
  longint signed expected[Rows];
  logic request_held = 0;
  logic [68:0] held_request;

  always_comb req_ready = !memory_active && !rsp_valid && request_waited && cycle % 4 != 0;
  logic cluster_load_valid, cluster_load_error;
  logic [1:0] cluster_load_core, cluster_load_kind;
  logic [9:0] cluster_load_address;
  logic [2047:0] cluster_load_data;
  logic [31:0] cluster_load_rows;
  logic cluster_cmd_valid, cluster_cmd_ready, cluster_cmd_accumulate;
  logic [4:0] cluster_cmd_weight;
  logic [9:0] cluster_cmd_activation;
  logic [3:0] cluster_cmd_output, cluster_out_output;
  logic cluster_out_valid, cluster_out_ready;
  logic [1023:0] cluster_out_data;
  logic manual_owner = 0, manual_load_valid = 0, manual_cmd_valid = 0;
  logic manual_out_ready = 0, manual_accumulate = 0;
  logic [1:0] manual_core = 0, manual_kind = 0;
  logic [9:0] manual_address = 0;
  logic [2047:0] manual_data = 0;
  logic [3:0] manual_slot = 0;
  int core_instances = 0, cluster_instances = 0;
  int weight_mask_memories = 0, activation_memories = 0, result_memories = 0;
  int preserved_slots = 0;
  int signed retained[3][32];
`ifdef SLOT0_BASELINE
  tri_oracle_cluster_projection dut (.*);
`else
  tri_oracle_cluster_projection_executor dut (.*);
  tri_oracle_sram_compute_cluster compiled_cluster (
    .clk(clk), .rst_n(rst_n),
    .load_valid(manual_owner ? manual_load_valid : cluster_load_valid),
    .load_core(manual_owner ? manual_core : cluster_load_core),
    .load_kind(manual_owner ? manual_kind : cluster_load_kind),
    .load_addr(manual_owner ? manual_address : cluster_load_address),
    .load_data(manual_owner ? manual_data : cluster_load_data),
    .load_row_enable(manual_owner ? 32'hffffffff : cluster_load_rows),
    .load_error(cluster_load_error),
    .cmd_valid(manual_owner ? manual_cmd_valid : cluster_cmd_valid),
    .cmd_ready(cluster_cmd_ready), .cmd_weight(manual_owner ? 5'd0 : cluster_cmd_weight),
    .cmd_mask(5'd0), .cmd_activation(manual_owner ? 10'd0 : cluster_cmd_activation),
    .cmd_output(manual_owner ? manual_slot : cluster_cmd_output),
    .cmd_accumulate(manual_owner ? manual_accumulate : cluster_cmd_accumulate),
    .cmd_reduce(2'd0), .out_valid(cluster_out_valid),
    .out_ready(manual_owner ? manual_out_ready : cluster_out_ready),
    .out_output(cluster_out_output), .out_data(cluster_out_data));
`endif

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
        requests++;
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
            rsp_data[lane*8+:8] <= 8'(activation_value(
                int'(cursor - expected_activation_base)
            ));
        end
      end
      if (rsp_valid && rsp_ready) begin
        rsp_valid <= 0;
        if (rsp_last) memory_active <= 0;
        else beat <= beat + 1;
      end
      if (dut.cluster_cmd_valid && dut.cluster_cmd_ready) begin
        if (!$test$plusargs("ALLOW_DESTRUCTIVE_SLOTS") && dut.cluster_cmd_output !== 4'd0)
          $fatal(1, "PROJECTION_OVERWRITES_RESERVED_DOWN_CONTEXT slot=%0d", dut.cluster_cmd_output);
`ifndef SLOT0_BASELINE
        if (!$test$plusargs("ALLOW_DESTRUCTIVE_SLOTS") &&
            dut.cluster_cmd_accumulate !== (commands != 0))
          $fatal(1, "WRONG_FIRST_OVERWRITE_OR_SUBSEQUENT_ACCUMULATE");
`endif
        commands++;
        issue_run++;
        if (issue_run > max_issue_run) max_issue_run = issue_run;
      end else issue_run = 0;
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
      fault_style = fault == 0 ? 0 : (fault - 1) % 3 + 1;
      fault_scope = fault == 0 ? 0 : (fault - 1) / 3;
      fault_fired = 0;
      requests = 0;
      activation_bytes = 0;
      weight_bytes = 0;
      commands = 0;
      issue_run = 0;
      max_issue_run = 0;
      request_stalls = 0;
      in_channels = 0;
      for (int row = 0; row < Rows; row++) begin
        channel = row % 3 == 0 ? 65535 - row : (row % 3 == 1 ? row * 17 : 500 + row);
        in_channels[row*IdBits+:IdBits] = IdBits'(channel);
        expected[row] = 0;
        if (row < row_count && !(bad_config > 0 && bad_config < 6) && fault == 0)
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
      in_count = 6'(row_count);
      in_activation_base = ActBase;
      in_weight_base = WeightBase;
      case (bad_config)
        1: in_features = 513;
        2: in_count = 33;
        3: in_activation_base = ActBase + 1;
        4: in_weight_base = 64'hfffffffffffffff8;
        5: in_activation_base = 64'hfffffffffffffff8;
        6: in_activation_base = 64'hffffffffffffffff - 64'(feature_strips * Lanes) + 1;
        7: in_weight_base = 64'hffffffffffffffff - 64'(65536 * feature_strips * Lanes) + 1;
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
    logic [1576:0] old;  // Held output packet before applying backpressure.
    begin
      launch(feature_strips, row_count, fault, bad_config, case_seed);
      if ($test$plusargs("CORRUPT_DOT_REFERENCE") && row_count > 0) expected[0]++;
      timeout = 0;
      expect_error = fault != 0 || (bad_config > 0 && bad_config < 6);
      while (!out_valid && timeout < TimeoutCycles) begin
        @(negedge clk);
        timeout++;
      end
      if (out_valid !== 1'b1) $fatal(1, "PROJECTION_NOT_COMPLETED");
      if (memory_active || rsp_valid) $fatal(1, "EARLY_RESULT_WITH_OWNED_MEMORY_RESPONSE");
      if (fault != 0 && !fault_fired) $fatal(1, "MEMORY_FAULT_NOT_EXERCISED");
      if (fault >= 7 && commands != MaxBurst) $fatal(1, "LATER_TILE_FAULT_NOT_REACHED");
      if (out_error !== expect_error || out_tag !== expected_tag ||
          out_last !== expected_last || out_fallback !== expected_fallback ||
          out_count !== 6'(expect_error ? 0 : row_count) || out_channels !== expected_channels)
        $fatal(1, "PROJECTION_METADATA_MISMATCH");
      for (int row = 0; row < Rows; row++)
      if (out_data[row*SumBits+:SumBits] !== (expect_error ? SumBits'(0) : SumBits'(expected[row])))
        $fatal(1, "PROJECTION_SUM_MISMATCH case=%0d row=%0d", case_seed, row);
      if (!expect_error && row_count != 0) begin
        if (activation_bytes != feature_strips * Lanes ||
            weight_bytes != feature_strips * Lanes * row_count)
          $fatal(1, "PROJECTION_TRAFFIC_MISMATCH");
        if (commands != (feature_strips + 3) / 4 || request_stalls == 0)
          $fatal(1, "MISSING_FOUR_CORE_COMMANDS_OR_STALLS");
        // Reusing slot 0 intentionally serializes issue until its old result retires.
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
      $display("CLUSTER_PROJECTION_CASE_PASS seed=%0d error=%0d commands=%0d run=%0d",
               case_seed, expect_error, commands, max_issue_run);
    end
  endtask

  // The test peer owns the same real bus only while the executor is idle.
  // No internal output memory is deposited, forced or read hierarchically.
  task automatic direct_load(input int core, kind, input logic [2047:0] word_data);
    @(negedge clk);
    manual_core = 2'(core);
    manual_kind = 2'(kind);
    manual_address = 0;
    manual_data = word_data;
    manual_load_valid = 1;
    @(posedge clk);
    #1;
    if (cluster_load_error) $fatal(1, "LEGITIMATE_CONTEXT_LOAD_REJECTED");
    @(negedge clk);
    manual_load_valid = 0;
  endtask

  task automatic direct_command(input int slot, input bit accumulate,
                                 input int retained_index);
    int timeout;
    logic [1023:0] held;
    @(negedge clk);
    manual_slot = 4'(slot);
    manual_accumulate = accumulate;
    manual_cmd_valid = 1;
    timeout = 0;
    @(posedge clk);
    while (!cluster_cmd_ready && timeout < 1000) begin
      @(posedge clk);
      timeout++;
    end
    if (!cluster_cmd_ready) $fatal(1, "CONTEXT_COMMAND_NOT_ACCEPTED");
    @(negedge clk);
    manual_cmd_valid = 0;
    timeout = 0;
    while (!cluster_out_valid && timeout < 1000) begin
      @(negedge clk);
      timeout++;
    end
    if (!cluster_out_valid || cluster_out_output !== 4'(slot))
      $fatal(1, "MISSING_RETAINED_CONTEXT_RESULT");
    for (int row = 0; row < 32; row++)
      if (cluster_out_data[row*32+:32] !== 32'(retained[retained_index][row]))
        $fatal(1, "DOWN_CONTEXT_CORRUPTED slot=%0d row=%0d expected=%0d got=%0d",
               slot, row, retained[retained_index][row], $signed(cluster_out_data[row*32+:32]));
    held = cluster_out_data;
    repeat (4) begin
      @(negedge clk);
      if (!cluster_out_valid || cluster_out_output !== 4'(slot) || cluster_out_data !== held)
        $fatal(1, "RETAINED_CONTEXT_NOT_STABLE_UNDER_STALL");
    end
    manual_out_ready = 1;
    @(posedge clk);
    @(negedge clk);
    manual_out_ready = 0;
    if (cluster_out_valid) $fatal(1, "CONTEXT_RESULT_NOT_RETIRED");
  endtask

  task automatic initialize_retained_contexts;
    logic [2047:0] word_data;
    int slot, weight_byte, activation_byte, nonzero;
    if (!in_ready) $fatal(1, "UNSAFE_CONTEXT_HANDOFF");
    manual_owner = 1;
    for (int index = 0; index < 3; index++) begin
      slot = index == 0 ? 1 : (index == 1 ? 7 : 15);
      for (int row = 0; row < 32; row++) retained[index][row] = 0;
      for (int core = 0; core < 4; core++) begin
        word_data = 0;
        word_data[255:0] = '1;
        direct_load(core, 2, word_data);
        word_data = 0;
        for (int lane = 0; lane < 8; lane++) begin
          activation_byte = ((core + lane + slot) % 9) - 4;
          word_data[lane*8+:8] = 8'(activation_byte);
        end
        direct_load(core, 1, word_data);
        word_data = 0;
        for (int row = 0; row < 32; row++) begin
          weight_byte = ((slot + core + row) % 13) - 6;
          for (int lane = 0; lane < 8; lane++) begin
            word_data[(row*8+lane)*8+:8] = 8'(weight_byte);
            activation_byte = ((core + lane + slot) % 9) - 4;
            retained[index][row] += weight_byte * activation_byte;
          end
        end
        direct_load(core, 0, word_data);
      end
      nonzero = 0;
      for (int row = 0; row < 32; row++) if (retained[index][row] != 0) nonzero++;
      if (nonzero < 24) $fatal(1, "VACUOUS_NONZERO_CONTEXT_FIXTURE");
      direct_command(slot, 0, index);
    end
    manual_owner = 0;
    $display("DOWN_CONTEXT_INITIALIZATION_PASS slots=1,7,15 values=96");
  endtask

  task automatic verify_retained_contexts;
    logic [2047:0] mask_data;
    int slot;
    if (!in_ready) $fatal(1, "UNSAFE_CONTEXT_VERIFICATION_HANDOFF");
    manual_owner = 1;
    mask_data = 0;
    mask_data[255:0] = '1;
    for (int core = 0; core < 4; core++) begin
      direct_load(core, 2, mask_data);
      direct_load(core, 1, 2048'b0);
      direct_load(core, 0, 2048'b0);
    end
    for (int index = 0; index < 3; index++) begin
      slot = index == 0 ? 1 : (index == 1 ? 7 : 15);
      direct_command(slot, 1, index);
      preserved_slots++;
      $display("DOWN_CONTEXT_PRESERVATION_PASS slot=%0d values=32", slot);
    end
    manual_owner = 0;
  endtask

  initial begin
    #1;
    if (core_instances != 4 || cluster_instances != 1 || weight_mask_memories != 72 ||
        activation_memories != 8 || result_memories != 40)
      $fatal(1, "WRONG_ACTUAL_COMPILED_CLUSTER_HIERARCHY");
    $display("SLOT0_ACTUAL_HIERARCHY cores=4 clusters=1 compiled_memories=120");
    repeat (2) @(negedge clk);
    rst_n = 1;
`ifdef SLOT0_BASELINE
    run_case(67, 3, 0, 0, 200);
    $fatal(1, "DESTRUCTIVE_BASELINE_NOT_REJECTED");
`endif
    if ($test$plusargs("LEGACY_PRESERVATION_ONLY")) begin
      initialize_retained_contexts();
      run_case(67, 3, 0, 0, 201);
      verify_retained_contexts();
      $fatal(1, "DESTRUCTIVE_LEGACY_CONTEXT_OVERWRITE_NOT_REJECTED");
    end
    run_case(0, 0, 0, 0, 0);
    run_case(1, 1, 0, 0, 1);
    run_case(2, 3, 0, 0, 2);
    run_case(3, 7, 0, 0, 3);
    run_case(4, 32, 0, 0, 4);
    run_case(5, 3, 0, 0, 5);
    run_case(63, 7, 0, 0, 6);
    run_case(64, 32, 0, 0, 7);
    run_case(65, 3, 0, 0, 8);
    run_case(67, 7, 0, 0, 9);
    run_case(127, 7, 0, 0, 10);
    run_case(128, 3, 0, 0, 11);
    run_case(129, 7, 0, 0, 12);
    run_case(512, 32, 0, 0, 13);
    run_case(1, 1, 0, 0, 14);
    for (int fault = 1; fault <= 3; fault++) begin
      run_case(67, 3, fault, 0, 20 + fault);
      run_case(5, 3, 0, 0, 30 + fault);
    end
    for (int bad = 1; bad <= 5; bad++) run_case(67, 3, 0, bad, 40 + bad);
    for (int fault = 4; fault <= 9; fault++) begin
      run_case(fault >= 7 ? 129 : 67, 3, fault, 0, 60 + fault);
      run_case(5, 3, 0, 0, 80 + fault);
    end
    run_case(3, 3, 0, 6, 90);
    run_case(67, 3, 0, 7, 91);
    launch(67, 3, 0, 0, 50);
    wait (memory_active);
    @(negedge clk);
    rst_n = 0;
    request_held = 0;
    repeat (2) @(negedge clk);
    rst_n = 1;
    run_case(5, 3, 0, 0, 51);
    if (checked != 41) $fatal(1, "WRONG_CLUSTER_CASE_INVENTORY");
    initialize_retained_contexts();
    run_case(1, 1, 0, 0, 201);
    verify_retained_contexts();
    run_case(67, 3, 0, 0, 202);
    verify_retained_contexts();
    run_case(129, 7, 0, 0, 203);
    verify_retained_contexts();
    run_case(512, 32, 0, 0, 204);
    verify_retained_contexts();
    // Preserve live down contexts through a second-tile weight error and reuse.
    run_case(129, 3, 7, 0, 205);
    verify_retained_contexts();
    run_case(5, 3, 0, 0, 206);
    verify_retained_contexts();
    if (checked != 47 || preserved_slots != 18) $fatal(1, "WRONG_PRESERVATION_CASE_INVENTORY");
    $display("SLOT0_PRESERVATION_PASS slots_checked=18 values=576");
    $display("CLUSTER_PROJECTION_EXECUTOR_PASS cases=%0d", checked);
    $finish;
  end
  initial begin
    #20000000;
    $fatal(1, "CLUSTER_PROJECTION_WATCHDOG");
  end
endmodule

module tri_oracle_slot0_instance_count #(parameter int KIND = 0) ();
  initial begin
    case (KIND)
      0: $root.tri_oracle_cluster_projection_executor_tb.core_instances++;
      1: $root.tri_oracle_cluster_projection_executor_tb.cluster_instances++;
      2: $root.tri_oracle_cluster_projection_executor_tb.weight_mask_memories++;
      3: $root.tri_oracle_cluster_projection_executor_tb.activation_memories++;
      4: $root.tri_oracle_cluster_projection_executor_tb.result_memories++;
    endcase
  end
endmodule

bind tri_oracle_sram_memory_compute tri_oracle_slot0_instance_count
    #(.KIND(0)) count_actual_core ();
bind tri_oracle_sram_compute_cluster tri_oracle_slot0_instance_count
    #(.KIND(1)) count_actual_cluster ();
bind TS5N28HPCPSVTA32X128M2FW tri_oracle_slot0_instance_count
    #(.KIND(2)) count_actual_weight_mask ();
bind TS5N28HPCPSVTA512X64M4F tri_oracle_slot0_instance_count
    #(.KIND(3)) count_actual_activation ();
bind TS6N28HPCPSVTA16X128M2F tri_oracle_slot0_instance_count
    #(.KIND(4)) count_actual_result ();
