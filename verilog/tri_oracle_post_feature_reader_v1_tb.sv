`timescale 1ns / 1ps
// Prospective synthetic archive-reader testbench. No C, model, trained data,
// predictor, SRAM or compute fabric. The actual reader must remain unimplemented
// until Root runs the first missing-read behavioral RED with a reviewed stub.
module tri_oracle_post_feature_reader_tb;
  logic clk, rst_n, abort_valid, next_context_owned;
  logic cfg_valid, cfg_ready, cfg_archive_committed;
  logic [1:0] cfg_normalization_role;
  logic [31:0] cfg_tag;
  logic [4:0] cfg_layer;
  logic [15:0] cfg_epoch;
  logic [9:0] cfg_original_root, cfg_input_rank, cfg_kept_rank;
  logic signed [8:0] cfg_exponent;
  logic [63:0] cfg_feature_base, cfg_feature_bytes;
  logic req_valid, req_ready;
  logic [63:0] req_address;
  logic [4:0] req_length;
  logic rsp_valid, rsp_ready, rsp_last, rsp_error;
  logic [63:0] rsp_data;
  logic out_valid, out_ready, out_last, out_error;
  logic [31:0] out_tag;
  logic [4:0] out_layer;
  logic [15:0] out_epoch;
  logic [9:0] out_original_root, out_input_rank, out_kept_rank, out_index;
  logic [3:0] out_count;
  logic signed [8:0] out_exponent;
  logic [7:0] out_outlier_mask, out_normalized_negative, out_outlier_negative;
  logic done_valid, done_ready, done_error;
  logic [31:0] done_tag;
  logic [4:0] done_layer;
  logic [15:0] done_epoch;
  logic [9:0] done_original_root, done_input_rank, done_kept_rank;
  logic signed [8:0] done_exponent;
  logic [8:0] accepted_strips;
  logic [3:0] completed_lines;
  logic [6:0] received_beats;
  logic epoch_fault, active, port_idle, idle;

  // The provider represents an external read endpoint only. It creates bytes
  // from an independently indexed synthetic archive, never from DUT output.
  logic peer_owned, peer_valid, peer_last, peer_error;
  logic [63:0] peer_data, peer_address;
  logic rogue_valid, hold_request, hold_response, hold_output;
  logic inject_error, inject_early_last, inject_late_last;
  integer peer_beat, peer_delay, cycles, test_case, selected_case;
  integer cfg_accepts, requests, response_beats, output_fires;
  logic [63:0] expected_row_address;
  logic [31:0] expected_tag;
  logic [4:0] expected_layer;
  logic [15:0] expected_epoch;
  logic [9:0] expected_root, expected_input_rank, expected_kept_rank;
  logic signed [8:0] expected_exponent;
  logic request_held, output_held, done_held;

  typedef struct packed {
    logic [63:0] address;
    logic [4:0] length;
  } request_packet_t;
  typedef struct packed {
    logic error, last;
    logic [31:0] tag;
    logic [4:0] layer;
    logic [15:0] epoch;
    logic [9:0] original_root, input_rank, kept_rank, index;
    logic [3:0] count;
    logic signed [8:0] exponent;
    logic [7:0] outlier_mask, normalized_negative, outlier_negative;
  } output_packet_t;
  typedef struct packed {
    logic error;
    logic [31:0] tag;
    logic [4:0] layer;
    logic [15:0] epoch;
    logic [9:0] original_root, input_rank, kept_rank;
    logic signed [8:0] exponent;
  } done_packet_t;
  request_packet_t saved_request;
  output_packet_t saved_output;
  done_packet_t saved_done;

  tri_oracle_post_feature_reader_v1 dut (
    .clk, .rst_n, .abort_valid, .next_context_owned,
    .cfg_valid, .cfg_ready, .cfg_archive_committed, .cfg_normalization_role,
    .cfg_tag, .cfg_layer, .cfg_epoch, .cfg_original_root, .cfg_input_rank, .cfg_kept_rank,
    .cfg_exponent, .cfg_feature_base, .cfg_feature_bytes,
    .req_valid, .req_ready, .req_address, .req_length,
    .rsp_valid, .rsp_ready, .rsp_last, .rsp_error, .rsp_data,
    .out_valid, .out_ready, .out_last, .out_error, .out_tag, .out_layer, .out_epoch,
    .out_original_root, .out_input_rank, .out_kept_rank, .out_index, .out_count,
    .out_exponent, .out_outlier_mask, .out_normalized_negative, .out_outlier_negative,
    .done_valid, .done_ready, .done_error, .done_tag, .done_layer, .done_epoch,
    .done_original_root, .done_input_rank, .done_kept_rank, .done_exponent,
    .accepted_strips, .completed_lines, .received_beats, .epoch_fault, .active, .port_idle, .idle
  );

  assign req_ready = rst_n && !peer_owned && !peer_valid && !hold_request && cycles % 5 != 1;
  assign rsp_valid = rogue_valid || peer_valid;
  assign rsp_last = rogue_valid ? 1'b1 : peer_last;
  assign rsp_error = !rogue_valid && peer_error;
  assign rsp_data = rogue_valid ? 64'hbad0_bad0_bad0_bad0 : peer_data;
  assign out_ready = rst_n && !hold_output && cycles % 4 != 1;
  initial clk = 0;
  always #5 clk = ~clk;

  function automatic logic [7:0] mask_value(input integer strip);
    return 8'((strip * 29 + 90) ^ (strip >> 3));
  endfunction
  function automatic logic [7:0] full_sign_value(input integer strip);
    return 8'((strip * 53 + 167) ^ (strip << 1));
  endfunction
  function automatic logic [7:0] input_sign_value(input integer strip);
    return mask_value(strip) & 8'(150 ^ (strip * 7));
  endfunction
  function automatic logic [7:0] archive_byte(input integer offset);
    integer strip;
    strip = offset / 3;
    case (offset % 3)
      0: return mask_value(strip);
      1: return full_sign_value(strip);
      default: return input_sign_value(strip);
    endcase
  endfunction
  function automatic logic [63:0] archive_word(input integer offset);
    logic [63:0] value;
    value = 0;
    for (integer lane = 0; lane < 8; lane++)
      if (offset + lane < 768) value[lane*8+:8] = archive_byte(offset + lane);
    return value;
  endfunction
  function automatic output_packet_t output_packet();
    return {out_error, out_last, out_tag, out_layer, out_epoch, out_original_root,
      out_input_rank, out_kept_rank, out_index, out_count, out_exponent,
      out_outlier_mask, out_normalized_negative, out_outlier_negative};
  endfunction
  function automatic done_packet_t done_packet();
    return {done_error, done_tag, done_layer, done_epoch, done_original_root,
      done_input_rank, done_kept_rank, done_exponent};
  endfunction

  always_ff @(posedge clk or negedge rst_n) begin : external_read_provider
    if (!rst_n) begin
      peer_owned <= 0; peer_valid <= 0; peer_last <= 0; peer_error <= 0;
      peer_data <= 0; peer_address <= 0; peer_beat <= 0; peer_delay <= 0;
    end else begin
      if (req_valid && req_ready) begin
        if (peer_owned || peer_valid) $fatal(1, "POST_FEATURE_READER_MULTIPLE_OWNED_READS");
        peer_owned <= 1; peer_address <= req_address; peer_beat <= 0; peer_delay <= 0;
      end
      // Only a request accepted on a PREVIOUS edge can produce a response.
      if (peer_owned && !peer_valid && !hold_response) begin
        if (peer_delay >= 1) begin
          peer_valid <= 1;
          peer_last <= inject_early_last ? peer_beat == 2 :
            (inject_late_last ? peer_beat == 8 : peer_beat == 7);
          peer_error <= inject_error && peer_beat == 2;
          peer_data <= archive_word(int'(peer_address - expected_row_address) + peer_beat*8);
        end else peer_delay <= peer_delay + 1;
      end
      if (peer_valid && !rogue_valid && rsp_ready) begin
        peer_valid <= 0; peer_delay <= 0;
        if (peer_last) peer_owned <= 0;
        else peer_beat <= peer_beat + 1;
      end
    end
  end

  always_ff @(posedge clk or negedge rst_n) begin : acceptance_and_hold_checks
    if (!rst_n) begin
      cycles <= 0; cfg_accepts <= 0; requests <= 0; response_beats <= 0; output_fires <= 0;
      request_held <= 0; output_held <= 0; done_held <= 0;
      saved_request <= '0; saved_output <= '0; saved_done <= '0;
    end else begin
      cycles <= cycles + 1;
      if (cycles > 12000) $fatal(1, "POST_FEATURE_READER_WATCHDOG case=%0d", test_case);
      if (cfg_valid && cfg_ready) cfg_accepts <= cfg_accepts + 1;
      if (request_held && (!req_valid || {req_address, req_length} !== saved_request))
        $fatal(1, "POST_FEATURE_READER_RETRACTED_REQUEST case=%0d", test_case);
      if (output_held && (!out_valid || output_packet() !== saved_output))
        $fatal(1, "POST_FEATURE_READER_RETRACTED_OUTPUT case=%0d", test_case);
      if (done_held && (!done_valid || done_packet() !== saved_done))
        $fatal(1, "POST_FEATURE_READER_REWROTE_DONE case=%0d", test_case);
      if (req_valid && req_ready) begin
        if (req_length != 8 || requests >= 12 ||
            req_address !== expected_row_address + 64'(requests)*64'd64)
          $fatal(1, "POST_FEATURE_READER_WRONG_READ case=%0d request=%0d address=%016h length=%0d",
            test_case, requests, req_address, req_length);
        requests <= requests + 1;
      end
      if (peer_valid && !rogue_valid && rsp_ready) response_beats <= response_beats + 1;
      if (out_valid && out_ready) begin
        if (output_fires >= 256 || out_error || out_tag !== expected_tag ||
            out_layer !== expected_layer || out_epoch !== expected_epoch ||
            out_original_root !== expected_root || out_input_rank !== expected_input_rank ||
            out_kept_rank !== expected_kept_rank || out_index !== 10'(output_fires) ||
            out_count != 8 || out_last != (output_fires == 255) ||
            out_exponent !== expected_exponent || out_outlier_mask !== mask_value(output_fires) ||
            out_normalized_negative !== full_sign_value(output_fires) ||
            out_outlier_negative !== input_sign_value(output_fires))
          $fatal(1, "POST_FEATURE_READER_WRONG_STRIP case=%0d strip=%0d index=%0d", test_case, output_fires, out_index);
        output_fires <= output_fires + 1;
      end
      // Quietness is required when success FIRST becomes an offer. A genuine
      // earlier held success must remain immutable after a late unknown beat.
      if (done_valid && !done_error && !done_held &&
          (output_fires != 256 || accepted_strips != 256 || requests != 12 ||
           response_beats != 96 || received_beats != 96 || completed_lines != 12 ||
           peer_owned || peer_valid || req_valid || rsp_valid || out_valid))
        $fatal(1, "POST_FEATURE_READER_EARLY_SUCCESS case=%0d", test_case);
      if (done_valid && (done_tag !== expected_tag || done_layer !== expected_layer ||
          done_epoch !== expected_epoch || done_original_root !== expected_root ||
          done_input_rank !== expected_input_rank || done_kept_rank !== expected_kept_rank ||
          done_exponent !== expected_exponent))
        $fatal(1, "POST_FEATURE_READER_WRONG_DONE_IDENTITY case=%0d", test_case);
      request_held <= req_valid && !req_ready;
      output_held <= out_valid && !out_ready; done_held <= done_valid && !done_ready;
      saved_request <= {req_address, req_length}; saved_output <= output_packet(); saved_done <= done_packet();
    end
  end

  task automatic ticks(input integer count);
    repeat (count) @(negedge clk);
  endtask
  task automatic defaults();
    abort_valid = 0; next_context_owned = 1; cfg_valid = 0; cfg_archive_committed = 1;
    cfg_normalization_role = 1; cfg_tag = 32'h504f0002; cfg_layer = 3; cfg_epoch = 11;
    cfg_original_root = 19; cfg_input_rank = 2; cfg_kept_rank = 2; cfg_exponent = -9'sd14;
    cfg_feature_base = 64'h40000000; cfg_feature_bytes = 64'd442368;
    done_ready = 0; rogue_valid = 0; hold_request = 0; hold_response = 0; hold_output = 0;
    inject_error = 0; inject_early_last = 0; inject_late_last = 0;
  endtask
  task automatic remember_expected();
    expected_row_address = cfg_feature_base + 64'(cfg_kept_rank)*64'd768;
    expected_tag = cfg_tag; expected_layer = cfg_layer; expected_epoch = cfg_epoch;
    expected_root = cfg_original_root; expected_input_rank = cfg_input_rank;
    expected_kept_rank = cfg_kept_rank; expected_exponent = cfg_exponent;
  endtask
  task automatic start_case(input integer number);
    @(negedge clk); rst_n = 0; defaults(); test_case = number;
    ticks(3); rst_n = 1; ticks(2);
  endtask
  task automatic accept_context();
    integer limit;
    remember_expected(); cfg_valid = 1; limit = 0;
    forever begin
      @(posedge clk);
      if (cfg_ready === 1'b1) break;
      limit++;
      if (limit > 30) $fatal(1, "POST_FEATURE_READER_NO_CFG_ACCEPTANCE case=%0d", test_case);
    end
    @(negedge clk); cfg_valid = 0;
  endtask
  task automatic expect_first_request();
    integer limit;
    limit = 0;
    while (!req_valid && requests == 0 && limit < 100) begin ticks(1); limit++; end
    if (!req_valid && requests == 0) begin
      if (cfg_accepts != 1) $fatal(1, "POST_FEATURE_READER_RED_NOT_ARMED cfg=%0d", cfg_accepts);
      $fatal(1, "POST_FEATURE_READER_EXPECTED_READ_REQUEST case=%0d cfg=%0d requests=%0d strips=%0d",
        test_case, cfg_accepts, requests, output_fires);
    end
  endtask
  task automatic wait_done(input logic expected_error);
    integer limit;
    limit = 0;
    while (!done_valid && limit < 7000) begin ticks(1); limit++; end
    if (!done_valid || done_error !== expected_error || !active)
      $fatal(1, "POST_FEATURE_READER_WRONG_OR_MISSING_DONE case=%0d error=%b", test_case, done_error);
    ticks(4);
    done_ready = 1; @(posedge clk); @(negedge clk); done_ready = 0; ticks(2);
    if (expected_error) begin
      if (!epoch_fault || !active || idle || cfg_ready)
        $fatal(1, "POST_FEATURE_READER_FAULT_RELEASED_CONTEXT case=%0d", test_case);
    end else if (!idle || active || !port_idle || epoch_fault)
      $fatal(1, "POST_FEATURE_READER_SUCCESS_NOT_RETIRED case=%0d", test_case);
  endtask
  task automatic wait_output();
    integer limit;
    limit = 0;
    while (!out_valid && limit < 200) begin ticks(1); limit++; end
    if (!out_valid) $fatal(1, "POST_FEATURE_READER_NO_HELD_OUTPUT case=%0d", test_case);
  endtask
  task automatic require_quarantine();
    ticks(10);
    if (!epoch_fault || !active || idle || port_idle || cfg_ready || rsp_ready || done_valid)
      $fatal(1, "POST_FEATURE_READER_UNASSOCIATED_RESPONSE_ESCAPED case=%0d", test_case);
    rogue_valid = 0; ticks(4);
    if (!epoch_fault || !active || idle || cfg_ready || done_valid)
      $fatal(1, "POST_FEATURE_READER_QUARANTINE_NOT_STICKY case=%0d", test_case);
  endtask
  task automatic run_case(input integer number);
    integer limit;
    start_case(number);
    case (number)
      0, 1, 2, 3: begin
        // Breaks caught: no read; wrong byte/plane order/cross-line carry;
        // wrong signed exponent, rank offset, and inclusive 64-bit endpoint.
        if (number == 1) begin cfg_exponent = 9'sh100; cfg_kept_rank = 575; cfg_input_rank = 575; end
        if (number == 2) begin cfg_exponent = 9'sd255; cfg_kept_rank = 0; cfg_input_rank = 0; end
        if (number == 3) begin
          cfg_kept_rank = 0; cfg_input_rank = 0;
          cfg_feature_base = 64'hfffffffffffffd00; cfg_feature_bytes = 768;
        end
        accept_context(); expect_first_request();
        // Candidate must use only captured configuration after acceptance.
        cfg_tag = 0; cfg_layer = 0; cfg_epoch = 0; cfg_original_root = 0;
        cfg_kept_rank = 0; cfg_input_rank = 0; cfg_exponent = 0; cfg_feature_base = 0;
        wait_done(0);
      end
      10, 11, 12, 13, 14, 15, 16: begin
        // Every malformed admitted configuration faults with no archive read.
        case (number)
          10: cfg_normalization_role = 0;
          11: cfg_layer = 22;
          12: cfg_original_root = 576;
          13: cfg_input_rank = 1;
          14: cfg_feature_base = cfg_feature_base + 8;
          15: begin cfg_feature_base = 64'hffffffffffffffc0; cfg_feature_bytes = 768; end
          16: cfg_feature_bytes = 64'd768;
          default: begin end
        endcase
        accept_context(); wait_done(1);
        if (requests || response_beats || output_fires)
          $fatal(1, "POST_FEATURE_READER_INVALID_CONFIG_READ_MEMORY case=%0d", test_case);
      end
      20, 21: begin
        // Lack of committed archive/actual ownership must deny admission.
        if (number == 20) cfg_archive_committed = 0; else next_context_owned = 0;
        remember_expected(); cfg_valid = 1; ticks(8);
        if (cfg_accepts || cfg_ready || requests || out_valid || done_valid)
          $fatal(1, "POST_FEATURE_READER_UNAUTHORIZED_ADMISSION case=%0d", test_case);
        cfg_valid = 0;
      end
      30, 31, 32: begin
        inject_error = number == 30; inject_early_last = number == 31; inject_late_last = number == 32;
        accept_context(); expect_first_request(); wait_done(1);
        if (requests != 1 || output_fires != 0 || peer_owned || peer_valid ||
            response_beats != (number == 31 ? 3 : (number == 32 ? 9 : 8)))
          $fatal(1, "POST_FEATURE_READER_BAD_BURST_DID_NOT_DRAIN case=%0d", test_case);
      end
      40: begin
        // Abort may stop fresh work, never retract an exposed request.
        hold_request = 1; accept_context(); expect_first_request(); ticks(4);
        abort_valid = 1; ticks(4); hold_request = 0; wait_done(1);
        if (requests != 1 || response_beats != 8 || output_fires != 0)
          $fatal(1, "POST_FEATURE_READER_ABORT_REQUEST_NOT_DRAINED");
      end
      41, 42: begin
        // A previously exposed strip remains immutable and must drain once.
        hold_output = 1; accept_context(); expect_first_request(); wait_output(); ticks(3);
        if (number == 41) abort_valid = 1; else next_context_owned = 0;
        ticks(4); hold_output = 0; wait_done(1);
        if (requests != 1 || response_beats != 8 || output_fires != 1)
          $fatal(1, "POST_FEATURE_READER_HELD_STRIP_NOT_DRAINED case=%0d", test_case);
      end
      43: begin
        // Unknown response before request acceptance must not become associated
        // merely because that already-offered request subsequently accepts.
        hold_request = 1; accept_context(); expect_first_request(); ticks(2);
        rogue_valid = 1; ticks(3); hold_request = 0; ticks(5);
        if (requests != 1) $fatal(1, "POST_FEATURE_READER_OFFER_NOT_PRESERVED_UNDER_QUARANTINE");
        require_quarantine();
      end
      44: begin
        // A completed line does not confer ownership on a second response.
        hold_output = 1; accept_context(); expect_first_request(); wait_output();
        rogue_valid = 1; ticks(3); hold_output = 0; require_quarantine();
        if (output_fires != 1) $fatal(1, "POST_FEATURE_READER_QUARANTINE_RETRACTED_STRIP");
      end
      45: begin
        // An unexpected idle response fences cfg without a fake accepted job.
        rogue_valid = 1; remember_expected(); cfg_valid = 1; ticks(5);
        if (cfg_accepts || req_valid || out_valid || done_valid || rsp_ready || cfg_ready || !epoch_fault)
          $fatal(1, "POST_FEATURE_READER_IDLE_UNKNOWN_RESPONSE_ACCEPTED");
        rogue_valid = 0; cfg_valid = 0; ticks(3);
        if (!epoch_fault || cfg_ready || idle) $fatal(1, "POST_FEATURE_READER_IDLE_QUARANTINE_CLEARED");
      end
      46: begin
        // A genuinely earlier success offer remains success after a late fault.
        accept_context(); expect_first_request(); limit = 0;
        while (!done_valid && limit < 7000) begin ticks(1); limit++; end
        if (!done_valid || done_error) $fatal(1, "POST_FEATURE_READER_NO_EARLIER_SUCCESS");
        ticks(2); rogue_valid = 1; ticks(4);
        if (!done_valid || done_error || !epoch_fault || !active)
          $fatal(1, "POST_FEATURE_READER_LATE_FAULT_REWROTE_SUCCESS");
        done_ready = 1; @(posedge clk); @(negedge clk); done_ready = 0; rogue_valid = 0; ticks(3);
        if (!active || !epoch_fault || idle || cfg_ready || done_valid)
          $fatal(1, "POST_FEATURE_READER_LATE_FAULT_RELEASED_CONTEXT");
      end
      47: begin
        // Coupled reset, not a fabricated private clear, cancels an owned read.
        hold_response = 1; accept_context(); expect_first_request(); ticks(3);
        if (!peer_owned) $fatal(1, "POST_FEATURE_READER_RESET_TARGET_NOT_OWNED");
        rst_n = 0; ticks(3); defaults(); rst_n = 1; ticks(3);
        if (!idle || !port_idle || active || epoch_fault || req_valid || out_valid || done_valid || peer_owned)
          $fatal(1, "POST_FEATURE_READER_COUPLED_RESET_NOT_QUIET");
      end
      default: $fatal(1, "POST_FEATURE_READER_UNKNOWN_CASE=%0d", number);
    endcase
    $display("POST_FEATURE_READER_CASE_PASS case=%0d cfg=%0d requests=%0d responses=%0d strips=%0d", number, cfg_accepts, requests, response_beats, output_fires);
  endtask

  initial begin
    rst_n = 0; defaults(); test_case = -1; selected_case = 0;
    expected_row_address = 0; expected_tag = 0; expected_layer = 0; expected_epoch = 0;
    expected_root = 0; expected_input_rank = 0; expected_kept_rank = 0; expected_exponent = 0;
    if ($test$plusargs("FEATURE_READER_ALL")) begin
      for (integer number = 0; number <= 3; number++) run_case(number);
      for (integer number = 10; number <= 16; number++) run_case(number);
      run_case(20); run_case(21);
      for (integer number = 30; number <= 32; number++) run_case(number);
      for (integer number = 40; number <= 47; number++) run_case(number);
    end else begin
      if ($value$plusargs("FEATURE_READER_CASE=%d", selected_case)) begin end
      run_case(selected_case);
    end
    $display("POST_FEATURE_READER_TB_PASS synthetic_only=1");
    $finish;
  end
endmodule
