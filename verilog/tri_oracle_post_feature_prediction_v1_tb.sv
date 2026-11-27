`timescale 1ns / 1ps
// SYNTHETIC CONTROLLER UNIT ONLY: the explicit predictor peer below validates
// packets and returns chosen masks. No physical fabric/core, C, trained weights,
// row compute, TMU, model or actual archive appears in this testbench.
module tri_oracle_post_feature_prediction_tb;
  logic clk, rst_n, abort_valid, next_context_owned, strip_fabric_owned;
  logic cfg_valid, cfg_ready, cfg_archive_committed, cfg_scalar_weight_units;
  logic [1:0] cfg_normalization_role;
  logic [31:0] cfg_tag;
  logic [4:0] cfg_layer;
  logic [15:0] cfg_epoch;
  logic [9:0] cfg_original_root, cfg_input_rank, cfg_kept_rank;
  logic signed [8:0] cfg_exponent;
  logic [127:0] cfg_bundle_id;
  logic [63:0] cfg_feature_base, cfg_feature_bytes, cfg_gate_sign_base, cfg_gate_sign_bytes;
  logic [63:0] cfg_up_sign_base, cfg_up_sign_bytes;
  logic req_valid, req_ready, rsp_valid, rsp_ready, rsp_last, rsp_error;
  logic [63:0] req_address, rsp_data;
  logic [4:0] req_length;
  logic [533:0] strip_request;
  logic [111:0] strip_response;
  logic mask_valid, mask_ready, mask_last;
  logic [31:0] mask_tag;
  logic [15:0] mask_start;
  logic [6:0] mask_count;
  logic [1279:0] mask_bits;
  logic done_valid, done_ready, done_error;
  logic [31:0] done_tag;
  logic [4:0] done_layer;
  logic [15:0] done_epoch;
  logic [9:0] done_original_root, done_input_rank, done_kept_rank;
  logic signed [8:0] done_exponent;
  logic [127:0] done_bundle_id;
  logic [7:0] completed_groups;
  logic [15:0] accepted_strips;
  logic [6:0] accepted_masks;
  logic epoch_fault, active, port_idle, strip_quiet, idle;
  logic peer_owned, peer_valid, peer_last, peer_error;
  logic [63:0] peer_address, peer_data;
  logic [4:0] peer_length;
  logic [1:0] peer_kind;
  logic hold_request, hold_response, hold_predictor, hold_mask;
  logic rogue_response, rogue_prediction, inject_memory_error, model_result_valid;
  logic model_in_ready;
  logic [31:0] model_skip, model_gate, model_up;
  logic [4:0] clusters_seen;
  integer cycles, test_case, selected_case, cfg_accepts;
  integer requests, responses, feature_requests, sign_requests;
  integer peer_beat, peer_delay, pred_group, pred_strip, pred_transfers, group_results;
  integer masks, gate_acks, up_acks;
  logic [63:0] saved_feature_base, saved_gate_base, saved_up_base, selected_row_base;
  logic [31:0] saved_tag;
  logic [4:0] saved_layer;
  logic [15:0] saved_epoch;
  logic [9:0] saved_root, saved_input_rank, saved_kept_rank;
  logic signed [8:0] saved_exponent;
  logic [127:0] saved_bundle;
  logic request_held, strip_held, mask_held, done_held;
  logic [68:0] held_request;
  logic [532:0] held_strip;
  typedef struct packed {
    logic last;
    logic [31:0] tag;
    logic [15:0] start;
    logic [6:0] count;
    logic [1279:0] bits;
  } mask_packet_t;
  typedef struct packed {
    logic error;
    logic [31:0] tag;
    logic [4:0] layer;
    logic [15:0] epoch;
    logic [9:0] root, input_rank, kept_rank;
    logic signed [8:0] exponent;
    logic [127:0] bundle;
  } done_packet_t;
  mask_packet_t held_mask;
  done_packet_t held_done;

  tri_oracle_post_feature_prediction_v1 dut (
    .clk, .rst_n, .abort_valid, .next_context_owned, .strip_fabric_owned,
    .cfg_valid, .cfg_ready, .cfg_archive_committed, .cfg_scalar_weight_units, .cfg_normalization_role,
    .cfg_tag, .cfg_layer, .cfg_epoch, .cfg_original_root, .cfg_input_rank, .cfg_kept_rank,
    .cfg_exponent, .cfg_bundle_id, .cfg_feature_base, .cfg_feature_bytes,
    .cfg_gate_sign_base, .cfg_gate_sign_bytes, .cfg_up_sign_base, .cfg_up_sign_bytes,
    .req_valid, .req_ready, .req_address, .req_length, .rsp_valid, .rsp_ready, .rsp_last, .rsp_error, .rsp_data,
    .strip_request, .strip_response, .mask_valid, .mask_ready, .mask_last, .mask_tag, .mask_start, .mask_count, .mask_bits,
    .done_valid, .done_ready, .done_error, .done_tag, .done_layer, .done_epoch,
    .done_original_root, .done_input_rank, .done_kept_rank, .done_exponent, .done_bundle_id,
    .completed_groups, .accepted_strips, .accepted_masks, .epoch_fault, .active, .port_idle, .strip_quiet, .idle
  );
  assign req_ready = rst_n && !peer_owned && !peer_valid && !hold_request && cycles % 5 != 1;
  assign rsp_valid = rogue_response || peer_valid;
  assign rsp_last = rogue_response ? 1'b1 : peer_last;
  assign rsp_error = !rogue_response && peer_error;
  assign rsp_data = rogue_response ? 64'hbad0_bad0_bad0_bad0 : peer_data;
  assign model_in_ready = rst_n && !model_result_valid && !hold_predictor && cycles % 4 != 2;
  assign model_gate = model_skip | 32'haa55aa55;
  assign model_up = model_skip | 32'h55aa55aa;
  assign strip_response = {model_in_ready, (rogue_prediction || model_result_valid), 1'b0,
    model_gate, model_up, model_skip, 13'd240};
  assign mask_ready = rst_n && !hold_mask && cycles % 7 != 2;
  initial clk = 0;
  always #5 clk = ~clk;

  function automatic logic [7:0] active_bits(input integer strip);
    return strip % 17 == 0 ? 8'd0 : (8'd1 << (strip % 8));
  endfunction
  function automatic logic [7:0] input_negative(input integer strip);
    return strip % 2 == 1 ? active_bits(strip) : 8'd0;
  endfunction
  function automatic logic [7:0] normalized_negative(input integer strip);
    return 8'((strip * 53 + 167) ^ (strip << 1));
  endfunction
  function automatic logic [7:0] archive_byte(input integer offset);
    case (offset % 3)
      0: return active_bits(offset / 3);
      1: return normalized_negative(offset / 3);
      default: return input_negative(offset / 3);
    endcase
  endfunction
  function automatic logic weight_negative(input logic up, input integer channel, feature);
    return 1'((channel * 13 + feature * 7 + (up ? 3 : 0)) ^ (channel >> 3) ^ (feature >> 4));
  endfunction
  function automatic logic chosen_skip(input integer channel);
    // Deliberately chosen response pattern: validates transport/repacking only,
    // NEVER a substitute for real core prediction or trained sign arithmetic.
    return 1'((channel * 7 + (channel >> 3) + 90) ^ (channel >> 5));
  endfunction
  function automatic logic [63:0] memory_word(input logic [1:0] kind, input logic [63:0] address);
    logic [63:0] value;
    integer offset, group_index, first_feature;
    value = 0;
    if (kind == 0) begin
      offset = int'(address - selected_row_base);
      for (integer lane = 0; lane < 8; lane++) value[lane*8+:8] = archive_byte(offset + lane);
    end else begin
      offset = int'(address - (kind == 2 ? saved_up_base : saved_gate_base));
      group_index = offset / 8192; first_feature = (offset % 8192) / 4;
      for (integer half = 0; half < 2; half++)
        for (integer channel = 0; channel < 32; channel++)
          value[32*half + channel] = weight_negative(kind == 2, 32*group_index + channel, first_feature + half);
    end
    return value;
  endfunction
  function automatic mask_packet_t mask_packet();
    return {mask_last, mask_tag, mask_start, mask_count, mask_bits};
  endfunction
  function automatic done_packet_t done_packet();
    return {done_error, done_tag, done_layer, done_epoch, done_original_root,
      done_input_rank, done_kept_rank, done_exponent, done_bundle_id};
  endfunction

  always_ff @(posedge clk or negedge rst_n) begin : external_read_endpoint
    if (!rst_n) begin
      peer_owned <= 0; peer_valid <= 0; peer_last <= 0; peer_error <= 0; peer_data <= 0;
      peer_address <= 0; peer_length <= 0; peer_kind <= 0; peer_beat <= 0; peer_delay <= 0;
    end else begin
      if (req_valid && req_ready) begin
        if (peer_owned || peer_valid) $fatal(1, "POST_PREDICTION_MULTIPLE_OWNED_READS");
        peer_owned <= 1; peer_address <= req_address; peer_length <= req_length;
        peer_kind <= req_address >= saved_up_base ? 2 : (req_address >= saved_gate_base ? 1 : 0);
        peer_beat <= 0; peer_delay <= 0;
      end
      if (peer_owned && !peer_valid && !hold_response) begin
        if (peer_delay >= 1) begin
          peer_valid <= 1; peer_last <= peer_beat + 1 == int'(peer_length);
          peer_error <= inject_memory_error;
          peer_data <= memory_word(peer_kind, peer_address + 64'(peer_beat)*8);
        end else peer_delay <= peer_delay + 1;
      end
      if (peer_valid && !rogue_response && rsp_ready) begin
        peer_valid <= 0; peer_delay <= 0;
        if (peer_last) peer_owned <= 0;
        else peer_beat <= peer_beat + 1;
      end
    end
  end

  always_ff @(posedge clk or negedge rst_n) begin : synthetic_predictor_peer
    if (!rst_n) begin
      pred_group <= 0; pred_strip <= 0; pred_transfers <= 0; group_results <= 0;
      model_result_valid <= 0; model_skip <= 0; clusters_seen <= 0;
    end else begin
      if (model_result_valid && strip_request[533:531] !== 3'(pred_group % 5))
        $fatal(1, "POST_PREDICTION_CHANGED_RESULT_OWNER group=%0d", pred_group);
      if (strip_request[530] && model_in_ready) begin
        if (model_result_valid || pred_group >= 176 || strip_request[533:531] !== 3'(pred_group % 5) ||
            strip_request[529] !== (pred_strip == 255) || strip_request[519:512] !== active_bits(pred_strip) ||
            strip_request[527:520] !== input_negative(pred_strip))
          $fatal(1, "POST_PREDICTION_WRONG_STRIP_FLAGS group=%0d strip=%0d", pred_group, pred_strip);
        for (integer channel = 0; channel < 32; channel++)
          for (integer lane = 0; lane < 8; lane++) begin
            if (strip_request[256+8*channel+lane] !==
                  (active_bits(pred_strip)[lane] && weight_negative(0, 32*pred_group+channel, 8*pred_strip+lane)) ||
                strip_request[8*channel+lane] !==
                  (active_bits(pred_strip)[lane] && weight_negative(1, 32*pred_group+channel, 8*pred_strip+lane)))
              $fatal(1, "POST_PREDICTION_WRONG_SIGN_LAYOUT group=%0d strip=%0d channel=%0d lane=%0d", pred_group, pred_strip, channel, lane);
          end
        if ((active_bits(pred_strip) != 0 && (gate_acks != 1 || up_acks != 1)) ||
            (active_bits(pred_strip) == 0 && (gate_acks != 0 || up_acks != 0)))
          $fatal(1, "POST_PREDICTION_BEFORE_REAL_SIGN_RESPONSE group=%0d strip=%0d", pred_group, pred_strip);
        pred_transfers <= pred_transfers + 1; clusters_seen[pred_group % 5] <= 1;
        if (pred_strip == 255) begin
          for (integer lane = 0; lane < 32; lane++) model_skip[lane] <= chosen_skip(32*pred_group+lane);
          model_result_valid <= 1;
        end else pred_strip <= pred_strip + 1;
      end
      if (model_result_valid && !rogue_prediction && strip_request[528]) begin
        model_result_valid <= 0; pred_group <= pred_group + 1; pred_strip <= 0; group_results <= group_results + 1;
      end
    end
  end

  always_ff @(posedge clk or negedge rst_n) begin : observable_protocol_checks
    integer offset, request_group, request_strip;
    if (!rst_n) begin
      cycles <= 0; cfg_accepts <= 0; requests <= 0; responses <= 0; feature_requests <= 0; sign_requests <= 0;
      masks <= 0; gate_acks <= 0; up_acks <= 0;
      request_held <= 0; strip_held <= 0; mask_held <= 0; done_held <= 0;
      held_request <= 0; held_strip <= 0; held_mask <= '0; held_done <= '0;
    end else begin
      cycles <= cycles + 1;
      if (cycles > 2500000) $fatal(1, "POST_PREDICTION_WATCHDOG case=%0d", test_case);
      if (cfg_valid && cfg_ready) cfg_accepts <= cfg_accepts + 1;
      if (request_held && (!req_valid || {req_address, req_length} !== held_request)) $fatal(1, "POST_PREDICTION_RETRACTED_READ");
      if (strip_held && (!strip_request[530] || {strip_request[533:529],strip_request[527:0]} !== held_strip))
        $fatal(1, "POST_PREDICTION_RETRACTED_STRIP");
      if (mask_held && (!mask_valid || mask_packet() !== held_mask)) $fatal(1, "POST_PREDICTION_RETRACTED_KEEP");
      if (done_held && (!done_valid || done_packet() !== held_done)) $fatal(1, "POST_PREDICTION_REWROTE_DONE");
      if (req_valid && req_ready) begin
        requests <= requests + 1;
        if (req_address >= selected_row_base && req_address < selected_row_base + 768) begin
          if (req_length != 8 || req_address !== selected_row_base + 64'(feature_requests % 12)*64 ||
              feature_requests / 12 != group_results)
            $fatal(1, "POST_PREDICTION_WRONG_FEATURE_OR_EARLY_GROUP_READ group=%0d", pred_group);
          feature_requests <= feature_requests + 1;
        end else begin
          if (req_length != 1 || req_address[2:0] != 0 ||
              !((req_address >= saved_gate_base && req_address < saved_gate_base + 1441792) ||
                (req_address >= saved_up_base && req_address < saved_up_base + 1441792)))
            $fatal(1, "POST_PREDICTION_WRONG_SIGN_READ");
          offset = int'(req_address - (req_address >= saved_up_base ? saved_up_base : saved_gate_base));
          request_group = offset / 8192; request_strip = (offset % 8192) / 32;
          if (request_group != pred_group || request_strip != pred_strip || active_bits(pred_strip) == 0 ||
              (offset % 32) / 8 != (pred_strip % 8) / 2)
            $fatal(1, "POST_PREDICTION_SIGN_ADDRESS_WRONG_GROUP_OR_PAIR");
          sign_requests <= sign_requests + 1;
        end
      end
      if (peer_valid && !rogue_response && rsp_ready) begin
        responses <= responses + 1;
        if (peer_kind == 1 && peer_last) gate_acks <= gate_acks + 1;
        if (peer_kind == 2 && peer_last) up_acks <= up_acks + 1;
      end
      if (strip_request[530] && model_in_ready) begin gate_acks <= 0; up_acks <= 0; end
      if (mask_valid && mask_ready) begin
        if (masks >= 71 || mask_tag !== saved_tag || mask_start !== 16'(masks*80) ||
            mask_count !== (masks == 70 ? 7'd32 : 7'd80) || mask_last !== (masks == 70) || mask_bits[1279:80] != 0)
          $fatal(1, "POST_PREDICTION_WRONG_KEEP_PACKET packet=%0d", masks);
        for (integer lane = 0; lane < 80; lane++)
          if (mask_bits[lane] !== (lane < int'(mask_count) ? !chosen_skip(masks*80+lane) : 1'b0))
            $fatal(1, "POST_PREDICTION_WRONG_KEEP_BIT packet=%0d lane=%0d", masks, lane);
        masks <= masks + 1;
      end
      if (done_valid && !done_error && !done_held &&
          (pred_transfers != 45056 || group_results != 176 || masks != 71 || completed_groups != 176 ||
           accepted_strips != 45056 || accepted_masks != 71 || clusters_seen != 5'b11111 ||
           feature_requests != 2112 || sign_requests != 84480 || responses != 101376 ||
           peer_owned || peer_valid || model_result_valid || req_valid || rsp_valid || strip_request[530] || mask_valid || !strip_quiet))
        $fatal(1, "POST_PREDICTION_FALSE_EARLY_SUCCESS");
      if (done_valid && (done_tag !== saved_tag || done_layer !== saved_layer || done_epoch !== saved_epoch ||
          done_original_root !== saved_root || done_input_rank !== saved_input_rank || done_kept_rank !== saved_kept_rank ||
          done_exponent !== saved_exponent || done_bundle_id !== saved_bundle)) $fatal(1, "POST_PREDICTION_WRONG_DONE_CONTEXT");
      request_held <= req_valid && !req_ready;
      strip_held <= strip_request[530] && !model_in_ready;
      mask_held <= mask_valid && !mask_ready; done_held <= done_valid && !done_ready;
      held_request <= {req_address,req_length}; held_strip <= {strip_request[533:529],strip_request[527:0]};
      held_mask <= mask_packet(); held_done <= done_packet();
    end
  end

  task automatic ticks(input integer count);
    repeat (count) @(negedge clk);
  endtask
  task automatic defaults();
    abort_valid = 0; next_context_owned = 1; strip_fabric_owned = 1; cfg_valid = 0;
    cfg_archive_committed = 1; cfg_scalar_weight_units = 1; cfg_normalization_role = 1;
    cfg_tag = 32'h504f0002; cfg_layer = 0; cfg_epoch = 1; cfg_original_root = 19;
    cfg_input_rank = 2; cfg_kept_rank = 2; cfg_exponent = -9'sd14;
    cfg_bundle_id = 128'h4f53545f505245445f544553545f3031;
    cfg_feature_base = 64'h40000000; cfg_feature_bytes = 442368;
    cfg_gate_sign_base = 64'h50000000; cfg_gate_sign_bytes = 1441792;
    cfg_up_sign_base = 64'h60000000; cfg_up_sign_bytes = 1441792;
    done_ready = 0; hold_request = 0; hold_response = 0; hold_predictor = 0; hold_mask = 0;
    rogue_response = 0; rogue_prediction = 0; inject_memory_error = 0;
  endtask
  task automatic start_case(input integer number);
    @(negedge clk); rst_n = 0; defaults(); test_case = number;
    ticks(3); rst_n = 1; ticks(2);
  endtask
  task automatic capture_expected();
    saved_feature_base = cfg_feature_base; saved_gate_base = cfg_gate_sign_base; saved_up_base = cfg_up_sign_base;
    selected_row_base = cfg_feature_base + 64'(cfg_kept_rank)*768;
    saved_tag = cfg_tag; saved_layer = cfg_layer; saved_epoch = cfg_epoch; saved_root = cfg_original_root;
    saved_input_rank = cfg_input_rank; saved_kept_rank = cfg_kept_rank; saved_exponent = cfg_exponent; saved_bundle = cfg_bundle_id;
  endtask
  task automatic accept_context();
    integer limit;
    capture_expected(); cfg_valid = 1; limit = 0;
    forever begin
      @(posedge clk); if (cfg_ready === 1'b1) break;
      limit++; if (limit > 30) $fatal(1, "POST_PREDICTION_NO_CFG_ACCEPTANCE case=%0d", test_case);
    end
    @(negedge clk); cfg_valid = 0;
  endtask
  task automatic first_read();
    integer limit;
    limit = 0;
    while (!req_valid && requests == 0 && limit < 100) begin ticks(1); limit++; end
    if (!req_valid && requests == 0) begin
      if (cfg_accepts != 1 || !active) $fatal(1, "POST_PREDICTION_RED_NOT_ARMED");
      $fatal(1, "POST_FEATURE_PREDICTION_EXPECTED_READ case=%0d cfg=%0d requests=%0d strips=%0d", test_case,cfg_accepts,requests,pred_transfers);
    end
  endtask
  task automatic await_status(input logic error_expected);
    integer limit;
    limit = 0;
    while (!done_valid && limit < 2000000) begin ticks(1); limit++; end
    if (!done_valid || done_error !== error_expected || !active) $fatal(1, "POST_PREDICTION_WRONG_OR_MISSING_DONE");
    ticks(4); done_ready = 1; @(posedge clk); @(negedge clk); done_ready = 0; ticks(3);
    if (error_expected) begin
      if (!active || !epoch_fault || idle || cfg_ready) $fatal(1, "POST_PREDICTION_ERROR_RELEASED_CONTEXT");
    end else if (!idle || active || epoch_fault || !port_idle || !strip_quiet) $fatal(1, "POST_PREDICTION_NOT_RETIRED");
  endtask
  task automatic run_case(input integer number);
    integer limit;
    start_case(number);
    case (number)
      0: begin
        accept_context(); first_read();
        cfg_tag = 0; cfg_bundle_id = 0; cfg_feature_base = 0; cfg_gate_sign_base = 0; cfg_up_sign_base = 0;
        await_status(0);
      end
      10,11,12,13,14,15: begin
        case (number)
          10: cfg_normalization_role = 0;
          11: cfg_scalar_weight_units = 0;
          12: cfg_gate_sign_bytes = 1441784;
          13: cfg_up_sign_base = cfg_gate_sign_base;
          14: cfg_gate_sign_base = 64'hfffffffffffffff8;
          15: cfg_feature_bytes = 768;
          default: begin end
        endcase
        accept_context(); await_status(1);
        if (requests || pred_transfers || masks) $fatal(1, "POST_PREDICTION_INVALID_CFG_CREATED_WORK");
      end
      20,21,22: begin
        if (number == 20) next_context_owned = 0;
        if (number == 21) strip_fabric_owned = 0;
        if (number == 22) cfg_archive_committed = 0;
        capture_expected(); cfg_valid = 1; ticks(8);
        if (cfg_accepts || cfg_ready || req_valid || strip_request[530] || mask_valid || done_valid)
          $fatal(1, "POST_PREDICTION_UNAUTHORIZED_ADMISSION");
        cfg_valid = 0;
      end
      30: begin
        inject_memory_error = 1; accept_context(); first_read(); await_status(1);
        if (requests != 1 || responses != 8 || pred_transfers || masks || peer_owned)
          $fatal(1, "POST_PREDICTION_FIRST_LINE_ERROR_NOT_DRAINED");
      end
      40: begin
        hold_mask = 1; accept_context(); first_read(); limit = 0;
        while (!mask_valid && limit < 100000) begin ticks(1); limit++; end
        if (!mask_valid) $fatal(1, "POST_PREDICTION_NO_HELD_KEEP_TARGET");
        ticks(4); abort_valid = 1; ticks(4); hold_mask = 0; ticks(20);
        if (!epoch_fault || !active || idle || cfg_ready || masks < 1)
          $fatal(1, "POST_PREDICTION_ABORT_LOST_KEEP_OR_CONTEXT");
      end
      41: begin
        hold_predictor = 1; accept_context(); first_read(); limit = 0;
        while (!strip_request[530] && limit < 2000) begin ticks(1); limit++; end
        if (!strip_request[530]) $fatal(1, "POST_PREDICTION_NO_HELD_STRIP_TARGET");
        ticks(3); abort_valid = 1; ticks(4); hold_predictor = 0; ticks(30);
        if (pred_transfers != 1 || !epoch_fault || !active || strip_quiet || idle || done_valid || cfg_ready)
          $fatal(1, "POST_PREDICTION_PARTIAL_GROUP_FAKED_QUIET");
      end
      42: begin
        hold_request = 1; accept_context(); first_read(); ticks(3); rogue_response = 1;
        ticks(4); hold_request = 0; ticks(8);
        if (requests != 1 || rsp_ready || !epoch_fault || !active || idle || done_valid)
          $fatal(1, "POST_PREDICTION_RETROACTIVE_RESPONSE_ASSOCIATION");
        rogue_response = 0; ticks(3);
        if (!epoch_fault || done_valid || cfg_ready) $fatal(1, "POST_PREDICTION_RESPONSE_QUARANTINE_CLEARED");
      end
      43: begin
        // Raw predictor response has no tag: a result before LAST is unknown.
        hold_request = 1; accept_context(); first_read(); rogue_prediction = 1; ticks(8);
        if (!epoch_fault || !active || idle || strip_quiet || done_valid || strip_request[528])
          $fatal(1, "POST_PREDICTION_UNASSOCIATED_RESULT_ACCEPTED");
      end
      44: begin
        // Genuine public cfg handshake enters FaultDrain without creating any
        // child work. Inject BEFORE its next quiet/error-completion edge.
        cfg_normalization_role = 0; accept_context();
        if (cfg_accepts != 1 || !active || done_valid || requests != 0 || pred_transfers != 0)
          $fatal(1, "POST_PREDICTION_FAULT_DRAIN_REPRO_NOT_ARMED cfg=%0d active=%b done=%b",cfg_accepts,active,done_valid);
        rogue_prediction = 1; ticks(1);
        if (done_valid)
          $fatal(1, "POST_PREDICTION_UNKNOWN_FAULT_DRAIN_CREATED_DONE cfg=%0d active=%b error=%b",cfg_accepts,active,done_error);
        if (!epoch_fault || !active || strip_quiet || strip_request[528] || cfg_ready)
          $fatal(1, "POST_PREDICTION_FAULT_DRAIN_UNKNOWN_NOT_QUARANTINED");
        ticks(4);
        if (done_valid || !epoch_fault || !active || strip_quiet || strip_request[528] || cfg_ready)
          $fatal(1, "POST_PREDICTION_FAULT_DRAIN_UNKNOWN_HOLD_ESCAPED");
        rogue_prediction = 0; ticks(4);
        if (done_valid || !epoch_fault || !active || strip_quiet || strip_request[528] || cfg_ready || idle)
          $fatal(1, "POST_PREDICTION_FAULT_DRAIN_QUARANTINE_NOT_STICKY");
      end
      default: $fatal(1, "POST_PREDICTION_UNKNOWN_CASE=%0d", number);
    endcase
    $display("POST_PREDICTION_CASE_PASS case=%0d cfg=%0d reads=%0d beats=%0d strips=%0d groups=%0d masks=%0d mock_only=1",number,cfg_accepts,requests,responses,pred_transfers,group_results,masks);
  endtask
  initial begin
    rst_n = 0; defaults(); test_case = -1; selected_case = 0;
    saved_feature_base = 0; saved_gate_base = 0; saved_up_base = 0; selected_row_base = 0;
    saved_tag = 0; saved_layer = 0; saved_epoch = 0; saved_root = 0; saved_input_rank = 0;
    saved_kept_rank = 0; saved_exponent = 0; saved_bundle = 0;
    if ($test$plusargs("POST_PREDICTION_ALL")) begin
      run_case(0); for(integer number=10;number<=15;number++)run_case(number);
      run_case(20);run_case(21);run_case(22);run_case(30);
      for(integer number=40;number<=44;number++)run_case(number);
    end else begin
      if ($value$plusargs("POST_PREDICTION_CASE=%d",selected_case))begin end
      run_case(selected_case);
    end
    $display("POST_PREDICTION_TB_PASS synthetic_controller_only=1");
    $finish;
  end
endmodule
