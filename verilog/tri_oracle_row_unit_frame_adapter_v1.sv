`timescale 1ns / 1ps
// Descriptor-derived row units and a direct existing row-frame configuration.
// No tensor buffer, compute array, predictor or residual arithmetic is added.
module tri_oracle_row_unit_frame_adapter_v1 (
    input logic clk, rst_n, abort_valid,
    input logic cfg_valid,
    output logic cfg_ready,
    // Caller holds an acknowledged, successful parent context. The adapter
    // independently joins the actual NextOwner descriptor response below.
    input logic cfg_parent_context_valid, cfg_parent_error,
    input logic [31:0] cfg_tag_base,
    input logic [4:0] cfg_layer, cfg_bundle_layer,
    input logic [15:0] cfg_epoch,
    input logic [9:0] cfg_image_start, cfg_input_count, cfg_kept_count,
    input logic [9:0] cfg_kept_rank, cfg_expected_root, cfg_expected_input_rank,
    input logic cfg_release_after_row,
    // INPUT=0, POST_ATTENTION=1. FIRST_PREFILL=0, ORDINARY_PREFILL=1, DECODE=2.
    input logic [1:0] cfg_normalization_role, cfg_phase,
    input logic [127:0] cfg_bundle_id,
    input logic signed [8:0] cfg_gate_exponent, cfg_up_exponent, cfg_down_max_exponent,
    input logic [2:0] cfg_gate_delta_max, cfg_up_delta_max, cfg_bucket_count,
    // Four signed9 fields, slot0 at bits8:0. All unused slots must be zero.
    input logic [35:0] cfg_bucket_exponents, cfg_bucket_gain_caps, cfg_bucket_down_offsets,
    input logic signed [8:0] cfg_fallback_gain_cap, cfg_fallback_down_offset,
    input logic [63:0] cfg_compact_output_base, cfg_gate_base, cfg_up_base, cfg_down_base,
    input logic [63:0] cfg_row_units_base, cfg_intermediate_base, cfg_down_scale_base,

    // Direct, read-only parent NextOwner transport. One outstanding response.
    input logic next_context_owned,
    output logic next_req_valid, next_req_write,
    input logic next_req_ready,
    output logic [9:0] next_req_word,
    output logic [63:0] next_req_data,
    input logic next_rsp_valid, next_rsp_error,
    input logic [63:0] next_rsp_data,
    output logic next_rsp_ready,
    output logic next_release_valid,
    input logic next_release_ready,

    // Exact existing tri_oracle_external_row_frame configuration boundary.
    output logic frame_cfg_valid,
    input logic frame_cfg_ready,
    output logic frame_cfg_row_enable, frame_cfg_correction_enable,
    output logic [31:0] frame_cfg_tag,
    output logic [4:0] frame_cfg_tokens,
    output logic [15:0] frame_cfg_input_features, frame_cfg_intermediate_features,
    output logic [16:0] frame_cfg_output_features,
    output logic [63:0] frame_cfg_activation_base, frame_cfg_gate_base, frame_cfg_up_base,
    output logic [63:0] frame_cfg_down_base, frame_cfg_intermediate_base, frame_cfg_row_units_base,
    output logic [31:0] frame_cfg_activation_stride,
    output logic [95:0] frame_cfg_gate_shifts, frame_cfg_up_shifts, frame_cfg_down_shifts,
    input logic frame_done_valid, frame_done_error,
    input logic [31:0] frame_done_tag,
    output logic frame_done_ready,
    // Genuine owner-side drain observation: no unaccepted raw output or owned
    // output response remains. A done count alone must not supply this signal.
    input logic frame_out_drained,

    // Stable sidecar for the real raw accumulator consumer; no residual cast.
    output logic row_context_valid,
    output logic [31:0] row_tag,
    output logic [4:0] row_layer,
    output logic [15:0] row_epoch,
    output logic [9:0] row_original_root, row_input_rank, row_kept_rank,
    output logic signed [8:0] row_activation_exponent, row_down_max_exponent,
    output logic signed [10:0] row_up_gain,
    output logic [5:0] row_down_shift,
    // MAX output-weight unit only. Channel c uses this exponent minus its
    // actual matching table decrement; this is not one unit for every lane.
    output logic signed [11:0] row_down_physical_exponent,
    output logic [63:0] row_down_scale_base,
    output logic [127:0] row_bundle_id,
    output logic legacy_residual_writeback_enable,
    output logic done_valid, done_error, epoch_fault, frame_active, idle,
    input logic done_ready
);
  typedef enum logic [3:0] {
    Idle, OfferRead, ReceiveRead, Derive, OfferConfiguration,
    WaitExternal, Completion, BetweenRows, ReleaseOwner, FaultLock
  } state_t;
  typedef struct packed {
    logic [31:0] tag_base;
    logic [4:0] layer;
    logic [15:0] epoch;
    logic [9:0] image_start, input_count, kept_count;
    logic [1:0] normalization_role, phase;
    logic [127:0] bundle_id;
    logic signed [8:0] gate_exponent, up_exponent, down_max_exponent;
    logic [2:0] gate_delta_max, up_delta_max, bucket_count;
    logic [35:0] bucket_exponents, bucket_gain_caps, bucket_down_offsets;
    logic signed [8:0] fallback_gain_cap, fallback_down_offset;
    logic [63:0] compact_output_base, gate_base, up_base, down_base;
    logic [63:0] row_units_base, intermediate_base, down_scale_base;
  } context_t;
  state_t state;
  context_t offered_context, saved_context;
  logic context_held, fault_latched, read_owned, external_started;
  logic read_quarantined, terminal_quarantined;
  logic terminal_seen, terminal_error, completion_error, unit_present;
  logic release_after_row;
  logic [9:0] expected_next_rank, last_input_rank, last_root;
  logic [9:0] requested_rank, expected_root, expected_input_rank;
  logic [63:0] descriptor, activation_address;
  logic [5:0] gate_shift, up_shift, down_shift;
  logic signed [10:0] up_gain;
  logic signed [11:0] physical_exponent;
  logic cfg_fire, request_fire, response_fire, configuration_fire, terminal_fire;
  logic configuration_bad, descriptor_bad, arithmetic_bad, fault_now;
  logic unexpected_read_response, unexpected_terminal, association_bad;
  logic [32:0] maximum_tag, descriptor_input_rank;
  logic [10:0] maximum_position, expected_position;
  logic [64:0] activation_end, gate_end, up_end, down_end;
  logic [64:0] row_units_end, intermediate_end, down_scale_end, row_address;
  logic signed [8:0] descriptor_exponent;
  int signed activation_unit, selected_cap, selected_offset;
  int signed gate_calculation, up_original, gain_calculation;
  int signed up_calculation, down_calculation, physical_calculation;

  function automatic logic overlaps(
      input logic [63:0] first_base, second_base,
      input logic [64:0] first_end, second_end);
    return {1'b0, first_base} <= second_end && {1'b0, second_base} <= first_end;
  endfunction

  always_comb begin
    offered_context.tag_base = cfg_tag_base;
    offered_context.layer = cfg_layer;
    offered_context.epoch = cfg_epoch;
    offered_context.image_start = cfg_image_start;
    offered_context.input_count = cfg_input_count;
    offered_context.kept_count = cfg_kept_count;
    offered_context.normalization_role = cfg_normalization_role;
    offered_context.phase = cfg_phase;
    offered_context.bundle_id = cfg_bundle_id;
    offered_context.gate_exponent = cfg_gate_exponent;
    offered_context.up_exponent = cfg_up_exponent;
    offered_context.down_max_exponent = cfg_down_max_exponent;
    offered_context.gate_delta_max = cfg_gate_delta_max;
    offered_context.up_delta_max = cfg_up_delta_max;
    offered_context.bucket_count = cfg_bucket_count;
    offered_context.bucket_exponents = cfg_bucket_exponents;
    offered_context.bucket_gain_caps = cfg_bucket_gain_caps;
    offered_context.bucket_down_offsets = cfg_bucket_down_offsets;
    offered_context.fallback_gain_cap = cfg_fallback_gain_cap;
    offered_context.fallback_down_offset = cfg_fallback_down_offset;
    offered_context.compact_output_base = cfg_compact_output_base;
    offered_context.gate_base = cfg_gate_base;
    offered_context.up_base = cfg_up_base;
    offered_context.down_base = cfg_down_base;
    offered_context.row_units_base = cfg_row_units_base;
    offered_context.intermediate_base = cfg_intermediate_base;
    offered_context.down_scale_base = cfg_down_scale_base;

    // All endpoint checks retain their carry. These are the exact external
    // one-row/dense-matrix/table extents used by the existing row-frame ports.
    activation_end = {1'b0, cfg_compact_output_base} + 65'(cfg_kept_count) * 65'd2048 - 65'd1;
    gate_end = {1'b0, cfg_gate_base} + 65'd11534335;
    up_end = {1'b0, cfg_up_base} + 65'd11534335;
    down_end = {1'b0, cfg_down_base} + 65'd11534335;
    row_units_end = {1'b0, cfg_row_units_base} + 65'd4543;
    intermediate_end = {1'b0, cfg_intermediate_base} + 65'd5631;
    down_scale_end = {1'b0, cfg_down_scale_base} + 65'd1023;
    row_address = {1'b0, cfg_compact_output_base} + 65'(cfg_kept_rank) * 65'd2048;
    maximum_tag = {1'b0, cfg_tag_base} + 33'd575;
    maximum_position = {1'b0, cfg_image_start} + 11'd575;
    expected_position = {1'b0, cfg_image_start} + {1'b0, cfg_expected_root};
    configuration_bad = !cfg_parent_context_valid || cfg_parent_error ||
      cfg_layer >= 22 || cfg_bundle_layer != cfg_layer || cfg_normalization_role != 1 || cfg_phase != 1 ||
      cfg_input_count == 0 || cfg_input_count > 576 || cfg_kept_count == 0 || cfg_kept_count > cfg_input_count ||
      cfg_kept_rank >= cfg_kept_count || cfg_expected_root >= 576 || cfg_expected_input_rank >= cfg_input_count ||
      cfg_kept_rank != (context_held ? expected_next_rank : 10'd0) ||
      cfg_release_after_row != ({1'b0, cfg_kept_rank} + 11'd1 == {1'b0, cfg_kept_count}) ||
      maximum_tag[32] || maximum_position[10] || expected_position[10] || expected_position == 0 ||
      cfg_compact_output_base[5:0] != 0 || cfg_gate_base[2:0] != 0 || cfg_up_base[2:0] != 0 ||
      cfg_down_base[2:0] != 0 || cfg_row_units_base[5:0] != 0 || cfg_intermediate_base[2:0] != 0 ||
      cfg_down_scale_base[2:0] != 0 || activation_end[64] || gate_end[64] || up_end[64] || down_end[64] ||
      row_units_end[64] || intermediate_end[64] || down_scale_end[64] || row_address[64] || cfg_bucket_count > 4;
    if (context_held && (offered_context != saved_context ||
        cfg_expected_input_rank <= last_input_rank || cfg_expected_root <= last_root)) configuration_bad = 1;
    // The writable scratch region cannot overwrite any still-owned source.
    if (overlaps(cfg_intermediate_base, cfg_compact_output_base, intermediate_end, activation_end) ||
        overlaps(cfg_intermediate_base, cfg_gate_base, intermediate_end, gate_end) ||
        overlaps(cfg_intermediate_base, cfg_up_base, intermediate_end, up_end) ||
        overlaps(cfg_intermediate_base, cfg_down_base, intermediate_end, down_end) ||
        overlaps(cfg_intermediate_base, cfg_row_units_base, intermediate_end, row_units_end) ||
        overlaps(cfg_intermediate_base, cfg_down_scale_base, intermediate_end, down_scale_end)) configuration_bad = 1;
    if (overlaps(cfg_row_units_base, cfg_compact_output_base, row_units_end, activation_end) ||
        overlaps(cfg_row_units_base, cfg_gate_base, row_units_end, gate_end) ||
        overlaps(cfg_row_units_base, cfg_up_base, row_units_end, up_end) ||
        overlaps(cfg_row_units_base, cfg_down_base, row_units_end, down_end)) configuration_bad = 1;
    for (int bucket = 0; bucket < 4; bucket++) begin
      if (bucket >= int'(cfg_bucket_count)) begin
        if (cfg_bucket_exponents[bucket*9+:9] != 0 || cfg_bucket_gain_caps[bucket*9+:9] != 0 ||
            cfg_bucket_down_offsets[bucket*9+:9] != 0) configuration_bad = 1;
      end else begin
        for (int previous_bucket = 0; previous_bucket < 4; previous_bucket++)
          if (previous_bucket < bucket && cfg_bucket_exponents[bucket*9+:9] ==
              cfg_bucket_exponents[previous_bucket*9+:9]) configuration_bad = 1;
      end
    end

    descriptor_input_rank = {1'b0, next_rsp_data[31:0]} - {1'b0, saved_context.tag_base};
    descriptor_bad = next_rsp_data[63:61] != 3'b010 || next_rsp_data[51:42] != requested_rank ||
      next_rsp_data[41:32] >= 576 || next_rsp_data[41:32] != expected_root || descriptor_input_rank[32] ||
      descriptor_input_rank >= 33'(saved_context.input_count) || descriptor_input_rank != 33'(expected_input_rank);

    // Calculate in signed32 before any six-bit/twelve-bit port narrowing.
    // Exponents/caps/offsets are signed9; these sums are far inside signed32.
    descriptor_exponent = $signed(descriptor[60:52]);
    activation_unit = int'($signed(descriptor_exponent));
    selected_cap = int'($signed(saved_context.fallback_gain_cap));
    selected_offset = int'($signed(saved_context.fallback_down_offset));
    for (int bucket = 0; bucket < 4; bucket++)
      if (bucket < int'(saved_context.bucket_count) &&
          $signed(saved_context.bucket_exponents[bucket*9+:9]) == descriptor_exponent) begin
        selected_cap = int'($signed(saved_context.bucket_gain_caps[bucket*9+:9]));
        selected_offset = int'($signed(saved_context.bucket_down_offsets[bucket*9+:9]));
      end
    gate_calculation = -(activation_unit + int'($signed(saved_context.gate_exponent)) + 32'sd8);
    up_original = -(activation_unit + int'($signed(saved_context.up_exponent)) + 32'sd8);
    gain_calculation = up_original < selected_cap ? up_original : selected_cap;
    up_calculation = up_original - gain_calculation;
    down_calculation = gain_calculation + selected_offset;
    if (down_calculation < 0) down_calculation = 0;
    physical_calculation = down_calculation - 32'sd8 - gain_calculation + int'($signed(saved_context.down_max_exponent));
    arithmetic_bad = gate_calculation < 0 || gate_calculation > 63 || up_calculation < 0 || up_calculation > 63 ||
      down_calculation < 0 || down_calculation > 63 ||
      gate_calculation + int'({1'b0, saved_context.gate_delta_max}) > 63 ||
      up_calculation + int'({1'b0, saved_context.up_delta_max}) > 63 ||
      gain_calculation < -1024 || gain_calculation > 1023 || physical_calculation < -2048 || physical_calculation > 2047;

    cfg_ready = rst_n && !fault_latched && !abort_valid && next_context_owned && (state == Idle || state == BetweenRows);
    cfg_fire = cfg_valid && cfg_ready;
    next_req_valid = rst_n && state == OfferRead;
    next_req_write = 0;
    next_req_word = 10'd256 + requested_rank;
    next_req_data = 0;
    // A response seen before ownership cannot acquire an association merely
    // because an already exposed request is accepted later. Keep that channel
    // quarantined until coupled reset; the other known-owned channel may drain.
    next_rsp_ready = rst_n && read_owned && !read_quarantined;
    request_fire = next_req_valid && next_req_ready;
    response_fire = next_rsp_valid && next_rsp_ready;
    frame_cfg_valid = rst_n && state == OfferConfiguration;
    configuration_fire = frame_cfg_valid && frame_cfg_ready;
    frame_done_ready = rst_n && state == WaitExternal && external_started && !terminal_seen && !terminal_quarantined;
    terminal_fire = frame_done_valid && frame_done_ready;
    unexpected_read_response = next_rsp_valid && !read_owned && (context_held || cfg_fire);
    unexpected_terminal = frame_done_valid && (!external_started || terminal_seen) && (context_held || cfg_fire);
    association_bad = read_quarantined || terminal_quarantined || unexpected_read_response || unexpected_terminal;
    fault_now = (context_held && (abort_valid || !next_context_owned)) ||
      association_bad ||
      (cfg_fire && configuration_bad) ||
      (response_fire && (next_rsp_error || descriptor_bad)) ||
      (state == Derive && arithmetic_bad) ||
      (terminal_fire && (frame_done_error || frame_done_tag != descriptor[31:0]));

    // A release is a revocable ownership grant, not a new tensor/request
    // transfer. Fault fences it before acceptance; data/config/status offers
    // above remain stable and their accepted work is always drained.
    next_release_valid = rst_n && state == ReleaseOwner && !fault_latched && !fault_now;
    frame_cfg_row_enable = 1;
    frame_cfg_correction_enable = 0;
    frame_cfg_tag = descriptor[31:0];
    frame_cfg_tokens = 1;
    frame_cfg_input_features = 2048;
    frame_cfg_intermediate_features = 5632;
    frame_cfg_output_features = 2048;
    frame_cfg_activation_base = activation_address;
    frame_cfg_activation_stride = 2048;
    frame_cfg_gate_base = saved_context.gate_base;
    frame_cfg_up_base = saved_context.up_base;
    frame_cfg_down_base = saved_context.down_base;
    frame_cfg_row_units_base = saved_context.row_units_base;
    frame_cfg_intermediate_base = saved_context.intermediate_base;
    frame_cfg_gate_shifts = {90'b0, gate_shift};
    frame_cfg_up_shifts = {90'b0, up_shift};
    frame_cfg_down_shifts = {90'b0, down_shift};
    row_context_valid = rst_n && unit_present;
    row_tag = descriptor[31:0];
    row_layer = saved_context.layer;
    row_epoch = saved_context.epoch;
    row_original_root = descriptor[41:32];
    row_input_rank = expected_input_rank;
    row_kept_rank = requested_rank;
    row_activation_exponent = descriptor_exponent;
    row_down_max_exponent = saved_context.down_max_exponent;
    row_up_gain = up_gain;
    row_down_shift = down_shift;
    row_down_physical_exponent = physical_exponent;
    row_down_scale_base = saved_context.down_scale_base;
    row_bundle_id = saved_context.bundle_id;
    legacy_residual_writeback_enable = 0;
    done_valid = rst_n && state == Completion;
    done_error = completion_error;
    epoch_fault = rst_n && fault_latched;
    frame_active = rst_n && context_held;
    idle = rst_n && state == Idle && !context_held && !fault_latched && !read_owned && !next_rsp_valid;
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state <= Idle;
      saved_context <= '0;
      context_held <= 0;
      fault_latched <= 0;
      read_owned <= 0;
      external_started <= 0;
      read_quarantined <= 0;
      terminal_quarantined <= 0;
      terminal_seen <= 0;
      terminal_error <= 0;
      completion_error <= 0;
      unit_present <= 0;
      release_after_row <= 0;
      expected_next_rank <= 0;
      last_input_rank <= 0;
      last_root <= 0;
      requested_rank <= 0;
      expected_root <= 0;
      expected_input_rank <= 0;
      descriptor <= 0;
      activation_address <= 0;
      gate_shift <= 0;
      up_shift <= 0;
      down_shift <= 0;
      up_gain <= 0;
      physical_exponent <= 0;
    end else begin
      if (fault_now) fault_latched <= 1;
      // Sample association against PRE-edge ownership, before committing any
      // current handshake. A legitimate final ACK may clear its producer after
      // this edge without being mistaken for an unsolicited response here.
      if (unexpected_read_response) read_quarantined <= 1;
      if (unexpected_terminal) terminal_quarantined <= 1;
      case (state)
        Idle, BetweenRows: begin
          if (cfg_fire) begin
            if (!context_held) saved_context <= offered_context;
            context_held <= 1;
            requested_rank <= cfg_kept_rank;
            expected_root <= cfg_expected_root;
            expected_input_rank <= cfg_expected_input_rank;
            release_after_row <= cfg_release_after_row;
            activation_address <= row_address[63:0];
            external_started <= 0;
            terminal_seen <= 0;
            terminal_error <= 0;
            unit_present <= 0;
            if (configuration_bad || fault_now) begin
              completion_error <= 1;
              state <= state_t'(association_bad ? FaultLock : Completion);
            end else state <= OfferRead;
          end else if (context_held && fault_now) state <= FaultLock;
        end
        // Once exposed, neither a fault nor lost ownership retracts this
        // request/configuration. Coupled reset is the only forced cancellation.
        OfferRead: if (request_fire) begin read_owned <= 1; state <= ReceiveRead; end
        ReceiveRead: if (response_fire) begin
          read_owned <= 0;
          descriptor <= next_rsp_data;
          if (association_bad) begin
            // The known descriptor response has drained, but an unassociated
            // response on either channel forbids a NEW completion packet.
            state <= FaultLock;
          end else if (fault_latched || fault_now || next_rsp_error || descriptor_bad) begin
            completion_error <= 1;
            state <= Completion;
          end else state <= Derive;
        end
        Derive: begin
          if (association_bad) state <= FaultLock;
          else if (fault_latched || fault_now || arithmetic_bad) begin
            completion_error <= 1;
            state <= Completion;
          end else begin
            gate_shift <= 6'(gate_calculation);
            up_shift <= 6'(up_calculation);
            down_shift <= 6'(down_calculation);
            up_gain <= 11'(gain_calculation);
            physical_exponent <= 12'(physical_calculation);
            unit_present <= 1;
            state <= OfferConfiguration;
          end
        end
        OfferConfiguration: if (configuration_fire) begin external_started <= 1; state <= WaitExternal; end
        WaitExternal: begin
          if (terminal_fire) begin
            terminal_seen <= 1;
            terminal_error <= frame_done_error || frame_done_tag != descriptor[31:0];
          end
          if (terminal_seen && frame_out_drained && !read_owned && !next_rsp_valid) begin
            if (association_bad) state <= FaultLock;
            else begin
              completion_error <= terminal_error || fault_latched || fault_now;
              state <= Completion;
            end
          end
        end
        Completion: if (done_ready) begin
          // Never rewrite a held success/error packet when a late fault
          // arrives. Its acceptance still cannot release a faulted epoch.
          if (completion_error || fault_latched || fault_now) state <= FaultLock;
          else begin
            expected_next_rank <= requested_rank + 1'b1;
            last_input_rank <= expected_input_rank;
            last_root <= expected_root;
            unit_present <= 0;
            external_started <= 0;
            terminal_seen <= 0;
            state <= state_t'(release_after_row ? ReleaseOwner : BetweenRows);
          end
        end
        ReleaseOwner: begin
          if (fault_latched || fault_now) state <= FaultLock;
          else if (next_release_valid && next_release_ready) begin
            context_held <= 0;
            expected_next_rank <= 0;
            state <= Idle;
          end
        end
        FaultLock: begin end
        default: begin fault_latched <= 1; state <= FaultLock; end
      endcase
    end
  end
endmodule
