`timescale 1ns / 1ps
// Synthetic feature-packet/real-write-mux unit only; no C, SRAM or model gold.
module tri_oracle_post_feature_store_tb;
  logic clk, rst_n, abort_valid, producer_idle, next_context_owned;
  logic cfg_valid, cfg_ready;
  logic [1:0] cfg_normalization_role;
  logic [31:0] cfg_tag;
  logic [4:0] cfg_layer;
  logic [15:0] cfg_epoch;
  logic [9:0] cfg_original_root, cfg_input_rank, cfg_kept_rank;
  logic [63:0] cfg_feature_base, cfg_feature_bytes, cfg_code_base, cfg_code_bytes;
  logic [63:0] cfg_immutable_input_base, cfg_immutable_input_bytes;
  logic aux_valid, aux_ready, aux_last, aux_error;
  logic [31:0] aux_tag;
  logic [4:0] aux_layer;
  logic [15:0] aux_epoch;
  logic [9:0] aux_original_root, aux_input_rank, aux_kept_rank, aux_index;
  logic [3:0] aux_count;
  logic signed [8:0] aux_exponent;
  logic signed [8:0] configured_exponent;
  logic [7:0] aux_outlier_mask, aux_normalized_negative, aux_outlier_negative;
  logic scalar_req_valid, scalar_req_ready, scalar_data_valid, scalar_data_ready, scalar_data_last;
  logic [63:0] scalar_req_address, scalar_data;
  logic [4:0] scalar_req_length;
  logic [7:0] scalar_strobe;
  logic scalar_rsp_valid, scalar_rsp_ready, scalar_rsp_error;
  logic mux_scalar_rsp_valid, mux_scalar_rsp_error, rogue_rsp_valid;
  logic done_valid, done_ready, done_error, epoch_fault, active, port_idle, idle;
  logic [31:0] done_tag;
  logic [4:0] done_layer;
  logic [15:0] done_epoch;
  logic [9:0] done_original_root, done_input_rank, done_kept_rank;
  logic signed [8:0] done_exponent;
  logic [8:0] accepted_strips;
  logic [3:0] acknowledged_lines;
  logic mem_req_valid, mem_req_ready, mem_data_valid, mem_data_ready, mem_data_last;
  logic [63:0] mem_req_address, mem_data;
  logic [4:0] mem_req_length;
  logic [7:0] mem_strobe;
  logic mem_rsp_valid, mem_rsp_ready, mem_rsp_error;
  logic mem_owned, all_data_seen, first_scalar_seen, source_finished;
  logic hold_request, hold_data, hold_last_ack, hold_source_quiet, inject_response_error;
  logic held_request, held_data, held_aux, held_done;
  logic [68:0] saved_request;
  logic [72:0] saved_data;
  logic [131:0] saved_aux;
  logic [131:0] prepared_upstream_packet;
  logic [105:0] saved_done;
  integer cycles, test_case, cfg_accepts, aux_fires, offered_aux_samples;
  integer requests, data_words, responses, scalar_responses, data_beat, response_delay;

  tri_oracle_post_feature_store_v1 dut (
      .clk, .rst_n, .abort_valid, .producer_idle, .next_context_owned,
      .cfg_valid, .cfg_ready, .cfg_normalization_role, .cfg_tag, .cfg_layer, .cfg_epoch,
      .cfg_original_root, .cfg_input_rank, .cfg_kept_rank,
      .cfg_feature_base, .cfg_feature_bytes, .cfg_code_base, .cfg_code_bytes,
      .cfg_immutable_input_base, .cfg_immutable_input_bytes,
      .aux_valid, .aux_ready, .aux_last, .aux_error, .aux_tag, .aux_layer, .aux_epoch,
      .aux_original_root, .aux_input_rank, .aux_kept_rank, .aux_index, .aux_count, .aux_exponent,
      .aux_outlier_mask, .aux_normalized_negative, .aux_outlier_negative,
      .scalar_req_valid, .scalar_req_ready, .scalar_req_address, .scalar_req_length,
      .scalar_data_valid, .scalar_data_ready, .scalar_data_last, .scalar_data, .scalar_strobe,
      .scalar_rsp_valid, .scalar_rsp_ready, .scalar_rsp_error,
      .done_valid, .done_ready, .done_error, .done_tag, .done_layer, .done_epoch,
      .done_original_root, .done_input_rank, .done_kept_rank, .done_exponent,
      .accepted_strips, .acknowledged_lines, .epoch_fault, .active, .port_idle, .idle
  );

  tri_oracle_external_write_mux write_mux (
      .clk, .rst_n,
      .scalar_req_valid, .scalar_req_ready, .scalar_req_address, .scalar_req_length,
      .scalar_data_valid, .scalar_data_ready, .scalar_data_last, .scalar_data, .scalar_strobe,
      .scalar_rsp_valid(mux_scalar_rsp_valid), .scalar_rsp_ready, .scalar_rsp_error(mux_scalar_rsp_error),
      .vector_req_valid(1'b0), .vector_req_ready(), .vector_req_address(64'd0), .vector_req_data(512'd0),
      .vector_rsp_valid(), .vector_rsp_ready(1'b0), .vector_rsp_error(),
      .mem_req_valid, .mem_req_ready, .mem_req_address, .mem_req_length,
      .mem_data_valid, .mem_data_ready, .mem_data_last, .mem_data, .mem_strobe,
      .mem_rsp_valid, .mem_rsp_ready, .mem_rsp_error
  );

  // Known responses traverse the real mux. The explicit rogue peer is used
  // only for unassociated-response tests, without forcing internal state.
  assign scalar_rsp_valid = rogue_rsp_valid || mux_scalar_rsp_valid;
  assign scalar_rsp_error = !rogue_rsp_valid && mux_scalar_rsp_error;
  assign mem_req_ready = rst_n && !mem_owned && !mem_rsp_valid && !hold_request && cycles[2:0] != 2;
  assign mem_data_ready = rst_n && mem_owned && !all_data_seen && !hold_data && cycles[1:0] != 1;
  initial clk = 0;
  always #5 clk = ~clk;

  function automatic logic [7:0] mask_value(input integer strip);
    return 8'((strip * 29 + 90) ^ (strip >> 3));
  endfunction
  function automatic logic [7:0] full_sign_value(input integer strip);
    return 8'((strip * 53 + 167) ^ (strip << 1));
  endfunction
  function automatic logic [7:0] input_outlier_sign_value(input integer strip);
    return mask_value(strip) & 8'(150 ^ (strip * 7));
  endfunction
  function automatic logic [7:0] expected_byte(input integer byte_number);
    // Independent byte indexing proves both cross-512 boundaries and the
    // three distinct field roles; no candidate line buffer is inspected.
    integer strip;
    strip = byte_number / 3;
    case (byte_number % 3)
      0: return mask_value(strip);
      1: return full_sign_value(strip);
      default: return input_outlier_sign_value(strip);
    endcase
  endfunction
  function automatic logic [131:0] aux_packet();
    return {aux_tag, aux_layer, aux_epoch, aux_original_root, aux_input_rank, aux_kept_rank,
      aux_index, aux_count, aux_last, aux_error, aux_exponent,
      aux_outlier_mask, aux_normalized_negative, aux_outlier_negative};
  endfunction
  function automatic logic [105:0] done_packet();
    return {done_error, done_tag, done_layer, done_epoch, done_original_root,
      done_input_rank, done_kept_rank, done_exponent, accepted_strips, acknowledged_lines};
  endfunction

  // One genuine external burst at a time; eight accepted data beats precede
  // its delayed registered ACK. No output fixture or large memory is used.
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      cycles <= 0; cfg_accepts <= 0; aux_fires <= 0; offered_aux_samples <= 0;
      requests <= 0; data_words <= 0; responses <= 0; scalar_responses <= 0;
      data_beat <= 0; response_delay <= 0; mem_owned <= 0; all_data_seen <= 0;
      mem_rsp_valid <= 0; mem_rsp_error <= 0; first_scalar_seen <= 0;
    end else begin
      cycles <= cycles + 1;
      if (cycles > 20000) $fatal(1, "POST_FEATURE_STORE_WATCHDOG case=%0d", test_case);
      if (cfg_valid && cfg_ready) cfg_accepts <= cfg_accepts + 1;
      if (aux_valid) offered_aux_samples <= offered_aux_samples + 1;
      if (aux_valid && aux_ready) aux_fires <= aux_fires + 1;
      if (scalar_req_valid) first_scalar_seen <= 1;
      if (scalar_rsp_valid && scalar_rsp_ready) begin
        if (rogue_rsp_valid) $fatal(1, "POST_FEATURE_STORE_ACCEPTED_UNASSOCIATED_RESPONSE");
        scalar_responses <= scalar_responses + 1;
      end
      if (mem_req_valid && mem_req_ready) begin
        if (mem_owned || mem_req_length != 8 || requests >= 12 ||
            mem_req_address !== cfg_feature_base + 64'(cfg_kept_rank)*64'd768 + 64'(requests)*64'd64)
          $fatal(1, "POST_FEATURE_STORE_BAD_REAL_SCALAR_REQUEST case=%0d line=%0d", test_case, requests);
        requests <= requests + 1; data_beat <= 0; mem_owned <= 1; all_data_seen <= 0;
      end
      if (mem_data_valid && mem_data_ready) begin
        if (!mem_owned || all_data_seen || mem_strobe != 8'hff || mem_data_last != (data_beat == 7))
          $fatal(1, "POST_FEATURE_STORE_BAD_DATA_CONTROL case=%0d", test_case);
        for (integer lane = 0; lane < 8; lane++)
          if (mem_data[lane*8+:8] !== expected_byte((requests-1)*64 + data_beat*8 + lane))
            $fatal(1, "POST_FEATURE_STORE_PACKING_MISMATCH line=%0d beat=%0d byte=%0d", requests-1, data_beat, lane);
        data_words <= data_words + 1;
        if (data_beat == 7) begin all_data_seen <= 1; response_delay <= 0; end
        else data_beat <= data_beat + 1;
      end
      if (mem_owned && all_data_seen && !mem_rsp_valid) begin
        if (response_delay >= 2 && !(hold_last_ack && requests == 12)) begin
          mem_rsp_valid <= 1; mem_rsp_error <= inject_response_error;
        end else response_delay <= response_delay + 1;
      end
      if (mem_rsp_valid && mem_rsp_ready) begin
        mem_rsp_valid <= 0; mem_owned <= 0; all_data_seen <= 0; responses <= responses + 1;
      end
    end
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      held_request <= 0; held_data <= 0; held_aux <= 0; held_done <= 0;
      saved_request <= 0; saved_data <= 0; saved_aux <= 0; saved_done <= 0;
    end else begin
      if (held_request && (!scalar_req_valid || {scalar_req_address, scalar_req_length} !== saved_request))
        $fatal(1, "POST_FEATURE_STORE_RETRACTED_REQUEST case=%0d", test_case);
      if (held_data && (!scalar_data_valid || {scalar_data, scalar_strobe, scalar_data_last} !== saved_data))
        $fatal(1, "POST_FEATURE_STORE_RETRACTED_DATA case=%0d", test_case);
      if (held_aux && (!aux_valid || aux_packet() !== saved_aux))
        $fatal(1, "POST_FEATURE_STORE_SOURCE_RETRACTED_AUX case=%0d", test_case);
      if (held_done && (!done_valid || done_packet() !== saved_done))
        $fatal(1, "POST_FEATURE_STORE_REWROTE_DONE case=%0d", test_case);
      if (done_valid && !done_error &&
          (aux_fires != 256 || accepted_strips != 256 || requests != 12 || data_words != 96 ||
           responses != 12 || scalar_responses != 12 || acknowledged_lines != 12 ||
           !producer_idle || aux_valid || mem_owned || mem_rsp_valid || scalar_req_valid || scalar_data_valid))
        $fatal(1, "POST_FEATURE_STORE_EARLY_SUCCESS case=%0d", test_case);
      held_request <= scalar_req_valid && !scalar_req_ready;
      held_data <= scalar_data_valid && !scalar_data_ready;
      held_aux <= aux_valid && !aux_ready; held_done <= done_valid && !done_ready;
      saved_request <= {scalar_req_address, scalar_req_length};
      saved_data <= {scalar_data, scalar_strobe, scalar_data_last};
      saved_aux <= aux_packet(); saved_done <= done_packet();
    end
  end

  task automatic ticks(input integer count);
    repeat (count) @(negedge clk);
  endtask
  task automatic defaults();
    abort_valid = 0; producer_idle = 1; next_context_owned = 1;
    cfg_valid = 0; cfg_normalization_role = 1; cfg_tag = 32'hfa000002;
    cfg_layer = 3; cfg_epoch = 11; cfg_original_root = 19; cfg_input_rank = 2; cfg_kept_rank = 2;
    cfg_feature_base = 64'h30000000; cfg_feature_bytes = 64'd442368;
    cfg_code_base = 64'h20000000; cfg_code_bytes = 64'd1179648;
    cfg_immutable_input_base = 64'h10000000; cfg_immutable_input_bytes = 64'h00100000;
    aux_valid = 0; aux_last = 0; aux_error = 0; aux_tag = cfg_tag; aux_layer = cfg_layer;
    aux_epoch = cfg_epoch; aux_original_root = cfg_original_root; aux_input_rank = cfg_input_rank;
    aux_kept_rank = cfg_kept_rank; aux_index = 0; aux_count = 8;
    configured_exponent = -9'sd14; aux_exponent = configured_exponent;
    aux_outlier_mask = 0; aux_normalized_negative = 0; aux_outlier_negative = 0;
    done_ready = 0; rogue_rsp_valid = 0; hold_request = 0; hold_data = 0;
    hold_last_ack = 0; hold_source_quiet = 0; inject_response_error = 0; source_finished = 0;
  endtask
  task automatic start_case(input integer number);
    @(negedge clk); rst_n = 0; defaults(); test_case = number;
    ticks(3); rst_n = 1; ticks(2);
  endtask
  task automatic accept_context();
    integer limit;
    cfg_valid = 1; limit = 0;
    while (cfg_ready !== 1'b1 && limit < 30) begin ticks(1); limit++; end
    if (cfg_ready !== 1'b1) $fatal(1, "POST_FEATURE_STORE_NO_CFG_ACCEPTANCE");
    @(posedge clk); @(negedge clk); cfg_valid = 0;
  endtask
  task automatic prepare_aux(input integer strip, bad_kind);
    aux_tag = cfg_tag; aux_layer = cfg_layer; aux_epoch = cfg_epoch;
    aux_original_root = cfg_original_root; aux_input_rank = cfg_input_rank; aux_kept_rank = cfg_kept_rank;
    aux_index = 10'(strip); aux_count = 8; aux_last = strip == 255; aux_error = 0;
    aux_exponent = configured_exponent; aux_outlier_mask = mask_value(strip);
    aux_normalized_negative = full_sign_value(strip); aux_outlier_negative = input_outlier_sign_value(strip);
    if (strip == 3) begin
      case (bad_kind)
        1: aux_index = 4;
        2: aux_last = 1;
        3: aux_exponent = configured_exponent + 9'sd1;
        4: aux_count = 7;
        5: aux_error = 1;
        6: aux_tag = cfg_tag + 1;
        7: aux_layer = cfg_layer + 1;
        8: aux_original_root = cfg_original_root + 1;
        9: aux_input_rank = cfg_input_rank + 1;
        10: aux_kept_rank = cfg_kept_rank + 1;
        11: aux_epoch = cfg_epoch + 1;
        default: begin end
      endcase
    end
  endtask
  task automatic put_aux(input integer strip, bad_kind);
    integer limit;
    prepare_aux(strip, bad_kind);
    aux_valid = 1; limit = 0;
    // Every offered tuple remains unchanged through its actual handshake,
    // including the one already offered when the registered fault arrives.
    begin : await_aux_fire
      forever begin
        @(posedge clk);
        if (aux_ready === 1'b1) break;
        limit++;
        if (limit > 2000) $fatal(1, "POST_FEATURE_STORE_STUCK_HELD_AUX case=%0d", test_case);
      end
    end
    @(negedge clk); aux_valid = 0;
  endtask
  task automatic send_row(input integer bad_kind);
    producer_idle = 0;
    for (integer strip = 0; strip < 256; strip++) begin
      if (epoch_fault) break;
      put_aux(strip, bad_kind); ticks(strip % 3 == 1 ? 1 : 0);
    end
    ticks(1); source_finished = 1;
    if (!hold_source_quiet) producer_idle = 1;
  endtask
  task automatic expect_first_scalar_request();
    integer limit;
    limit = 0;
    while (!first_scalar_seen && limit < 160) begin ticks(1); limit++; end
    if (!first_scalar_seen) begin
      if (cfg_accepts != 1 || offered_aux_samples < 4)
        $fatal(1, "POST_FEATURE_STORE_BASELINE_NOT_ARMED");
      $fatal(1, "POST_FEATURE_STORE_EXPECTED_SCALAR_REQUEST cfg=%0d offered=%0d aux=%0d requests=%0d", cfg_accepts, offered_aux_samples, aux_fires, requests);
    end
  endtask
  task automatic wait_for_done(input logic expected_error);
    integer limit;
    limit = 0;
    while (done_valid !== 1'b1 && limit < 3000) begin ticks(1); limit++; end
    if (done_valid !== 1'b1 || done_error !== expected_error || done_tag !== cfg_tag ||
        done_layer !== cfg_layer || done_epoch !== cfg_epoch || done_original_root !== cfg_original_root ||
        done_input_rank !== cfg_input_rank || done_kept_rank !== cfg_kept_rank)
      $fatal(1, "POST_FEATURE_STORE_BAD_DONE case=%0d", test_case);
    ticks(4);
  endtask
  task automatic acknowledge_done(input logic expected_error);
    done_ready = 1; @(posedge clk); @(negedge clk); done_ready = 0; ticks(3);
    if (expected_error) begin
      if (!epoch_fault || cfg_ready || idle) $fatal(1, "POST_FEATURE_STORE_ERROR_REUSED_CONTEXT");
    end else if (done_valid || active || !idle || !port_idle)
      $fatal(1, "POST_FEATURE_STORE_SUCCESS_NOT_QUIET");
    $display("POST_FEATURE_STORE_CASE_PASS case=%0d aux=%0d ack=%0d", test_case, aux_fires, responses);
  endtask
  task automatic healthy_row(input logic delay_last_ack, delay_quiet);
    integer limit;
    hold_last_ack = delay_last_ack; hold_source_quiet = delay_quiet;
    accept_context();
    fork
      send_row(0);
      expect_first_scalar_request();
    join
    limit = 0;
    while (data_words != 96 && limit < 3000) begin ticks(1); limit++; end
    if (!source_finished || aux_fires != 256 || requests != 12 || data_words != 96)
      $fatal(1, "POST_FEATURE_STORE_INCOMPLETE_ROW_TRANSFER");
    if (delay_last_ack) begin
      ticks(4);
      if (responses != 11 || done_valid) $fatal(1, "POST_FEATURE_STORE_IGNORED_LAST_REAL_ACK");
      hold_last_ack = 0;
    end
    if (delay_quiet) begin
      limit = 0;
      while (responses != 12 && limit < 100) begin ticks(1); limit++; end
      ticks(4);
      if (responses != 12 || done_valid || producer_idle)
        $fatal(1, "POST_FEATURE_STORE_IGNORED_SOURCE_QUIET");
      producer_idle = 1;
    end
    wait_for_done(0);
    if (done_exponent !== configured_exponent || acknowledged_lines != 12 || accepted_strips != 256)
      $fatal(1, "POST_FEATURE_STORE_WRONG_SUCCESS_COUNTS");
  endtask

  initial begin
    rst_n = 0; defaults(); test_case = -1;
    start_case(0);
    healthy_row(1, 0);
    acknowledge_done(0);

    start_case(1);
    healthy_row(0, 1);
    acknowledge_done(0);

    // Full signed9 transport endpoints; no assertion that the actual C emits
    // these extrema, and no narrowing of this status field to signed8.
    start_case(2); configured_exponent = $signed(9'h100);
    healthy_row(0, 0); acknowledge_done(0);
    start_case(3); configured_exponent = 9'sd255;
    healthy_row(0, 0); acknowledge_done(0);
    start_case(4); configured_exponent = 9'sd150;
    cfg_feature_bytes = cfg_feature_bytes + 64; cfg_code_bytes = cfg_code_bytes + 64;
    healthy_row(0, 0); acknowledge_done(0);

    for (integer bad = 1; bad <= 11; bad++) begin
      start_case(10 + bad); accept_context(); send_row(bad); wait_for_done(1);
      if (requests != 0 || responses != 0) $fatal(1, "POST_FEATURE_STORE_WROTE_MALFORMED_PREFIX");
      acknowledge_done(1);
    end

    start_case(30); cfg_normalization_role = 0; accept_context(); wait_for_done(1);
    if (requests != 0) $fatal(1, "POST_FEATURE_STORE_WROTE_WRONG_ROLE");
    acknowledge_done(1);
    start_case(31); cfg_feature_base = cfg_code_base + 64; accept_context(); wait_for_done(1);
    if (requests != 0) $fatal(1, "POST_FEATURE_STORE_MISSED_WHOLE_FRAME_OVERLAP");
    acknowledge_done(1);
    start_case(32); cfg_feature_base = 64'hffffffffffffffc0; accept_context(); wait_for_done(1);
    if (requests != 0) $fatal(1, "POST_FEATURE_STORE_TRUNCATED_ADDRESS_CARRY");
    acknowledge_done(1);

    start_case(40); inject_response_error = 1; accept_context(); send_row(0); wait_for_done(1);
    if (requests != 1 || responses != 1 || scalar_responses != 1 || mem_owned)
      $fatal(1, "POST_FEATURE_STORE_DID_NOT_DRAIN_KNOWN_ERROR");
    acknowledge_done(1);

    start_case(41); hold_request = 1; accept_context();
    fork
      send_row(0);
      begin
        while (!first_scalar_seen) ticks(1);
        ticks(3); abort_valid = 1; ticks(3);
        if (!scalar_req_valid || requests != 0 || done_valid)
          $fatal(1, "POST_FEATURE_STORE_DROPPED_ABORTED_REQUEST");
        hold_request = 0;
      end
    join
    wait_for_done(1);
    if (requests != 1 || responses != 1 || mem_owned) $fatal(1, "POST_FEATURE_STORE_ABORT_DRAIN_COUNT");
    acknowledge_done(1);

    start_case(42); accept_context(); rogue_rsp_valid = 1;
    ticks(8);
    if (!epoch_fault || done_valid || scalar_rsp_ready || cfg_ready || port_idle || idle || !active)
      $fatal(1, "POST_FEATURE_STORE_UNKNOWN_RESPONSE_NOT_QUARANTINED");
    $display("POST_FEATURE_STORE_CASE_PASS case=42 quarantine=1");

    start_case(43); healthy_row(0, 0); abort_valid = 1; ticks(4);
    if (!done_valid || done_error || !epoch_fault || cfg_ready)
      $fatal(1, "POST_FEATURE_STORE_LATE_FAULT_CHANGED_SUCCESS");
    acknowledge_done(1);

    start_case(44); healthy_row(0, 0); rogue_rsp_valid = 1; ticks(4);
    if (!done_valid || done_error || !epoch_fault || scalar_rsp_ready || port_idle)
      $fatal(1, "POST_FEATURE_STORE_LATE_RESPONSE_CHANGED_STATUS");
    done_ready = 1; @(posedge clk); @(negedge clk); done_ready = 0; ticks(3);
    if (done_valid || cfg_ready || idle) $fatal(1, "POST_FEATURE_STORE_REUSED_QUARANTINE");
    $display("POST_FEATURE_STORE_CASE_PASS case=44 quarantine=1");

    start_case(45); hold_data = 1; accept_context();
    fork
      send_row(0);
      begin
        while (!scalar_data_valid) ticks(1);
        ticks(3); abort_valid = 1; ticks(3);
        if (!scalar_data_valid || data_words != 0 || done_valid)
          $fatal(1, "POST_FEATURE_STORE_DROPPED_ABORTED_DATA");
        hold_data = 0;
      end
    join
    wait_for_done(1);
    if (requests != 1 || responses != 1 || data_words != 8 || mem_owned)
      $fatal(1, "POST_FEATURE_STORE_ABORTED_DATA_DRAIN_COUNT");
    acknowledge_done(1);

    // Model only the producer contract: an existing C tuple can be hidden by
    // the row writer's owned vector until its ErrorDrain route opens. Prepare
    // that tuple BEFORE fault; after fault change only its exposure/handshake.
    start_case(46); hold_request = 1; accept_context(); producer_idle = 0;
    for (integer strip = 0; strip < 22; strip++) put_aux(strip, 0);
    prepare_aux(22, 0); prepared_upstream_packet = aux_packet();
    while (!first_scalar_seen) ticks(1);
    ticks(3); abort_valid = 1; ticks(3);
    if (aux_valid || aux_packet() !== prepared_upstream_packet || !scalar_req_valid || requests != 0)
      $fatal(1, "POST_FEATURE_STORE_HIDDEN_HELD_TUPLE_NOT_ARMED");
    aux_valid = 1; hold_request = 0;
    begin : drain_prepared_C_tuple
      integer limit;
      limit = 0;
      forever begin
        @(posedge clk);
        if (aux_ready === 1'b1) break;
        limit++;
        if (limit > 2000) $fatal(1, "POST_FEATURE_STORE_CANNOT_DRAIN_PREEXISTING_C_TUPLE");
      end
    end
    @(negedge clk); aux_valid = 0; producer_idle = 1;
    wait_for_done(1);
    if (requests != 1 || responses != 1 || data_words != 8 || aux_fires != 23)
      $fatal(1, "POST_FEATURE_STORE_PREEXISTING_TUPLE_DRAIN_COUNT");
    acknowledge_done(1);

    $display("POST_FEATURE_STORE_PASS scenarios=26 packing_bytes_per_row=768");
    $finish;
  end
endmodule
