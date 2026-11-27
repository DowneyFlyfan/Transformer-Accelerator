`timescale 1ns / 1ps
// Test-first unit contract. The descriptor endpoint is an explicit synthetic
// NextOwner transport; the device must derive eA from its accepted response.
// No array, trained-model, residual-format, mapped or full-frame proof is made.
module tri_oracle_row_unit_frame_adapter_tb;
  logic clk, rst_n, abort_valid;
  logic cfg_valid, cfg_ready, cfg_parent_context_valid, cfg_parent_error;
  logic [31:0] cfg_tag_base;
  logic [4:0] cfg_layer, cfg_bundle_layer;
  logic [15:0] cfg_epoch;
  logic [9:0] cfg_image_start, cfg_input_count, cfg_kept_count;
  logic [9:0] cfg_kept_rank, cfg_expected_root, cfg_expected_input_rank;
  logic cfg_release_after_row;
  logic [1:0] cfg_normalization_role, cfg_phase;
  logic [127:0] cfg_bundle_id;
  logic signed [8:0] cfg_gate_exponent, cfg_up_exponent, cfg_down_max_exponent;
  logic [2:0] cfg_gate_delta_max, cfg_up_delta_max, cfg_bucket_count;
  logic [35:0] cfg_bucket_exponents, cfg_bucket_gain_caps, cfg_bucket_down_offsets;
  logic signed [8:0] cfg_fallback_gain_cap, cfg_fallback_down_offset;
  logic [63:0] cfg_compact_output_base, cfg_gate_base, cfg_up_base, cfg_down_base;
  logic [63:0] cfg_row_units_base, cfg_intermediate_base, cfg_down_scale_base;

  logic next_context_owned, next_req_valid, next_req_ready, next_req_write;
  logic [9:0] next_req_word;
  logic [63:0] next_req_data, next_rsp_data;
  logic next_rsp_valid, next_rsp_error, next_rsp_ready;
  logic provider_rsp_valid, provider_rsp_error, rogue_next_rsp_valid;
  logic [63:0] provider_rsp_data, rogue_next_rsp_data;
  logic next_release_valid, next_release_ready;

  logic frame_cfg_valid, frame_cfg_ready, frame_cfg_row_enable, frame_cfg_correction_enable;
  logic [31:0] frame_cfg_tag;
  logic [4:0] frame_cfg_tokens;
  logic [15:0] frame_cfg_input_features, frame_cfg_intermediate_features;
  logic [16:0] frame_cfg_output_features;
  logic [63:0] frame_cfg_activation_base, frame_cfg_gate_base, frame_cfg_up_base;
  logic [63:0] frame_cfg_down_base, frame_cfg_intermediate_base, frame_cfg_row_units_base;
  logic [31:0] frame_cfg_activation_stride;
  logic [95:0] frame_cfg_gate_shifts, frame_cfg_up_shifts, frame_cfg_down_shifts;
  logic frame_done_valid, frame_done_ready, frame_done_error, frame_out_drained;
  logic [31:0] frame_done_tag;

  logic row_context_valid;
  logic [31:0] row_tag;
  logic [4:0] row_layer;
  logic [15:0] row_epoch;
  logic [9:0] row_original_root, row_input_rank, row_kept_rank;
  logic signed [8:0] row_activation_exponent, row_down_max_exponent;
  logic signed [10:0] row_up_gain;
  logic signed [11:0] row_down_physical_exponent;
  logic [63:0] row_down_scale_base;
  logic [64:0] down_scale_last;
  logic [5:0] row_down_shift;
  logic [127:0] row_bundle_id;
  logic legacy_residual_writeback_enable;
  logic done_valid, done_ready, done_error, epoch_fault, frame_active, idle;

  logic [63:0] descriptor_word, saved_descriptor;
  logic provider_owned, endpoint_error, force_owner_lost, response_pending;
  logic [3:0] request_stalls, response_delay;
  logic [9:0] saved_request_word;
  logic held_request, held_configuration, held_done;
  logic [9:0] held_word;
  logic [63:0] held_request_data;
  logic held_request_write;
  integer test_case, cycles, request_count, response_count, command_count, release_count;

  typedef struct packed {
    logic row_enable, correction_enable;
    logic [31:0] tag;
    logic [4:0] tokens;
    logic [15:0] input_features, intermediate_features;
    logic [16:0] output_features;
    logic [63:0] activation_base, gate_base, up_base, down_base, intermediate_base, row_units_base;
    logic [31:0] activation_stride;
    logic [95:0] gate_shifts, up_shifts, down_shifts;
  } command_t;
  command_t held_command;
  logic held_done_error;

  tri_oracle_row_unit_frame_adapter_v1 dut (.*);

  function automatic command_t command_packet();
    return {frame_cfg_row_enable, frame_cfg_correction_enable, frame_cfg_tag, frame_cfg_tokens,
      frame_cfg_input_features, frame_cfg_intermediate_features, frame_cfg_output_features,
      frame_cfg_activation_base, frame_cfg_gate_base, frame_cfg_up_base, frame_cfg_down_base,
      frame_cfg_intermediate_base, frame_cfg_row_units_base, frame_cfg_activation_stride,
      frame_cfg_gate_shifts, frame_cfg_up_shifts, frame_cfg_down_shifts};
  endfunction

  assign next_context_owned = provider_owned && !force_owner_lost;
  // Exactly one driver per public response field. The standalone fault source
  // does not edit provider state/counters or create an owned read.
  assign next_rsp_valid = rogue_next_rsp_valid ? 1'b1 : provider_rsp_valid;
  assign next_rsp_error = rogue_next_rsp_valid ? 1'b0 : provider_rsp_error;
  assign next_rsp_data = rogue_next_rsp_valid ? rogue_next_rsp_data : provider_rsp_data;
  assign down_scale_last = {1'b0, row_down_scale_base} + 65'd1023;
  initial clk = 0;
  always #5 clk = ~clk;

  // Source-visible endpoint: held request for three sampled edges, then one
  // accepted read and one registered response. No eA enters through cfg ports.
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      next_req_ready <= 0;
      provider_rsp_valid <= 0;
      provider_rsp_error <= 0;
      provider_rsp_data <= 0;
      provider_owned <= 1;
      response_pending <= 0;
      request_stalls <= 0;
      response_delay <= 0;
      saved_request_word <= 0;
      saved_descriptor <= 0;
      request_count <= 0;
      response_count <= 0;
      command_count <= 0;
      release_count <= 0;
    end else begin
      if (next_req_valid && !next_req_ready && !response_pending) begin
        if (request_stalls == 3) next_req_ready <= 1;
        else request_stalls <= request_stalls + 1'b1;
      end
      if (next_req_valid && next_req_ready) begin
        if (response_pending || next_req_write || next_req_data != 0 ||
            next_req_word != 10'(256 + cfg_kept_rank))
          $fatal(1, "ROW_UNIT_ADAPTER_BAD_DESCRIPTOR_REQUEST case=%0d", test_case);
        request_count <= request_count + 1;
        saved_request_word <= next_req_word;
        saved_descriptor <= descriptor_word;
        next_req_ready <= 0;
        response_pending <= 1;
        response_delay <= 0;
      end
      if (response_pending && !provider_rsp_valid) begin
        if (response_delay == 2) begin
          provider_rsp_valid <= 1;
          provider_rsp_error <= endpoint_error;
          provider_rsp_data <= saved_descriptor;
        end else response_delay <= response_delay + 1'b1;
      end
      if (provider_rsp_valid && !rogue_next_rsp_valid && next_rsp_ready) begin
        provider_rsp_valid <= 0;
        response_pending <= 0;
        response_count <= response_count + 1;
      end
      if (frame_cfg_valid && frame_cfg_ready) command_count <= command_count + 1;
      if (next_release_valid && next_release_ready) begin
        if (response_pending || next_rsp_valid || next_req_valid)
          $fatal(1, "ROW_UNIT_ADAPTER_RELEASE_WITH_OWNED_READ case=%0d", test_case);
        provider_owned <= 0;
        release_count <= release_count + 1;
      end
    end
  end

  // Check actual exposed offers at the rising edge; never compare a test mock
  // against itself or rely only on a completion count.
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      held_request <= 0;
      held_configuration <= 0;
      held_done <= 0;
      held_word <= 0;
      held_request_write <= 0;
      held_request_data <= 0;
      held_command <= '0;
      held_done_error <= 0;
    end else begin
      if (held_request && (!next_req_valid || next_req_word !== held_word ||
          next_req_write !== held_request_write || next_req_data !== held_request_data))
        $fatal(1, "ROW_UNIT_ADAPTER_RETRACTED_DESCRIPTOR_OFFER case=%0d", test_case);
      if (held_configuration && (!frame_cfg_valid || command_packet() !== held_command))
        $fatal(1, "ROW_UNIT_ADAPTER_RETRACTED_CONFIGURATION case=%0d", test_case);
      if (held_done && (!done_valid || done_error !== held_done_error))
        $fatal(1, "ROW_UNIT_ADAPTER_REWROTE_HELD_COMPLETION case=%0d", test_case);
      held_request <= next_req_valid && !next_req_ready;
      held_configuration <= frame_cfg_valid && !frame_cfg_ready;
      held_done <= done_valid && !done_ready;
      held_word <= next_req_word;
      held_request_write <= next_req_write;
      held_request_data <= next_req_data;
      held_command <= command_packet();
      held_done_error <= done_error;
      if (legacy_residual_writeback_enable)
        $fatal(1, "ROW_UNIT_ADAPTER_ENABLED_LEGACY_CLIPPED_WRITER");
    end
  end

  task automatic ticks(input integer count);
    repeat (count) @(negedge clk);
  endtask

  task automatic defaults();
    cfg_valid = 0;
    abort_valid = 0;
    cfg_parent_context_valid = 1;
    cfg_parent_error = 0;
    cfg_tag_base = 32'h0000a100;
    cfg_layer = 5'd3;
    cfg_bundle_layer = 5'd3;
    cfg_epoch = 16'd11;
    cfg_image_start = 10'd5;
    cfg_input_count = 10'd12;
    cfg_kept_count = 10'd2;
    cfg_kept_rank = 10'd0;
    cfg_expected_root = 10'd19;
    cfg_expected_input_rank = 10'd7;
    cfg_release_after_row = 0;
    cfg_normalization_role = 2'd1; // POST_ATTENTION only; INPUT is zero.
    cfg_phase = 2'd1; // ORDINARY_PREFILL; FIRST=0, DECODE=2.
    cfg_bundle_id = 128'h0123456789abcdef1122334455667788;
    cfg_gate_exponent = -9'sd7;
    cfg_up_exponent = -9'sd8;
    cfg_down_max_exponent = -9'sd7;
    cfg_gate_delta_max = 3'd2;
    cfg_up_delta_max = 3'd3;
    cfg_bucket_count = 0;
    cfg_bucket_exponents = 0;
    cfg_bucket_gain_caps = 0;
    cfg_bucket_down_offsets = 0;
    cfg_fallback_gain_cap = 9'sd7;
    cfg_fallback_down_offset = -9'sd1;
    cfg_compact_output_base = 64'h00200000;
    cfg_gate_base = 64'h40000000;
    cfg_up_base = 64'h42000000;
    cfg_down_base = 64'h44000000;
    cfg_row_units_base = 64'h46000000;
    cfg_intermediate_base = 64'h47000000;
    cfg_down_scale_base = 64'h48000000;
    descriptor_word = {3'b010, 9'(-10), 10'd0, 10'd19, 32'h0000a107};
    endpoint_error = 0;
    rogue_next_rsp_valid = 0;
    rogue_next_rsp_data = 64'hdeadc0de12345678;
    force_owner_lost = 0;
    frame_cfg_ready = 0;
    frame_done_valid = 0;
    frame_done_error = 0;
    frame_done_tag = 32'h0000a107;
    frame_out_drained = 0;
    next_release_ready = 0;
    done_ready = 0;
  endtask

  task automatic start_case(input integer number);
    @(negedge clk);
    rst_n = 0;
    defaults();
    test_case = number;
    ticks(3);
    rst_n = 1;
    ticks(2);
  endtask

  task automatic accept_context();
    integer count;
    cfg_valid = 1;
    count = 0;
    while (cfg_ready !== 1'b1 && count < 20) begin ticks(1); count++; end
    if (cfg_ready !== 1'b1) $fatal(1, "ROW_UNIT_ADAPTER_CONTEXT_NOT_ACCEPTED");
    @(posedge clk);
    @(negedge clk);
    cfg_valid = 0;
  endtask

  task automatic require_command(input logic [5:0] want_gate, want_up, want_down,
      input logic signed [10:0] want_gain, input logic signed [11:0] want_physical,
      input logic signed [8:0] want_exponent, input logic [63:0] want_activation,
      input integer want_transfers);
    integer count;
    count = 0;
    while (frame_cfg_valid !== 1'b1 && count < 120) begin ticks(1); count++; end
    // The reset-safe unimplemented adapter must fail HERE, through real absent
    // command behavior after an accepted context, not through compile failure.
    if (frame_cfg_valid !== 1'b1)
      $fatal(1, "ROW_UNIT_ADAPTER_EXPECTED_DERIVED_COMMAND case=%0d req=%0d rsp=%0d", test_case, request_count, response_count);
    if (request_count != want_transfers || response_count != want_transfers ||
        saved_request_word != 10'(256 + cfg_kept_rank))
      $fatal(1, "ROW_UNIT_ADAPTER_COMMAND_WITHOUT_GENUINE_DESCRIPTOR_RESPONSE");
    if (frame_cfg_tag !== cfg_tag_base + 32'(cfg_expected_input_rank) || frame_cfg_tokens !== 1 ||
        frame_cfg_input_features !== 2048 || frame_cfg_intermediate_features !== 5632 ||
        frame_cfg_output_features !== 2048 || frame_cfg_activation_base !== want_activation ||
        frame_cfg_activation_stride !== 2048 || !frame_cfg_row_enable || frame_cfg_correction_enable ||
        frame_cfg_gate_base !== cfg_gate_base || frame_cfg_up_base !== cfg_up_base ||
        frame_cfg_down_base !== cfg_down_base || frame_cfg_row_units_base !== cfg_row_units_base ||
        frame_cfg_intermediate_base !== cfg_intermediate_base || frame_cfg_gate_shifts !== 96'(want_gate) ||
        frame_cfg_up_shifts !== 96'(want_up) || frame_cfg_down_shifts !== 96'(want_down))
      $fatal(1, "ROW_UNIT_ADAPTER_WRONG_DERIVED_CONFIGURATION case=%0d", test_case);
    if (!row_context_valid || row_tag !== cfg_tag_base + 32'(cfg_expected_input_rank) ||
        row_original_root !== cfg_expected_root || row_input_rank !== cfg_expected_input_rank ||
        row_kept_rank !== cfg_kept_rank || row_layer !== cfg_layer || row_epoch !== cfg_epoch ||
        row_activation_exponent !== want_exponent || row_bundle_id !== cfg_bundle_id ||
        row_down_max_exponent !== cfg_down_max_exponent || row_up_gain !== want_gain ||
        row_down_shift !== want_down || row_down_physical_exponent !== want_physical ||
        row_down_scale_base !== cfg_down_scale_base || row_down_scale_base[2:0] != 0 || down_scale_last[64])
      $fatal(1, "ROW_UNIT_ADAPTER_WRONG_UNIT_SIDECAR case=%0d", test_case);
    ticks(4);
  endtask

  task automatic finish_issued(input logic error_expected, release_expected,
      input integer want_transfers);
    integer count;
    frame_cfg_ready = 1;
    @(posedge clk);
    @(negedge clk);
    frame_cfg_ready = 0;
    ticks(2);
    frame_done_error = error_expected;
    frame_done_valid = 1;
    count = 0;
    while (frame_done_ready !== 1'b1 && count < 40) begin ticks(1); count++; end
    if (frame_done_ready !== 1'b1) $fatal(1, "ROW_UNIT_ADAPTER_MISSED_EXTERNAL_TERMINAL");
    @(posedge clk);
    @(negedge clk);
    frame_done_valid = 0;
    repeat (3) begin
      if (done_valid || next_release_valid) $fatal(1, "ROW_UNIT_ADAPTER_EARLY_OUTPUT_DRAIN_RETIREMENT");
      ticks(1);
    end
    frame_out_drained = 1;
    count = 0;
    while (done_valid !== 1'b1 && count < 40) begin ticks(1); count++; end
    if (done_valid !== 1'b1 || done_error !== error_expected)
      $fatal(1, "ROW_UNIT_ADAPTER_WRONG_COMPLETION case=%0d", test_case);
    repeat (4) begin
      if (next_release_valid || !next_context_owned || !row_context_valid)
        $fatal(1, "ROW_UNIT_ADAPTER_EARLY_OWNER_RELEASE case=%0d", test_case);
      ticks(1);
    end
    done_ready = 1;
    @(posedge clk);
    @(negedge clk);
    done_ready = 0;
    if (error_expected) begin
      ticks(4);
      if (next_release_valid || !next_context_owned || !frame_active || !epoch_fault || cfg_ready)
        $fatal(1, "ROW_UNIT_ADAPTER_FAULT_RELEASED_OR_REUSED_OWNER");
    end else if (!release_expected) begin
      ticks(4);
      if (next_release_valid || !next_context_owned || !frame_active || idle || !cfg_ready)
        $fatal(1, "ROW_UNIT_ADAPTER_LOST_FRAME_BETWEEN_ROWS");
    end else begin
      count = 0;
      while (next_release_valid !== 1'b1 && count < 30) begin ticks(1); count++; end
      if (next_release_valid !== 1'b1) $fatal(1, "ROW_UNIT_ADAPTER_MISSING_REAL_RELEASE");
      ticks(3);
      next_release_ready = 1;
      @(posedge clk);
      @(negedge clk);
      next_release_ready = 0;
      ticks(2);
      if (release_count != 1 || frame_active || !idle)
        $fatal(1, "ROW_UNIT_ADAPTER_BAD_FINAL_RELEASE");
    end
    if (request_count != want_transfers || response_count != want_transfers || command_count != want_transfers)
      $fatal(1, "ROW_UNIT_ADAPTER_WRONG_TRANSFER_CENSUS case=%0d", test_case);
    $display("ROW_UNIT_ADAPTER_CASE_PASS case=%0d", test_case);
  endtask

  task automatic require_rejected();
    integer count;
    accept_context();
    count = 0;
    while (done_valid !== 1'b1 && count < 120) begin
      if (frame_cfg_valid) $fatal(1, "ROW_UNIT_ADAPTER_ISSUED_REJECTED_CONTEXT case=%0d", test_case);
      ticks(1); count++;
    end
    if (done_valid !== 1'b1 || done_error !== 1'b1)
      $fatal(1, "ROW_UNIT_ADAPTER_REJECTION_NOT_REPORTED case=%0d", test_case);
    ticks(3);
    if (frame_cfg_valid || next_release_valid)
      $fatal(1, "ROW_UNIT_ADAPTER_REJECTED_CONTEXT_DROPPED_OWNER");
    done_ready = 1;
    @(posedge clk);
    @(negedge clk);
    done_ready = 0;
    ticks(2);
    if (next_release_valid || !next_context_owned || !epoch_fault || cfg_ready)
      $fatal(1, "ROW_UNIT_ADAPTER_REJECTION_RELEASED_OR_REUSED_OWNER");
    $display("ROW_UNIT_ADAPTER_CASE_PASS case=%0d", test_case);
  endtask

  task automatic repro_uncaptured_response();
    integer count;
    start_case(90);
    accept_context();
    count = 0;
    // First negedge after the actual descriptor ACK: eA has been captured,
    // no new configuration/status has been exposed, no owned read remains.
    while (response_count != 1 && count < 120) begin ticks(1); count++; end
    if (request_count != 1 || response_count != 1 || provider_rsp_valid || frame_cfg_valid || done_valid)
      $fatal(1, "ROW_UNIT_ADAPTER_UNCAPTURED_REPRO_NOT_ARMED");
    rogue_next_rsp_valid = 1;
    $display("ROW_UNIT_ADAPTER_UNCAPTURED_REPRO_ARMED req=%0d rsp=%0d", request_count, response_count);
    repeat (10) begin
      @(posedge clk);
      #1;
      if (done_valid)
        $fatal(1, "ROW_UNIT_ADAPTER_NEW_COMPLETION_WITH_UNCAPTURED_RESPONSE");
      if (frame_cfg_valid || next_rsp_ready || next_release_valid || cfg_ready ||
          !epoch_fault || !frame_active || idle || !next_context_owned)
        $fatal(1, "ROW_UNIT_ADAPTER_UNCAPTURED_RESPONSE_NOT_QUARANTINED");
    end
    @(negedge clk);
    rst_n = 0;
    rogue_next_rsp_valid = 0;
    ticks(3);
    rst_n = 1;
    ticks(2);
    if (epoch_fault || frame_active || !idle) $fatal(1, "ROW_UNIT_ADAPTER_QUARANTINE_RESET_FAILED");
    $display("ROW_UNIT_ADAPTER_UNCAPTURED_RESPONSE_PASS");
  endtask

  task automatic repro_unsolicited_frame_done();
    integer count;
    start_case(91);
    accept_context();
    count = 0;
    // The genuine descriptor read is now owned. Inject an unrelated terminal
    // before any external configuration; the owned descriptor must still drain.
    while (request_count != 1 && count < 120) begin ticks(1); count++; end
    if (request_count != 1 || response_count != 0 || frame_cfg_valid || done_valid)
      $fatal(1, "ROW_UNIT_ADAPTER_FRAME_DONE_REPRO_NOT_ARMED");
    frame_done_valid = 1;
    frame_done_error = 0;
    $display("ROW_UNIT_ADAPTER_FRAME_DONE_REPRO_ARMED req=%0d rsp=%0d", request_count, response_count);
    count = 0;
    while (response_count != 1 && count < 120) begin
      ticks(1); count++;
      if (done_valid) $fatal(1, "ROW_UNIT_ADAPTER_NEW_COMPLETION_WITH_UNSOLICITED_FRAME_DONE");
    end
    if (response_count != 1) $fatal(1, "ROW_UNIT_ADAPTER_DID_NOT_DRAIN_ORIGINAL_DESCRIPTOR");
    repeat (10) begin
      @(posedge clk);
      #1;
      if (done_valid)
        $fatal(1, "ROW_UNIT_ADAPTER_NEW_COMPLETION_WITH_UNSOLICITED_FRAME_DONE");
      if (frame_cfg_valid || frame_done_ready || next_release_valid || cfg_ready ||
          !epoch_fault || !frame_active || idle || !next_context_owned)
        $fatal(1, "ROW_UNIT_ADAPTER_UNSOLICITED_FRAME_DONE_NOT_QUARANTINED");
    end
    @(negedge clk);
    rst_n = 0;
    frame_done_valid = 0;
    ticks(3);
    rst_n = 1;
    ticks(2);
    if (epoch_fault || frame_active || !idle) $fatal(1, "ROW_UNIT_ADAPTER_QUARANTINE_RESET_FAILED");
    $display("ROW_UNIT_ADAPTER_UNSOLICITED_FRAME_DONE_PASS");
  endtask

  initial begin
    rst_n = 0;
    cycles = 0;
    test_case = -1;
    defaults();
    if ($test$plusargs("REPRO_UNCAPTURED_RESPONSE")) begin
      repro_uncaptured_response();
      $finish;
    end
    if ($test$plusargs("REPRO_UNSOLICITED_FRAME_DONE")) begin
      repro_unsolicited_frame_done();
      $finish;
    end
    start_case(0);
    accept_context();
    // eA=-10, eG=-7, eU=-8 => gate9, U0=10; cap7 gives
    // gain7, up3, down6; raw down unit exponent6-8-7-7=-16.
    require_command(6'd9, 6'd3, 6'd6, 11'sd7, -12'sd16, -9'sd10, 64'h00200000, 1);
    finish_issued(0, 0, 1);
    // Same completed-parent/bundle context, exact next kept rank, new real
    // caller map identity. Retain the ONE frame lease between these rows.
    cfg_kept_rank = 1;
    cfg_expected_root = 20;
    cfg_expected_input_rank = 8;
    cfg_release_after_row = 1;
    descriptor_word = {3'b010, 9'(-10), 10'd1, 10'd20, 32'h0000a108};
    frame_done_tag = 32'h0000a108;
    frame_out_drained = 0;
    accept_context();
    require_command(6'd9, 6'd3, 6'd6, 11'sd7, -12'sd16, -9'sd10, 64'h00200800, 2);
    finish_issued(0, 1, 2);

    start_case(1);
    cfg_kept_count = 1;
    cfg_release_after_row = 1;
    cfg_bucket_count = 1;
    cfg_bucket_exponents[8:0] = 9'(-10);
    cfg_bucket_gain_caps[8:0] = 9'd4;
    cfg_bucket_down_offsets[8:0] = 0;
    accept_context();
    require_command(6'd9, 6'd6, 6'd4, 11'sd4, -12'sd15, -9'sd10, 64'h00200000, 1);
    finish_issued(0, 1, 1);

    start_case(2);
    cfg_normalization_role = 0; // INPUT must never be silently POST.
    require_rejected();
    if (request_count != 0) $fatal(1, "ROW_UNIT_ADAPTER_READ_INPUT_ROLE_DESCRIPTOR");

    start_case(3);
    cfg_bucket_count = 2;
    cfg_bucket_exponents = {18'b0, 9'(-10), 9'(-10)};
    require_rejected();
    if (request_count != 0) $fatal(1, "ROW_UNIT_ADAPTER_READ_DUPLICATE_POLICY_DESCRIPTOR");

    start_case(4);
    // Exact tag-base difference is8; the real caller map expected input rank7.
    descriptor_word[31:0] = 32'h0000a108;
    require_rejected();
    if (request_count != 1 || response_count != 1)
      $fatal(1, "ROW_UNIT_ADAPTER_REJECTED_WITHOUT_ACTUAL_RESPONSE");

    start_case(5);
    accept_context();
    require_command(6'd9, 6'd3, 6'd6, 11'sd7, -12'sd16, -9'sd10, 64'h00200000, 1);
    abort_valid = 1;
    ticks(3); // Already exposed cfg must remain offered despite fault.
    finish_issued(1, 0, 1);
    if (!epoch_fault || cfg_ready) $fatal(1, "ROW_UNIT_ADAPTER_REUSED_FAULTED_EPOCH");

    start_case(6);
    cfg_release_after_row = 1; // Early frame-wide release is forbidden.
    require_rejected();
    if (request_count != 0) $fatal(1, "ROW_UNIT_ADAPTER_READ_EARLY_RELEASE_CONTEXT");

    start_case(7);
    cfg_kept_rank = 1; // Skip rank0 under a new completed-parent context.
    cfg_release_after_row = 1; // Isolate skipped rank; final-rank flag is legal.
    require_rejected();
    if (request_count != 0) $fatal(1, "ROW_UNIT_ADAPTER_READ_SKIPPED_FIRST_RANK");

    start_case(8);
    cfg_kept_count = 1;
    cfg_release_after_row = 1;
    cfg_gate_exponent = -9'sd8;
    cfg_up_exponent = -9'sd6;
    cfg_down_max_exponent = -9'sd10;
    descriptor_word[60:52] = 9'd0;
    accept_context();
    require_command(6'd0, 6'd0, 6'd0, -11'sd2, -12'sd16, 9'sd0, 64'h00200000, 1);
    finish_issued(0, 1, 1);

    start_case(9);
    cfg_kept_count = 1;
    cfg_release_after_row = 1;
    cfg_gate_exponent = 0;
    cfg_up_exponent = 0;
    cfg_down_max_exponent = -9'sd10;
    cfg_gate_delta_max = 0;
    cfg_up_delta_max = 0;
    descriptor_word[60:52] = 9'(-71);
    accept_context();
    require_command(6'd63, 6'd56, 6'd6, 11'sd7, -12'sd19, -9'sd71, 64'h00200000, 1);
    finish_issued(0, 1, 1);

    start_case(10);
    cfg_gate_exponent = 0;
    cfg_up_exponent = 0;
    cfg_gate_delta_max = 1; // 63+1 must reject before six-bit narrowing.
    descriptor_word[60:52] = 9'(-71);
    require_rejected();

    start_case(11);
    cfg_gate_exponent = 0;
    cfg_up_exponent = 0;
    cfg_gate_delta_max = 0;
    descriptor_word[60:52] = 9'(-72); // Base64 must not wrap to zero.
    require_rejected();

    start_case(12);
    cfg_kept_count = 1;
    cfg_release_after_row = 1;
    cfg_gate_exponent = -9'sd128;
    cfg_up_exponent = 9'sd127;
    cfg_down_max_exponent = 9'sd127;
    descriptor_word[60:52] = 9'd120;
    accept_context();
    require_command(6'd0, 6'd0, 6'd0, -11'sd255, 12'sd374, 9'sd120, 64'h00200000, 1);
    finish_issued(0, 1, 1);

    $display("ROW_UNIT_ADAPTER_PASS cases=13");
    $finish;
  end

  always @(posedge clk) begin
    cycles <= cycles + 1;
    if (cycles > 2000) $fatal(1, "ROW_UNIT_ADAPTER_TESTBENCH_WATCHDOG");
  end
endmodule
