`timescale 1ns / 1ps
// Test-first primitive: synthetic C-strip source and explicit ACK endpoints.
// This tests packing/ownership only, not real POST operands, prediction or TMU.
module tri_oracle_post_normalized_row_writer_tb;
  logic clk, rst_n, abort_valid, producer_idle;
  logic cfg_valid, cfg_ready;
  logic [1:0] cfg_normalization_role;
  logic [31:0] cfg_tag;
  logic [4:0] cfg_layer;
  logic [15:0] cfg_epoch;
  logic [9:0] cfg_original_root, cfg_input_rank, cfg_kept_rank;
  logic [63:0] cfg_code_base, cfg_immutable_input_base, cfg_immutable_input_bytes;
  logic next_context_owned;

  logic in_valid, in_ready, in_last, in_error;
  logic [31:0] in_tag;
  logic [9:0] in_index;
  logic [3:0] in_count;
  logic [63:0] in_activation;
  logic signed [8:0] in_exponent;
  logic [7:0] in_outlier_mask, in_normalized_negative, in_outlier_negative;

  logic aux_valid, aux_ready, aux_last, aux_error;
  logic [31:0] aux_tag;
  logic [4:0] aux_layer;
  logic [15:0] aux_epoch;
  logic [9:0] aux_original_root, aux_input_rank, aux_kept_rank, aux_index;
  logic [3:0] aux_count;
  logic signed [8:0] aux_exponent;
  logic [7:0] aux_outlier_mask, aux_normalized_negative, aux_outlier_negative;

  logic vector_req_valid, vector_req_ready, vector_rsp_valid, vector_rsp_ready, vector_rsp_error;
  logic [63:0] vector_req_address;
  logic [511:0] vector_req_data;
  logic next_req_valid, next_req_ready, next_req_write;
  logic [9:0] next_req_word;
  logic [63:0] next_req_data, next_rsp_data;
  logic next_rsp_valid, next_rsp_ready, next_rsp_error;

  logic done_valid, done_ready, done_error, epoch_fault, active, idle;
  logic [31:0] done_tag;
  logic [4:0] done_layer;
  logic [15:0] done_epoch;
  logic [9:0] done_original_root, done_input_rank, done_kept_rank;
  logic signed [8:0] done_exponent;
  logic [8:0] accepted_strips;
  logic [5:0] acknowledged_lines;
  logic descriptor_acknowledged;

  logic provider_owned, force_owner_lost, allow_vector, allow_descriptor;
  logic hold_last_vector_ack, hold_descriptor_ack, hold_aux;
  logic provider_vector_rsp_valid, rogue_vector_rsp_valid;
  logic vector_pending, descriptor_pending;
  logic [3:0] vector_stall, vector_delay, descriptor_delay;
  integer cycles, source_fires, aux_fires, vector_requests, vector_acks, descriptor_requests, descriptor_acks;
  logic vector_held, descriptor_held, aux_held, done_held;
  logic [63:0] held_vector_address, held_descriptor_data;
  logic [511:0] held_vector_data;
  logic [9:0] held_descriptor_word;
  logic held_done_error;
  typedef struct packed {
    logic [31:0] tag;
    logic [4:0] layer;
    logic [15:0] epoch;
    logic [9:0] original_root, input_rank, kept_rank, index;
    logic [3:0] count;
    logic last, error;
    logic signed [8:0] exponent;
    logic [7:0] mask, normalized_negative, outlier_negative;
  } feature_t;
  feature_t held_aux;

  tri_oracle_post_normalized_row_writer_v1 dut (.*);

  function automatic logic [63:0] activation_word(input integer word_index);
    // Distinct source words catch lost/repeated/reversed octets and lane order.
    return 64'h8172635445362718 ^ (64'(word_index) * 64'h0101010101010101);
  endfunction
  function automatic logic [511:0] expected_line(input integer line_index);
    logic [511:0] value;
    for (int word_index = 0; word_index < 8; word_index++)
      value[word_index*64+:64] = activation_word(line_index*8 + word_index);
    return value;
  endfunction
  function automatic feature_t feature_packet();
    return {aux_tag, aux_layer, aux_epoch, aux_original_root, aux_input_rank,
      aux_kept_rank, aux_index, aux_count, aux_last, aux_error, aux_exponent,
      aux_outlier_mask, aux_normalized_negative, aux_outlier_negative};
  endfunction

  assign next_context_owned = provider_owned && !force_owner_lost;
  assign aux_ready = rst_n && !hold_aux && cycles[2:0] != 3 && cycles[2:0] != 4;
  assign vector_req_ready = rst_n && allow_vector && !vector_pending && vector_stall >= 2;
  assign vector_rsp_valid = rogue_vector_rsp_valid || provider_vector_rsp_valid;
  assign vector_rsp_error = 0;
  assign next_req_ready = rst_n && allow_descriptor && !descriptor_pending;
  assign next_rsp_error = 0;
  assign next_rsp_data = 0;
  initial clk = 0;
  always #5 clk = ~clk;

  // Endpoint responses are registered and count only actual accepted work.
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      provider_owned <= 1;
      vector_pending <= 0;
      descriptor_pending <= 0;
      vector_stall <= 0;
      vector_delay <= 0;
      descriptor_delay <= 0;
      provider_vector_rsp_valid <= 0;
      next_rsp_valid <= 0;
      vector_requests <= 0;
      vector_acks <= 0;
      descriptor_requests <= 0;
      descriptor_acks <= 0;
    end else begin
      if (vector_req_valid && !vector_req_ready && !vector_pending && vector_stall < 2)
        vector_stall <= vector_stall + 1'b1;
      if (vector_req_valid && vector_req_ready) begin
        if (vector_pending || vector_requests >= 32 || source_fires < 8*(vector_requests+1) ||
            vector_req_address !== 64'h20001000 + 64'(vector_requests)*64 ||
            vector_req_data !== expected_line(vector_requests))
          $fatal(1, "POST_ROW_WRITER_WRONG_ACTUAL_VECTOR line=%0d", vector_requests);
        vector_requests <= vector_requests + 1;
        vector_pending <= 1;
        vector_stall <= 0;
        vector_delay <= 0;
      end
      if (vector_pending && !provider_vector_rsp_valid) begin
        if (vector_delay < 2) vector_delay <= vector_delay + 1'b1;
        else if (!(hold_last_vector_ack && vector_requests == 32)) provider_vector_rsp_valid <= 1;
      end
      if (provider_vector_rsp_valid && !rogue_vector_rsp_valid && vector_rsp_ready) begin
        provider_vector_rsp_valid <= 0;
        vector_pending <= 0;
        vector_acks <= vector_acks + 1;
      end
      if (next_req_valid && next_req_ready) begin
        if (descriptor_pending || vector_acks != 32 || !next_req_write || next_req_word !== 258 ||
            next_req_data !== {3'b010, 9'(-14), 10'd2, 10'd19, 32'hca000002})
          $fatal(1, "POST_ROW_WRITER_WRONG_OR_EARLY_DESCRIPTOR");
        descriptor_pending <= 1;
        descriptor_delay <= 0;
        descriptor_requests <= descriptor_requests + 1;
      end
      if (descriptor_pending && !next_rsp_valid) begin
        if (descriptor_delay < 2) descriptor_delay <= descriptor_delay + 1'b1;
        else if (!hold_descriptor_ack) next_rsp_valid <= 1;
      end
      if (next_rsp_valid && next_rsp_ready) begin
        next_rsp_valid <= 0;
        descriptor_pending <= 0;
        descriptor_acks <= descriptor_acks + 1;
      end
    end
  end

  // Mutations caught here: independent aux acceptance, aliasing full-product
  // sign to input-space sign, retracted offers, and done before physical ACKs.
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      source_fires <= 0;
      aux_fires <= 0;
      vector_held <= 0;
      descriptor_held <= 0;
      aux_held <= 0;
      done_held <= 0;
      held_vector_address <= 0;
      held_vector_data <= 0;
      held_descriptor_word <= 0;
      held_descriptor_data <= 0;
      held_aux <= '0;
      held_done_error <= 0;
    end else begin
      if ((in_valid && in_ready) !== (aux_valid && aux_ready))
        $fatal(1, "POST_ROW_WRITER_INDEPENDENT_AUX_FORK");
      if (in_valid && !aux_ready && in_ready) $fatal(1, "POST_ROW_WRITER_IGNORED_AUX_BACKPRESSURE");
      if (aux_valid && aux_ready) begin
        if (aux_tag !== in_tag || aux_index !== in_index || aux_count !== in_count ||
            aux_last !== in_last || aux_error !== in_error || aux_exponent !== in_exponent ||
            aux_layer !== cfg_layer || aux_epoch !== cfg_epoch || aux_original_root !== cfg_original_root ||
            aux_input_rank !== cfg_input_rank || aux_kept_rank !== cfg_kept_rank ||
            aux_outlier_mask !== in_outlier_mask || aux_normalized_negative !== in_normalized_negative ||
            aux_outlier_negative !== in_outlier_negative)
          $fatal(1, "POST_ROW_WRITER_LOST_PREDICTION_FEATURE_TUPLE");
        source_fires <= source_fires + 1;
        aux_fires <= aux_fires + 1;
      end
      if (vector_held && (!vector_req_valid || vector_req_address !== held_vector_address || vector_req_data !== held_vector_data))
        $fatal(1, "POST_ROW_WRITER_RETRACTED_VECTOR_OFFER");
      if (descriptor_held && (!next_req_valid || !next_req_write || next_req_word !== held_descriptor_word || next_req_data !== held_descriptor_data))
        $fatal(1, "POST_ROW_WRITER_RETRACTED_DESCRIPTOR_OFFER");
      if (aux_held && (!aux_valid || feature_packet() !== held_aux))
        $fatal(1, "POST_ROW_WRITER_RETRACTED_AUX_OFFER");
      if (done_held && (!done_valid || done_error !== held_done_error))
        $fatal(1, "POST_ROW_WRITER_REWROTE_HELD_COMPLETION");
      if (done_valid && !done_error && (source_fires != 256 || aux_fires != 256 || vector_acks != 32 || descriptor_acks != 1))
        $fatal(1, "POST_ROW_WRITER_SUCCESS_WITHOUT_ALL_ACTUAL_ACKS");
      vector_held <= vector_req_valid && !vector_req_ready;
      descriptor_held <= next_req_valid && !next_req_ready;
      aux_held <= aux_valid && !aux_ready;
      done_held <= done_valid && !done_ready;
      held_vector_address <= vector_req_address;
      held_vector_data <= vector_req_data;
      held_descriptor_word <= next_req_word;
      held_descriptor_data <= next_req_data;
      held_aux <= feature_packet();
      held_done_error <= done_error;
    end
  end

  task automatic ticks(input integer count);
    repeat (count) @(negedge clk);
  endtask
  task automatic defaults();
    abort_valid = 0;
    producer_idle = 1;
    cfg_valid = 0;
    cfg_normalization_role = 1;
    cfg_tag = 32'hca000002;
    cfg_layer = 3;
    cfg_epoch = 11;
    cfg_original_root = 19;
    cfg_input_rank = 2;
    cfg_kept_rank = 2;
    cfg_code_base = 64'h20000000;
    cfg_immutable_input_base = 64'h10000000;
    cfg_immutable_input_bytes = 64'h00100000;
    in_valid = 0;
    in_error = 0;
    in_tag = cfg_tag;
    in_index = 0;
    in_count = 8;
    in_last = 0;
    in_activation = 0;
    in_exponent = -9'sd14;
    in_outlier_mask = 0;
    in_normalized_negative = 0;
    in_outlier_negative = 0;
    force_owner_lost = 0;
    allow_vector = 1;
    allow_descriptor = 0;
    hold_last_vector_ack = 1;
    hold_descriptor_ack = 1;
    hold_aux = 0;
    rogue_vector_rsp_valid = 0;
    done_ready = 0;
  endtask
  task automatic reset_case();
    @(negedge clk);
    rst_n = 0;
    defaults();
    ticks(3);
    rst_n = 1;
    ticks(2);
  endtask
  task automatic accept_context();
    integer count;
    cfg_valid = 1;
    count = 0;
    while (cfg_ready !== 1'b1 && count < 20) begin ticks(1); count++; end
    if (cfg_ready !== 1'b1) $fatal(1, "POST_ROW_WRITER_CONTEXT_NOT_ACCEPTED");
    @(posedge clk);
    @(negedge clk);
    cfg_valid = 0;
    producer_idle = 0;
    $display("POST_ROW_WRITER_CONTEXT_ACCEPTED owned=%b", next_context_owned);
  endtask
  task automatic drive_words(input integer count);
    bit accepted;
    for (int word_index = 0; word_index < count; word_index++) begin
      in_valid = 1;
      in_index = 10'(word_index);
      in_activation = activation_word(word_index);
      in_last = word_index == 255;
      in_outlier_mask = (8'h01 << (word_index%8)) ^ 8'h55;
      in_normalized_negative = 8'ha6 ^ 8'(word_index);
      in_outlier_negative = in_outlier_mask & 8'h3c;
      accepted = 0;
      while (!accepted) begin @(posedge clk); if (in_ready) accepted = 1; end
      @(negedge clk);
      in_valid = 0;
    end
    producer_idle = 1;
  endtask
  task automatic wait_first_line();
    ticks(120);
    if (vector_requests == 0 && !vector_req_valid)
      $fatal(1, "POST_ROW_WRITER_EXPECTED_VECTOR_REQUEST strips=%0d aux=%0d", source_fires, aux_fires);
  endtask

  task automatic healthy_row();
    integer count;
    reset_case();
    accept_context();
    fork
      drive_words(256);
      wait_first_line();
    join
    count = 0;
    while (vector_requests != 32 && count < 120) begin ticks(1); count++; end
    if (vector_requests != 32 || source_fires != 256 || aux_fires != 256)
      $fatal(1, "POST_ROW_WRITER_INCOMPLETE_ROW");
    repeat (5) begin
      if (vector_acks != 31 || next_req_valid || done_valid)
        $fatal(1, "POST_ROW_WRITER_EARLY_DESCRIPTOR_BEFORE_LAST_VECTOR_ACK");
      ticks(1);
    end
    hold_last_vector_ack = 0;
    count = 0;
    while (next_req_valid !== 1'b1 && count < 80) begin ticks(1); count++; end
    if (next_req_valid !== 1'b1) $fatal(1, "POST_ROW_WRITER_MISSING_DESCRIPTOR");
    ticks(4);
    allow_descriptor = 1;
    count = 0;
    while (descriptor_requests != 1 && count < 40) begin ticks(1); count++; end
    if (descriptor_requests != 1) $fatal(1, "POST_ROW_WRITER_DESCRIPTOR_NOT_ACCEPTED");
    repeat (5) begin
      if (done_valid) $fatal(1, "POST_ROW_WRITER_EARLY_DONE_BEFORE_DESCRIPTOR_ACK");
      ticks(1);
    end
    hold_descriptor_ack = 0;
    count = 0;
    while (done_valid !== 1'b1 && count < 80) begin ticks(1); count++; end
    if (done_valid !== 1'b1 || done_error || done_tag !== cfg_tag || done_layer !== 3 || done_epoch !== 11 ||
        done_original_root !== 19 || done_input_rank !== 2 || done_kept_rank !== 2 || done_exponent !== -9'sd14 ||
        accepted_strips !== 256 || acknowledged_lines !== 32 || !descriptor_acknowledged || !next_context_owned)
      $fatal(1, "POST_ROW_WRITER_WRONG_HELD_ROW_COMPLETION");
    ticks(4);
    done_ready = 1;
    @(posedge clk);
    @(negedge clk);
    done_ready = 0;
    ticks(2);
    if (!idle || epoch_fault || !next_context_owned)
      $fatal(1, "POST_ROW_WRITER_WRONG_ROW_RETIREMENT");
    $display("POST_ROW_WRITER_PASS strips=256 aux=256 lines=32 descriptorACK=1");
  endtask

  task automatic unknown_response();
    reset_case();
    accept_context();
    rogue_vector_rsp_valid = 1;
    repeat (10) begin
      @(posedge clk); #1;
      if (done_valid || vector_rsp_ready || next_req_valid || cfg_ready || !active || !epoch_fault || idle)
        $fatal(1, "POST_ROW_WRITER_UNKNOWN_RESPONSE_NOT_QUARANTINED");
    end
    $display("POST_ROW_WRITER_UNKNOWN_RESPONSE_PASS");
  endtask

  task automatic fault_while_line_offered(input logic lose_owner);
    integer count;
    reset_case();
    accept_context();
    allow_vector = 0;
    fork
      drive_words(8);
      wait_first_line();
    join
    if (!vector_req_valid || source_fires != 8 || aux_fires != 8 || vector_requests != 0)
      $fatal(1, "POST_ROW_WRITER_HELD_LINE_FAULT_NOT_ARMED");
    producer_idle = 0;
    if (lose_owner) force_owner_lost = 1;
    else abort_valid = 1;
    ticks(4);
    if (!vector_req_valid || done_valid) $fatal(1, "POST_ROW_WRITER_FAULT_DROPPED_OWNED_OFFER");
    allow_vector = 1;
    count = 0;
    while (vector_acks != 1 && count < 80) begin ticks(1); count++; end
    if (vector_acks != 1) $fatal(1, "POST_ROW_WRITER_FAULT_DID_NOT_DRAIN_REAL_VECTOR_ACK");
    repeat (3) begin
      if (done_valid || next_req_valid) $fatal(1, "POST_ROW_WRITER_FAULT_RETIRED_BEFORE_SOURCE_QUIET");
      ticks(1);
    end
    producer_idle = 1;
    repeat (10) begin
      @(posedge clk); #1;
      if (next_req_valid || (done_valid && !done_error) || !epoch_fault || cfg_ready || idle)
        $fatal(1, "POST_ROW_WRITER_FAULT_FABRICATED_SUCCESS_OR_RELEASE");
    end
    $display("POST_ROW_WRITER_HELD_LINE_FAULT_PASS lost_owner=%b", lose_owner);
  endtask

  initial begin
    rst_n = 0;
    defaults();
    if ($test$plusargs("UNKNOWN_RESPONSE")) unknown_response();
    else if ($test$plusargs("ABORT_HELD_LINE")) fault_while_line_offered(0);
    else if ($test$plusargs("LOST_OWNER_HELD_LINE")) fault_while_line_offered(1);
    else healthy_row();
    $finish;
  end
  initial cycles = 0;
  always @(posedge clk) begin
    cycles <= cycles + 1;
    if (cycles > 10000) $fatal(1, "POST_ROW_WRITER_TESTBENCH_WATCHDOG");
  end
endmodule
