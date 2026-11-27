`timescale 1ns / 1ps
// One raw frame source, one unchanged compactor, and one external store lease.
// Public completion is retained separately from the physical memory owner.
module tri_oracle_raw32_frame_parent_v1 (
    input logic clk,
    input logic rst_n,
    input logic abort_valid,
    input logic cfg_valid,
    output logic cfg_ready,
    input logic cfg_new_image,
    input logic [11:0] cfg_minimum_matches,
    input logic [31:0] cfg_tag_base,
    input logic [4:0] cfg_layer,
    input logic [15:0] cfg_epoch,
    input logic [9:0] cfg_image_start,
    input logic [9:0] cfg_input_rows,
    input logic [63:0] cfg_raw_frame_base,
    input logic [63:0] cfg_raw_frame_bytes,
    input logic [63:0] cfg_metadata_base,
    input logic [63:0] cfg_metadata_bytes,
    input logic [63:0] cfg_gamma_base,
    input logic [63:0] cfg_gamma_bytes,
    input logic [63:0] cfg_compact_output_base,
    input logic signed [7:0] cfg_gamma_exponent,
    output logic read_req_valid,
    input logic read_req_ready,
    output logic [63:0] read_req_address,
    output logic [4:0] read_req_length,
    input logic read_rsp_valid,
    input logic read_rsp_last,
    input logic read_rsp_error,
    output logic read_rsp_ready,
    input logic [63:0] read_rsp_data,
    output logic store_acquire_valid,
    output logic store_release_valid,
    output logic store_req_valid,
    output logic store_req_write,
    output logic store_rsp_ready,
    input logic store_acquire_ready,
    input logic store_release_ready,
    input logic store_context_owned,
    input logic store_req_ready,
    input logic store_rsp_valid,
    input logic store_rsp_error,
    output logic [9:0] store_req_word,
    output logic [63:0] store_req_data,
    input logic [63:0] store_rsp_data,
    input logic next_req_valid,
    input logic next_req_write,
    input logic next_rsp_ready,
    input logic next_release_valid,
    output logic next_req_ready,
    output logic next_rsp_valid,
    output logic next_rsp_error,
    output logic next_release_ready,
    input logic [9:0] next_req_word,
    input logic [63:0] next_req_data,
    output logic [63:0] next_rsp_data,
    output logic vector_req_valid,
    output logic vector_rsp_ready,
    input logic vector_req_ready,
    input logic vector_rsp_valid,
    input logic vector_rsp_error,
    output logic [63:0] vector_req_address,
    output logic [511:0] vector_req_data,
    output logic done_valid,
    output logic done_error,
    output logic epoch_fault,
    output logic frame_protect,
    output logic metadata_needs_rebuild,
    output logic port_idle,
    output logic idle,
    input logic done_ready,
    input logic metadata_rebuilt,
    output logic [31:0] done_tag_base,
    output logic [4:0] done_layer,
    output logic [15:0] done_epoch,
    output logic [9:0] done_input_count,
    output logic [9:0] done_kept_count,
    output tri_oracle_merge_range_types::request_t fabric_merge_request,
    input tri_oracle_merge_range_types::response_t fabric_merge_response,
    output logic [2047:0] fabric_sign_data,
    output tri_oracle_token_size_types::request_t fabric_size_request,
    input tri_oracle_token_size_types::response_t fabric_size_response,
    input logic [9:0] fabric_size_out_origin,
    input tri_oracle_token_size_types::request_t next_size_request,
    output tri_oracle_token_size_types::response_t next_size_response,
    output logic [9:0] next_size_out_origin
);

  localparam int unsigned MAXIMUM_ROWS = 576;
  localparam logic [64:0] OUTPUT_LAST_OFFSET = 65'd1179647;
  typedef enum logic [1:0] {
    OwnerNone,
    OwnerCompactor,
    OwnerParentHeld,
    OwnerNext
  } owner_t;
  owner_t physical_owner;
  logic physical_acquired, frame_active, frame_started, completion_seen;
  logic epoch_fault_latched, store_response_pending;
  logic [31:0] saved_tag_base;
  logic [ 4:0] saved_layer;
  logic [15:0] saved_epoch;
  logic [ 9:0] saved_input_rows;

  logic [64:0] raw_last, metadata_last, gamma_last, output_last;
  logic [64:0] needed_raw_bytes, envelope_span;
  logic [63:0] envelope_base, envelope_last;
  logic [32:0] tag_last;
  logic [10:0] last_position;
  logic configuration_legal, admission_quiet, frame_offer, cfg_fire;
  logic children_cfg_valid, source_cfg_ready, child_cfg_ready;
  logic frame_port_granted, bridge_abort, fault_now;
  logic child_done_ready, child_done_valid, child_done_error, child_done_fire;
  logic child_epoch_invalid, child_frame_protect, child_abort_drained;
  logic capture_first, completion_join_bad, completion_drain_bad;
  logic source_retire_valid, source_retire_ready, source_error;
  logic source_producer_idle, source_port_idle, source_idle;
  logic [9:0] source_accepted_rows, source_completed_rows;
  logic [31:0] child_done_tag_base;
  logic [ 4:0] child_done_layer;
  logic [15:0] child_done_epoch;
  logic [9:0] child_done_input_count, child_done_kept_count;

  logic row_request_valid, row_request_ready;
  logic [9:0] row_request_original_root, row_request_input_rank;
  logic [31:0] row_request_tag;
  logic [ 4:0] row_request_layer;
  logic [15:0] row_request_epoch;
  logic normalized_valid, normalized_ready, normalized_last, normalized_error;
  logic [31:0] normalized_tag;
  logic [9:0] normalized_index;
  logic [3:0] normalized_count;
  logic [63:0] normalized_activation;
  logic signed [8:0] normalized_exponent;
  logic [7:0] normalized_outlier_mask, normalized_outlier_negative, normalized_negative;

  logic child_acquire_valid, child_acquire_ready;
  logic child_memory_req_valid, child_memory_req_ready, child_memory_req_write;
  logic [ 9:0] child_memory_req_word;
  logic [63:0] child_memory_req_data;
  logic child_memory_rsp_valid, child_memory_rsp_ready;
  tri_oracle_merge_range_types::request_t child_merge_request;
  tri_oracle_merge_range_types::response_t child_merge_response;
  logic [2047:0] child_sign_data;
  logic store_request_fire, store_response_fire, acquire_fire, release_fire;
  logic size_port_quiet, next_release_quiet, public_done_fire;

  always_comb begin
    raw_last = {1'b0, cfg_raw_frame_base} + {1'b0, cfg_raw_frame_bytes} - 65'd1;
    metadata_last = {1'b0, cfg_metadata_base} + {1'b0, cfg_metadata_bytes} - 65'd1;
    gamma_last = {1'b0, cfg_gamma_base} + {1'b0, cfg_gamma_bytes} - 65'd1;
    output_last = {1'b0, cfg_compact_output_base} + OUTPUT_LAST_OFFSET;
    needed_raw_bytes = (65'(cfg_image_start) + 65'(cfg_input_rows)) * 65'd8192;
    tag_last = {1'b0, cfg_tag_base} + 33'(MAXIMUM_ROWS - 1);
    last_position = {1'b0, cfg_image_start} + 11'(MAXIMUM_ROWS - 1);
    envelope_base = cfg_raw_frame_base;
    if (cfg_metadata_base < envelope_base) envelope_base = cfg_metadata_base;
    if (cfg_gamma_base < envelope_base) envelope_base = cfg_gamma_base;
    envelope_base[5:0] = 0;
    envelope_last = raw_last[63:0];
    if (metadata_last > raw_last) envelope_last = metadata_last[63:0];
    if (gamma_last > {1'b0, envelope_last}) envelope_last = gamma_last[63:0];
    envelope_last[5:0] = 6'b111111;
    // An exclusive end of 2^64 is legal; a span of 2^64 is not.
    envelope_span = {1'b0, envelope_last} + 65'd1 - {1'b0, envelope_base};
    configuration_legal = cfg_input_rows != 0 && cfg_input_rows <= MAXIMUM_ROWS &&
      (!cfg_new_image || cfg_input_rows == MAXIMUM_ROWS) && !last_position[10] && !tag_last[32] &&
      cfg_minimum_matches <= 2048 && cfg_raw_frame_base[5:0] == 0 &&
      cfg_raw_frame_bytes != 0 && cfg_raw_frame_bytes[5:0] == 0 &&
      {1'b0,cfg_raw_frame_bytes} >= needed_raw_bytes && !raw_last[64] &&
      cfg_metadata_base[3:0] == 0 && cfg_metadata_bytes[3:0] == 0 &&
      {1'b0,cfg_metadata_bytes} >= 65'(cfg_input_rows) * 65'd16 && !metadata_last[64] &&
      cfg_gamma_base[2:0] == 0 && cfg_gamma_bytes == 64'd6144 && !gamma_last[64] &&
      cfg_compact_output_base[5:0] == 0 && !output_last[64] &&
      envelope_span != 0 && !envelope_span[64] &&
      (envelope_last < cfg_compact_output_base || output_last < {1'b0,envelope_base});

    frame_offer = rst_n && cfg_valid && !frame_active && !done_valid &&
      !epoch_fault_latched && physical_owner == OwnerNone && !physical_acquired && !abort_valid;
    frame_port_granted = rst_n && (physical_owner == OwnerCompactor || frame_offer);
    admission_quiet = rst_n && !frame_active && !done_valid && !epoch_fault_latched &&
      physical_owner == OwnerNone && !physical_acquired && !store_context_owned &&
      !store_response_pending && !store_rsp_valid && !vector_rsp_valid && !read_rsp_valid &&
      !abort_valid && !source_error && source_cfg_ready && source_port_idle && !normalized_valid;
    // Invalid configurations produce a local error without starting either child.
    cfg_ready = admission_quiet && (!configuration_legal || child_cfg_ready);
    cfg_fire = cfg_valid && cfg_ready;
    children_cfg_valid = cfg_fire && configuration_legal;

    child_done_ready = rst_n && frame_started;
    child_done_fire = child_done_valid && child_done_ready;
    capture_first = child_done_fire && !completion_seen;
    completion_join_bad = child_done_tag_base != saved_tag_base ||
      child_done_layer != saved_layer || child_done_epoch != saved_epoch ||
      child_done_input_count > saved_input_rows || child_done_kept_count > child_done_input_count ||
      source_accepted_rows > saved_input_rows || source_completed_rows > source_accepted_rows ||
      child_done_input_count > source_accepted_rows ||
      (!child_done_error && (child_done_input_count != saved_input_rows ||
       source_accepted_rows != saved_input_rows || source_completed_rows != saved_input_rows ||
       !physical_acquired || !store_context_owned));
    completion_drain_bad = !source_producer_idle || !source_port_idle || !source_retire_ready ||
      normalized_valid || read_req_valid || read_rsp_valid || store_response_pending ||
      store_rsp_valid || child_memory_req_valid || vector_req_valid || vector_rsp_valid;
    source_retire_valid = capture_first && source_retire_ready;

    fault_now = (frame_active && abort_valid) || source_error || child_epoch_invalid ||
      (physical_acquired && !store_context_owned) ||
      (store_rsp_valid && (!store_response_pending || store_rsp_error)) ||
      (vector_rsp_valid && (!frame_started || completion_seen || vector_rsp_error)) ||
      (frame_active && fabric_size_response.error) ||
      (frame_active && fabric_merge_response.done_valid && fabric_merge_response.done_error) ||
      (completion_seen && frame_active && fabric_merge_response.map_valid) ||
      (physical_owner == OwnerNext && (next_size_request.frame_valid || next_size_request.map_valid));
    epoch_fault = rst_n && (epoch_fault_latched || fault_now);
    // Registered faults feed child aborts. Never feed a child's immediate
    // fault back into its own combinational configuration/output predicates.
    bridge_abort = abort_valid || epoch_fault_latched || source_error || child_epoch_invalid;

    fabric_merge_request = child_merge_request;
    fabric_merge_request.cfg_valid = !bridge_abort && child_merge_request.cfg_valid &&
      fabric_size_response.frame_ready;
    fabric_merge_request.sign_valid = !bridge_abort && child_merge_request.sign_valid;
    fabric_merge_request.map_ready = bridge_abort ? 1'b1 :
      child_merge_request.map_ready && fabric_size_response.map_ready;
    fabric_merge_request.done_ready = !bridge_abort && child_merge_request.done_ready;
    fabric_sign_data = child_sign_data;
    child_merge_response = fabric_merge_response;
    child_merge_response.cfg_ready = bridge_abort ? fabric_merge_response.cfg_ready :
      fabric_merge_response.cfg_ready && fabric_size_response.frame_ready;
    child_merge_response.map_valid = bridge_abort ? fabric_merge_response.map_valid :
      fabric_merge_response.map_valid && fabric_size_response.map_ready;

    fabric_size_request = '0;
    fabric_size_request.frame_valid = !bridge_abort && child_merge_request.cfg_valid &&
      fabric_merge_response.cfg_ready;
    fabric_size_request.map_valid = !bridge_abort && fabric_merge_response.map_valid &&
      child_merge_request.map_ready;
    fabric_size_request.map_origin = fabric_merge_response.map_origin;
    fabric_size_request.map_last = fabric_merge_response.map_last;
    if (physical_owner == OwnerNext) begin
      fabric_size_request.query_valid = next_size_request.query_valid && !epoch_fault &&
        !next_release_valid;
      fabric_size_request.query_position = next_size_request.query_position;
      // A prior Walk/Emit remains observable and drainable after a fault.
      fabric_size_request.out_ready = next_size_request.out_ready;
    end else if (bridge_abort) begin
      fabric_size_request.out_ready = 1'b1;
    end
    next_size_response   = '0;
    next_size_out_origin = 0;
    if (physical_owner == OwnerNext) begin
      next_size_response = fabric_size_response;
      next_size_response.frame_ready = 0;
      next_size_response.map_ready = 0;
      next_size_response.query_ready = fabric_size_response.query_ready && !epoch_fault &&
        !next_release_valid;
      next_size_out_origin = fabric_size_out_origin;
    end

    // FaultLock inhibits new work but retains the REAL owner and response mux.
    store_acquire_valid = rst_n && physical_owner == OwnerCompactor && child_acquire_valid;
    child_acquire_ready = rst_n && physical_owner == OwnerCompactor && store_acquire_ready;
    store_req_valid = 0;
    store_req_write = 0;
    store_req_word = 0;
    store_req_data = 0;
    store_rsp_ready = 0;
    child_memory_req_ready = 0;
    child_memory_rsp_valid = 0;
    next_req_ready = 0;
    next_rsp_valid = 0;
    next_rsp_error = store_rsp_error;
    next_rsp_data = store_rsp_data;
    case (physical_owner)
      OwnerCompactor: begin
        store_req_valid = rst_n && child_memory_req_valid;
        store_req_write = child_memory_req_write;
        store_req_word = child_memory_req_word;
        store_req_data = child_memory_req_data;
        child_memory_req_ready = rst_n && store_req_ready;
        store_rsp_ready = rst_n && child_memory_rsp_ready;
        child_memory_rsp_valid = rst_n && store_rsp_valid;
      end
      OwnerNext: begin
        store_req_valid = rst_n && next_req_valid && !epoch_fault && !next_release_valid &&
          !store_response_pending && !store_rsp_valid;
        store_req_write = next_req_write;
        store_req_word = next_req_word;
        store_req_data = next_req_data;
        next_req_ready = rst_n && store_req_ready && !epoch_fault && !next_release_valid &&
          !store_response_pending && !store_rsp_valid;
        store_rsp_ready = rst_n && next_rsp_ready;
        next_rsp_valid = rst_n && store_rsp_valid;
      end
      default: begin
      end
    endcase
    size_port_quiet = !fabric_size_response.out_valid &&
      (fabric_size_response.frame_ready || fabric_size_response.map_ready);
    next_release_quiet = !epoch_fault && physical_acquired && store_context_owned &&
      !store_response_pending && !store_rsp_valid && !store_req_valid && !next_req_valid &&
      !next_size_request.frame_valid && !next_size_request.map_valid &&
      !next_size_request.query_valid && fabric_size_response.frame_ready &&
      !fabric_size_response.out_valid && source_port_idle && !read_req_valid && !read_rsp_valid &&
      !vector_req_valid && !vector_rsp_valid;
    store_release_valid = rst_n && physical_owner == OwnerNext &&
      next_release_valid && next_release_quiet;
    next_release_ready = rst_n && physical_owner == OwnerNext &&
      next_release_quiet && store_release_ready;
    acquire_fire = store_acquire_valid && store_acquire_ready;
    release_fire = store_release_valid && store_release_ready;
    store_request_fire = store_req_valid && store_req_ready;
    store_response_fire = store_rsp_valid && store_rsp_ready;
    public_done_fire = done_valid && done_ready;

    frame_protect = rst_n && (cfg_valid || frame_active || physical_acquired || done_valid ||
      physical_owner != OwnerNone || child_frame_protect || epoch_fault_latched);
    port_idle = rst_n && source_port_idle && !read_req_valid && !read_rsp_valid &&
      !store_response_pending && !store_req_valid && !store_rsp_valid &&
      !vector_req_valid && !vector_rsp_valid && size_port_quiet &&
      !(physical_owner == OwnerNext && next_size_request.query_valid);
    idle = rst_n && !frame_active && !frame_started && !done_valid && !epoch_fault &&
      !physical_acquired && physical_owner == OwnerNone && !store_context_owned &&
      !cfg_valid && !abort_valid && source_idle && !child_frame_protect && port_idle;
  end

  tri_oracle_raw32_frame_source_v1 source (
      .clk,
      .rst_n,
      .abort_valid(abort_valid || epoch_fault_latched),
      .cfg_valid(children_cfg_valid),
      .cfg_ready(source_cfg_ready),
      .cfg_new_image,
      .cfg_tag_base,
      .cfg_layer,
      .cfg_epoch,
      .cfg_image_start,
      .cfg_input_rows,
      .cfg_raw_frame_base,
      .cfg_raw_frame_bytes,
      .cfg_metadata_base,
      .cfg_metadata_bytes,
      .cfg_gamma_base,
      .cfg_gamma_bytes,
      .cfg_gamma_exponent,
      .row_request_valid,
      .row_request_ready,
      .row_request_original_root,
      .row_request_input_rank,
      .row_request_tag,
      .row_request_layer,
      .row_request_epoch,
      .out_valid(normalized_valid),
      .out_last(normalized_last),
      .out_error(normalized_error),
      .out_ready(normalized_ready),
      .out_tag(normalized_tag),
      .out_index(normalized_index),
      .out_count(normalized_count),
      .out_activation(normalized_activation),
      .out_exponent(normalized_exponent),
      .out_outlier_mask(normalized_outlier_mask),
      .out_outlier_negative(normalized_outlier_negative),
      .out_normalized_negative(normalized_negative),
      .read_req_valid,
      .read_req_ready,
      .read_req_address,
      .read_req_length,
      .read_rsp_valid,
      .read_rsp_last,
      .read_rsp_error,
      .read_rsp_ready,
      .read_rsp_data,
      .retire_valid(source_retire_valid),
      .retire_ready(source_retire_ready),
      .row_source_error(source_error),
      .producer_idle(source_producer_idle),
      .port_idle(source_port_idle),
      .idle(source_idle),
      .accepted_rows(source_accepted_rows),
      .completed_rows(source_completed_rows)
  );

  tri_oracle_normalized_image_compactor compactor (
      .clk,
      .rst_n,
      .cfg_valid(children_cfg_valid),
      .cfg_new_image,
      .cfg_minimum_matches,
      .cfg_tag_base,
      .cfg_layer,
      .cfg_epoch,
      .cfg_immutable_input_base(envelope_base),
      .cfg_immutable_input_bytes(envelope_span[63:0]),
      .cfg_compact_output_base,
      // Once the child has latched the fault, release its abort input so its
      // actual drain can reach error completion. The epoch remains fenced.
      .abort_valid(frame_started && (abort_valid || (epoch_fault_latched && !child_epoch_invalid))),
      .row_source_error(source_error),
      .cfg_ready(child_cfg_ready),
      .frame_protect(child_frame_protect),
      .epoch_invalid(child_epoch_invalid),
      .row_request_valid,
      .row_request_ready,
      .producer_idle(source_producer_idle),
      .row_request_original_root,
      .row_request_input_rank,
      .row_request_tag,
      .row_request_layer,
      .row_request_epoch,
      .in_valid(normalized_valid),
      .in_ready(normalized_ready),
      .in_tag(normalized_tag),
      .in_index(normalized_index),
      .in_count(normalized_count),
      .in_last(normalized_last),
      .in_error(normalized_error),
      .in_activation(normalized_activation),
      .in_exponent(normalized_exponent),
      .in_negative(normalized_negative),
      .memory_acquire_valid(child_acquire_valid),
      .memory_acquire_ready(child_acquire_ready),
      .memory_context_owned(store_context_owned),
      .frame_port_granted,
      .memory_req_valid(child_memory_req_valid),
      .memory_req_write(child_memory_req_write),
      .memory_req_ready(child_memory_req_ready),
      .memory_req_word(child_memory_req_word),
      .memory_req_data(child_memory_req_data),
      .memory_rsp_valid(child_memory_rsp_valid),
      .memory_rsp_error(store_rsp_error),
      .memory_rsp_data(store_rsp_data),
      .memory_rsp_ready(child_memory_rsp_ready),
      .merge_request(child_merge_request),
      .merge_response(child_merge_response),
      .merge_sign_data(child_sign_data),
      .size_request_observed(fabric_size_request),
      .size_response_observed(fabric_size_response),
      .vector_req_valid,
      .vector_req_ready,
      .vector_req_address,
      .vector_req_data,
      .vector_rsp_valid,
      .vector_rsp_error,
      .vector_rsp_ready,
      .image_done_valid(child_done_valid),
      .image_error(child_done_error),
      .abort_drained(child_abort_drained),
      .image_done_ready(child_done_ready),
      .handoff_tag_base(child_done_tag_base),
      .handoff_layer(child_done_layer),
      .handoff_epoch(child_done_epoch),
      .handoff_input_count(child_done_input_count),
      .handoff_kept_count(child_done_kept_count)
  );

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      physical_owner <= OwnerNone;
      physical_acquired <= 0;
      frame_active <= 0;
      frame_started <= 0;
      completion_seen <= 0;
      epoch_fault_latched <= 0;
      store_response_pending <= 0;
      saved_tag_base <= 0;
      saved_layer <= 0;
      saved_epoch <= 0;
      saved_input_rows <= 0;
      done_valid <= 0;
      done_error <= 0;
      done_tag_base <= 0;
      done_layer <= 0;
      done_epoch <= 0;
      done_input_count <= 0;
      done_kept_count <= 0;
      metadata_needs_rebuild <= 1;
    end else begin
      if (metadata_rebuilt && idle && !cfg_fire) metadata_needs_rebuild <= 0;
      if (store_request_fire) store_response_pending <= 1;
      if (store_response_fire) store_response_pending <= 0;
      if (acquire_fire) begin
        physical_acquired <= 1;
        metadata_needs_rebuild <= 1;
      end
      if (cfg_fire) begin
        saved_tag_base <= cfg_tag_base;
        saved_layer <= cfg_layer;
        saved_epoch <= cfg_epoch;
        saved_input_rows <= cfg_input_rows;
        frame_active <= 1;
        frame_started <= configuration_legal;
        completion_seen <= !configuration_legal;
        if (configuration_legal) begin
          physical_owner <= OwnerCompactor;
        end else begin
          done_valid <= 1;
          done_error <= 1;
          done_tag_base <= cfg_tag_base;
          done_layer <= cfg_layer;
          done_epoch <= cfg_epoch;
          done_input_count <= 0;
          done_kept_count <= 0;
          epoch_fault_latched <= 1;
        end
      end
      if (capture_first) begin
        completion_seen <= 1;
        done_valid <= 1;
        done_error <= child_done_error || fault_now || completion_join_bad || completion_drain_bad;
        done_tag_base <= child_done_tag_base;
        done_layer <= child_done_layer;
        done_epoch <= child_done_epoch;
        done_input_count <= child_done_input_count;
        done_kept_count <= child_done_kept_count;
        physical_owner <= physical_acquired ? OwnerParentHeld : OwnerNone;
        if (completion_join_bad || completion_drain_bad) epoch_fault_latched <= 1;
      end
      if (public_done_fire) begin
        done_valid <= 0;
        if (!done_error && !epoch_fault_latched && !fault_now &&
            physical_acquired && store_context_owned) begin
          physical_owner <= OwnerNext;
        end else if (!physical_acquired) begin
          physical_owner <= OwnerNone;
          frame_active   <= 0;
        end
      end
      if (release_fire) begin
        physical_acquired <= 0;
        physical_owner <= OwnerNone;
        frame_active <= 0;
        frame_started <= 0;
      end
      // Never change a published tuple on a later fault or child status.
      if (fault_now) epoch_fault_latched <= 1;
    end
  end
endmodule
