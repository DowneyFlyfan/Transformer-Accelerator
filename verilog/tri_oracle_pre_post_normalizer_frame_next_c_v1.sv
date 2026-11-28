`timescale 1ns / 1ps
// One C source serves PRE, then POST under the retained physical lease.
// POST operands are supplied by the caller; this does not implement attention.
// Fault lock preserves known offered/owned traffic and requires coupled reset.
module tri_oracle_pre_post_normalizer_frame_next_c_v1 (
    // Third logical client of the same retained raw32 C source.
    input tri_oracle_next_c_types_v1::request_t next_c_request,
    output tri_oracle_next_c_types_v1::response_t next_c_response,
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
    output logic [9:0] next_size_out_origin,
    input logic post_cfg_valid,
    output logic post_cfg_ready,
    input logic [31:0] post_cfg_tag_base,
    input logic [63:0] post_cfg_raw_frame_base,
    input logic [63:0] post_cfg_raw_frame_bytes,
    input logic [63:0] post_cfg_metadata_base,
    input logic [63:0] post_cfg_metadata_bytes,
    input logic [63:0] post_cfg_gamma_base,
    input logic [63:0] post_cfg_gamma_bytes,
    input logic [63:0] post_cfg_feature_base,
    input logic [63:0] post_cfg_feature_bytes,
    input logic signed [7:0] post_cfg_gamma_exponent,
    input logic [127:0] post_cfg_bundle_id,
    output logic post_done_valid,
    input logic post_done_ready,
    output logic post_done_error,
    output logic post_epoch_fault,
    output logic post_active,
    output logic [31:0] post_done_tag_base,
    output logic [4:0] post_done_layer,
    output logic [15:0] post_done_epoch,
    output logic [9:0] post_done_count,
    output logic [63:0] post_done_code_base,
    output logic [63:0] post_done_feature_base,
    output logic [127:0] post_done_bundle_id,
    output logic feature_req_valid,
    input logic feature_req_ready,
    output logic [63:0] feature_req_address,
    output logic [4:0] feature_req_length,
    output logic feature_data_valid,
    input logic feature_data_ready,
    output logic feature_data_last,
    output logic [63:0] feature_data,
    output logic [7:0] feature_strobe,
    input logic feature_rsp_valid,
    output logic feature_rsp_ready,
    input logic feature_rsp_error
);
  logic next_c_granted, next_c_used, next_c_frame_started, next_c_retired_seen;
  logic next_c_cfg_offer, next_c_row_offer, next_c_retire_offer;
  logic next_c_cfg_just_fired, next_c_row_just_fired, next_c_retire_just_fired;
  logic next_c_fault_latched, next_c_fault_now;
  logic next_c_authority, next_c_check_controls, next_c_can_relinquish;
  logic next_c_cfg_bad, next_c_row_bad, next_c_full_frame;
  logic next_c_take_grant, next_c_take_row, next_c_take_retire, next_c_drop_grant;
  logic next_c_cfg_fire, next_c_row_fire, next_c_retire_fire;
  logic [9:0] next_c_configured_rows;
  tri_oracle_next_c_types_v1::request_t next_c_held_cfg, next_c_held_row;
  logic pre_c_abort_valid;
  logic src_abort_valid;
  logic pre_c_cfg_valid;
  logic src_cfg_valid;
  logic pre_c_cfg_ready;
  logic src_cfg_ready;
  logic pre_c_cfg_new_image;
  logic src_cfg_new_image;
  logic [31:0] pre_c_cfg_tag_base;
  logic [31:0] src_cfg_tag_base;
  logic [4:0] pre_c_cfg_layer;
  logic [4:0] src_cfg_layer;
  logic [15:0] pre_c_cfg_epoch;
  logic [15:0] src_cfg_epoch;
  logic [9:0] pre_c_cfg_image_start;
  logic [9:0] src_cfg_image_start;
  logic [9:0] pre_c_cfg_input_rows;
  logic [9:0] src_cfg_input_rows;
  logic [63:0] pre_c_cfg_raw_frame_base;
  logic [63:0] src_cfg_raw_frame_base;
  logic [63:0] pre_c_cfg_raw_frame_bytes;
  logic [63:0] src_cfg_raw_frame_bytes;
  logic [63:0] pre_c_cfg_metadata_base;
  logic [63:0] src_cfg_metadata_base;
  logic [63:0] pre_c_cfg_metadata_bytes;
  logic [63:0] src_cfg_metadata_bytes;
  logic [63:0] pre_c_cfg_gamma_base;
  logic [63:0] src_cfg_gamma_base;
  logic [63:0] pre_c_cfg_gamma_bytes;
  logic [63:0] src_cfg_gamma_bytes;
  logic signed [7:0] pre_c_cfg_gamma_exponent;
  logic signed [7:0] src_cfg_gamma_exponent;
  logic pre_c_row_request_valid;
  logic src_row_request_valid;
  logic pre_c_row_request_ready;
  logic src_row_request_ready;
  logic [9:0] pre_c_row_request_original_root;
  logic [9:0] src_row_request_original_root;
  logic [9:0] pre_c_row_request_input_rank;
  logic [9:0] src_row_request_input_rank;
  logic [31:0] pre_c_row_request_tag;
  logic [31:0] src_row_request_tag;
  logic [4:0] pre_c_row_request_layer;
  logic [4:0] src_row_request_layer;
  logic [15:0] pre_c_row_request_epoch;
  logic [15:0] src_row_request_epoch;
  logic pre_c_out_valid;
  logic src_out_valid;
  logic pre_c_out_last;
  logic src_out_last;
  logic pre_c_out_error;
  logic src_out_error;
  logic pre_c_out_ready;
  logic src_out_ready;
  logic [31:0] pre_c_out_tag;
  logic [31:0] src_out_tag;
  logic [9:0] pre_c_out_index;
  logic [9:0] src_out_index;
  logic [3:0] pre_c_out_count;
  logic [3:0] src_out_count;
  logic [63:0] pre_c_out_activation;
  logic [63:0] src_out_activation;
  logic signed [8:0] pre_c_out_exponent;
  logic signed [8:0] src_out_exponent;
  logic [7:0] pre_c_out_outlier_mask;
  logic [7:0] src_out_outlier_mask;
  logic [7:0] pre_c_out_outlier_negative;
  logic [7:0] src_out_outlier_negative;
  logic [7:0] pre_c_out_normalized_negative;
  logic [7:0] src_out_normalized_negative;
  logic pre_c_retire_valid;
  logic src_retire_valid;
  logic pre_c_retire_ready;
  logic src_retire_ready;
  logic pre_c_row_source_error;
  logic src_row_source_error;
  logic pre_c_producer_idle;
  logic src_producer_idle;
  logic pre_c_port_idle;
  logic src_port_idle;
  logic pre_c_idle;
  logic src_idle;
  logic [9:0] pre_c_accepted_rows;
  logic [9:0] src_accepted_rows;
  logic [9:0] pre_c_completed_rows;
  logic [9:0] src_completed_rows;
  logic pre_c_read_req_valid;
  logic pre_c_read_rsp_valid;

  typedef enum logic [3:0] {
    PreRun, ConfigurePost, DescriptorOffer, DescriptorWait, RowAdmit,
    RowWait, RowAcknowledge, RetirePost, WaitPostQuiet, PostHeld, PostNext, FaultLock
  } phase_t;
  typedef enum logic [1:0] {NextNone, NextExternal, NextDescriptor, NextWriter} next_owner_t;
  typedef enum logic [1:0] {VectorNone, VectorPre, VectorPost} vector_owner_t;
  phase_t phase;
  next_owner_t next_owner;
  vector_owner_t vector_owner;
  logic vector_pending, next_quarantined, vector_quarantined;
  logic pre_success_seen, pre_retired_seen, post_retired_seen, post_reserved;
  logic post_handoff_seen, external_offer, external_size_offer;
  logic post_fault_latched, post_fault_now, post_configuration_bad;
  logic post_cfg_fire, pre_cfg_valid, pre_cfg_ready, pre_abort_valid;
  logic pre_epoch_fault, pre_port_idle, pre_idle, pre_next_release_ready;
  logic pre_next_release_valid, pre_next_req_valid, pre_next_req_write;
  logic pre_next_req_ready, pre_next_rsp_valid, pre_next_rsp_ready, pre_next_rsp_error;
  logic [9:0] pre_next_req_word;
  logic [63:0] pre_next_req_data, pre_next_rsp_data;
  logic pre_vector_req_valid, pre_vector_req_ready, pre_vector_rsp_valid, pre_vector_rsp_ready;
  logic [63:0] pre_vector_req_address;
  logic [511:0] pre_vector_req_data;
  tri_oracle_token_size_types::request_t pre_next_size_request;
  tri_oracle_token_size_types::response_t pre_next_size_response;
  logic [9:0] pre_next_size_out_origin;
  logic [31:0] saved_pre_tag_base, saved_post_tag_base;
  logic [4:0] saved_layer;
  logic [15:0] saved_epoch;
  logic [9:0] saved_image_start, saved_pre_input_rows, saved_kept_rows;
  logic [9:0] pre_source_accepted, pre_source_completed;
  logic pre_source_error, saved_pre_new_image;
  logic [9:0] previous_pre_rank;
  logic [63:0] saved_code_base, saved_raw_base, saved_raw_bytes;
  logic [63:0] saved_metadata_base, saved_metadata_bytes, saved_gamma_base, saved_gamma_bytes;
  logic [63:0] saved_feature_base, saved_feature_bytes;
  logic signed [7:0] saved_gamma_exponent;
  logic [127:0] saved_bundle_id;
  logic [63:0] saved_immutable_base, saved_immutable_bytes, saved_code_bytes;
  logic [9:0] post_rank, post_root, previous_root;
  logic desc_offered, row_admit, row_status_good, row_status_bad;
  logic source_row_quiet, post_source_quiet, post_restore_quiet, external_next_enabled;
  logic selected_next_writer, selected_next_descriptor, selected_vector_post;
  logic next_request_fire, next_response_fire, vector_request_fire, vector_response_fire;
  logic descriptor_bad, unexpected_next_response, unexpected_vector_response;
  logic [32:0] descriptor_tag_delta, post_tag_last;
  logic [64:0] post_raw_last, post_metadata_last, post_gamma_last, post_feature_last;
  logic [64:0] post_code_last, post_needed_raw, post_envelope_span;
  logic [63:0] post_envelope_base, post_envelope_last;
  logic [64:0] post_code_bytes;

  logic writer_cfg_valid, writer_cfg_ready, writer_abort, writer_in_ready;
  logic writer_vector_req_valid, writer_vector_req_ready, writer_vector_rsp_valid, writer_vector_rsp_ready;
  logic [63:0] writer_vector_req_address;
  logic [511:0] writer_vector_req_data;
  logic writer_next_req_valid, writer_next_req_write, writer_next_req_ready;
  logic writer_next_rsp_valid, writer_next_rsp_ready;
  logic [9:0] writer_next_req_word;
  logic [63:0] writer_next_req_data;
  logic writer_done_valid, writer_done_ready, writer_done_error, writer_epoch_fault;
  logic writer_active, writer_idle, writer_descriptor_acknowledged;
  logic [31:0] writer_done_tag;
  logic [4:0] writer_done_layer;
  logic [15:0] writer_done_epoch;
  logic [9:0] writer_done_root, writer_done_input_rank, writer_done_kept_rank;
  logic signed [8:0] writer_done_exponent;
  logic [8:0] writer_accepted_strips;
  logic [5:0] writer_acknowledged_lines;
  logic aux_valid, aux_ready, aux_last, aux_error;
  logic [31:0] aux_tag;
  logic [4:0] aux_layer;
  logic [15:0] aux_epoch;
  logic [9:0] aux_original_root, aux_input_rank, aux_kept_rank, aux_index;
  logic [3:0] aux_count;
  logic signed [8:0] aux_exponent;
  logic [7:0] aux_outlier_mask, aux_normalized_negative, aux_outlier_negative;
  logic feature_cfg_valid, feature_cfg_ready;
  logic feature_done_valid, feature_done_ready, feature_done_error, feature_epoch_fault;
  logic feature_active, feature_port_idle, feature_idle;
  logic [31:0] feature_done_tag;
  logic [4:0] feature_done_layer;
  logic [15:0] feature_done_epoch;
  logic [9:0] feature_done_root, feature_done_input_rank, feature_done_kept_rank;
  logic signed [8:0] feature_done_exponent;
  logic [8:0] feature_accepted_strips;
  logic [3:0] feature_acknowledged_lines;

  function automatic logic overlap(
      input logic [63:0] first_base, second_base,
      input logic [64:0] first_last, second_last);
    return {1'b0,first_base} <= second_last && {1'b0,second_base} <= first_last;
  endfunction
  tri_oracle_raw32_frame_parent_client_v2 pre (
    .clk(clk),
    .rst_n(rst_n),
    .abort_valid(pre_abort_valid),
    .cfg_valid(pre_cfg_valid),
    .cfg_ready(pre_cfg_ready),
    .cfg_new_image(cfg_new_image),
    .cfg_minimum_matches(cfg_minimum_matches),
    .cfg_tag_base(cfg_tag_base),
    .cfg_layer(cfg_layer),
    .cfg_epoch(cfg_epoch),
    .cfg_image_start(cfg_image_start),
    .cfg_input_rows(cfg_input_rows),
    .cfg_raw_frame_base(cfg_raw_frame_base),
    .cfg_raw_frame_bytes(cfg_raw_frame_bytes),
    .cfg_metadata_base(cfg_metadata_base),
    .cfg_metadata_bytes(cfg_metadata_bytes),
    .cfg_gamma_base(cfg_gamma_base),
    .cfg_gamma_bytes(cfg_gamma_bytes),
    .cfg_compact_output_base(cfg_compact_output_base),
    .cfg_gamma_exponent(cfg_gamma_exponent),
    .store_acquire_valid(store_acquire_valid),
    .store_release_valid(store_release_valid),
    .store_req_valid(store_req_valid),
    .store_req_write(store_req_write),
    .store_rsp_ready(store_rsp_ready),
    .store_acquire_ready(store_acquire_ready),
    .store_release_ready(store_release_ready),
    .store_context_owned(store_context_owned),
    .store_req_ready(store_req_ready),
    .store_rsp_valid(store_rsp_valid),
    .store_rsp_error(store_rsp_error),
    .store_req_word(store_req_word),
    .store_req_data(store_req_data),
    .store_rsp_data(store_rsp_data),
    .next_req_valid(pre_next_req_valid),
    .next_req_write(pre_next_req_write),
    .next_rsp_ready(pre_next_rsp_ready),
    .next_release_valid(pre_next_release_valid),
    .next_req_ready(pre_next_req_ready),
    .next_rsp_valid(pre_next_rsp_valid),
    .next_rsp_error(pre_next_rsp_error),
    .next_release_ready(pre_next_release_ready),
    .next_req_word(pre_next_req_word),
    .next_req_data(pre_next_req_data),
    .next_rsp_data(pre_next_rsp_data),
    .vector_req_valid(pre_vector_req_valid),
    .vector_rsp_ready(pre_vector_rsp_ready),
    .vector_req_ready(pre_vector_req_ready),
    .vector_rsp_valid(pre_vector_rsp_valid),
    .vector_rsp_error(vector_rsp_error),
    .vector_req_address(pre_vector_req_address),
    .vector_req_data(pre_vector_req_data),
    .done_valid(done_valid),
    .done_error(done_error),
    .epoch_fault(pre_epoch_fault),
    .frame_protect(frame_protect),
    .metadata_needs_rebuild(metadata_needs_rebuild),
    .port_idle(pre_port_idle),
    .idle(pre_idle),
    .done_ready(done_ready),
    .metadata_rebuilt(metadata_rebuilt),
    .done_tag_base(done_tag_base),
    .done_layer(done_layer),
    .done_epoch(done_epoch),
    .done_input_count(done_input_count),
    .done_kept_count(done_kept_count),
    .fabric_merge_request(fabric_merge_request),
    .fabric_merge_response(fabric_merge_response),
    .fabric_sign_data(fabric_sign_data),
    .fabric_size_request(fabric_size_request),
    .fabric_size_response(fabric_size_response),
    .fabric_size_out_origin(fabric_size_out_origin),
    .next_size_request(pre_next_size_request),
    .next_size_response(pre_next_size_response),
    .next_size_out_origin(pre_next_size_out_origin),
    .c_abort_valid(pre_c_abort_valid),
    .c_cfg_valid(pre_c_cfg_valid),
    .c_cfg_ready(pre_c_cfg_ready),
    .c_cfg_new_image(pre_c_cfg_new_image),
    .c_cfg_tag_base(pre_c_cfg_tag_base),
    .c_cfg_layer(pre_c_cfg_layer),
    .c_cfg_epoch(pre_c_cfg_epoch),
    .c_cfg_image_start(pre_c_cfg_image_start),
    .c_cfg_input_rows(pre_c_cfg_input_rows),
    .c_cfg_raw_frame_base(pre_c_cfg_raw_frame_base),
    .c_cfg_raw_frame_bytes(pre_c_cfg_raw_frame_bytes),
    .c_cfg_metadata_base(pre_c_cfg_metadata_base),
    .c_cfg_metadata_bytes(pre_c_cfg_metadata_bytes),
    .c_cfg_gamma_base(pre_c_cfg_gamma_base),
    .c_cfg_gamma_bytes(pre_c_cfg_gamma_bytes),
    .c_cfg_gamma_exponent(pre_c_cfg_gamma_exponent),
    .c_row_request_valid(pre_c_row_request_valid),
    .c_row_request_ready(pre_c_row_request_ready),
    .c_row_request_original_root(pre_c_row_request_original_root),
    .c_row_request_input_rank(pre_c_row_request_input_rank),
    .c_row_request_tag(pre_c_row_request_tag),
    .c_row_request_layer(pre_c_row_request_layer),
    .c_row_request_epoch(pre_c_row_request_epoch),
    .c_out_valid(pre_c_out_valid),
    .c_out_last(pre_c_out_last),
    .c_out_error(pre_c_out_error),
    .c_out_ready(pre_c_out_ready),
    .c_out_tag(pre_c_out_tag),
    .c_out_index(pre_c_out_index),
    .c_out_count(pre_c_out_count),
    .c_out_activation(pre_c_out_activation),
    .c_out_exponent(pre_c_out_exponent),
    .c_out_outlier_mask(pre_c_out_outlier_mask),
    .c_out_outlier_negative(pre_c_out_outlier_negative),
    .c_out_normalized_negative(pre_c_out_normalized_negative),
    .c_retire_valid(pre_c_retire_valid),
    .c_retire_ready(pre_c_retire_ready),
    .c_row_source_error(pre_c_row_source_error),
    .c_producer_idle(pre_c_producer_idle),
    .c_port_idle(pre_c_port_idle),
    .c_idle(pre_c_idle),
    .c_accepted_rows(pre_c_accepted_rows),
    .c_completed_rows(pre_c_completed_rows),
    .c_read_req_valid(pre_c_read_req_valid),
    .c_read_rsp_valid(pre_c_read_rsp_valid)
  );
  tri_oracle_raw32_frame_source_v1 source (
    .clk(clk),
    .rst_n(rst_n),
    .abort_valid(src_abort_valid),
    .cfg_valid(src_cfg_valid),
    .cfg_ready(src_cfg_ready),
    .cfg_new_image(src_cfg_new_image),
    .cfg_tag_base(src_cfg_tag_base),
    .cfg_layer(src_cfg_layer),
    .cfg_epoch(src_cfg_epoch),
    .cfg_image_start(src_cfg_image_start),
    .cfg_input_rows(src_cfg_input_rows),
    .cfg_raw_frame_base(src_cfg_raw_frame_base),
    .cfg_raw_frame_bytes(src_cfg_raw_frame_bytes),
    .cfg_metadata_base(src_cfg_metadata_base),
    .cfg_metadata_bytes(src_cfg_metadata_bytes),
    .cfg_gamma_base(src_cfg_gamma_base),
    .cfg_gamma_bytes(src_cfg_gamma_bytes),
    .cfg_gamma_exponent(src_cfg_gamma_exponent),
    .row_request_valid(src_row_request_valid),
    .row_request_ready(src_row_request_ready),
    .row_request_original_root(src_row_request_original_root),
    .row_request_input_rank(src_row_request_input_rank),
    .row_request_tag(src_row_request_tag),
    .row_request_layer(src_row_request_layer),
    .row_request_epoch(src_row_request_epoch),
    .out_valid(src_out_valid),
    .out_last(src_out_last),
    .out_error(src_out_error),
    .out_ready(src_out_ready),
    .out_tag(src_out_tag),
    .out_index(src_out_index),
    .out_count(src_out_count),
    .out_activation(src_out_activation),
    .out_exponent(src_out_exponent),
    .out_outlier_mask(src_out_outlier_mask),
    .out_outlier_negative(src_out_outlier_negative),
    .out_normalized_negative(src_out_normalized_negative),
    .retire_valid(src_retire_valid),
    .retire_ready(src_retire_ready),
    .row_source_error(src_row_source_error),
    .producer_idle(src_producer_idle),
    .port_idle(src_port_idle),
    .idle(src_idle),
    .accepted_rows(src_accepted_rows),
    .completed_rows(src_completed_rows),
    .read_req_valid(read_req_valid),
    .read_req_ready(read_req_ready),
    .read_req_address(read_req_address),
    .read_req_length(read_req_length),
    .read_rsp_valid(read_rsp_valid),
    .read_rsp_last(read_rsp_last),
    .read_rsp_error(read_rsp_error),
    .read_rsp_ready(read_rsp_ready),
    .read_rsp_data(read_rsp_data)
  );

  tri_oracle_post_normalized_row_writer_v1 writer (
    .clk, .rst_n, .abort_valid(writer_abort), .producer_idle(src_producer_idle),
    .cfg_valid(writer_cfg_valid), .cfg_ready(writer_cfg_ready),
    .cfg_normalization_role(2'd1), .cfg_tag(saved_post_tag_base + 32'(post_rank)),
    .cfg_layer(saved_layer), .cfg_epoch(saved_epoch), .cfg_original_root(post_root),
    .cfg_input_rank(post_rank), .cfg_kept_rank(post_rank), .cfg_code_base(saved_code_base),
    .cfg_immutable_input_base(saved_immutable_base), .cfg_immutable_input_bytes(saved_immutable_bytes),
    .next_context_owned(store_context_owned),
    .in_valid(post_reserved && !next_c_granted && src_out_valid), .in_ready(writer_in_ready),
    .in_last(src_out_last), .in_error(src_out_error), .in_tag(src_out_tag),
    .in_index(src_out_index), .in_count(src_out_count), .in_activation(src_out_activation),
    .in_exponent(src_out_exponent), .in_outlier_mask(src_out_outlier_mask),
    .in_normalized_negative(src_out_normalized_negative), .in_outlier_negative(src_out_outlier_negative),
    .aux_valid, .aux_ready, .aux_last, .aux_error, .aux_tag, .aux_layer, .aux_epoch,
    .aux_original_root, .aux_input_rank, .aux_kept_rank, .aux_index, .aux_count,
    .aux_exponent, .aux_outlier_mask, .aux_normalized_negative, .aux_outlier_negative,
    .vector_req_valid(writer_vector_req_valid), .vector_req_ready(writer_vector_req_ready),
    .vector_req_address(writer_vector_req_address), .vector_req_data(writer_vector_req_data),
    .vector_rsp_valid(writer_vector_rsp_valid), .vector_rsp_ready(writer_vector_rsp_ready),
    .vector_rsp_error(vector_rsp_error),
    .next_req_valid(writer_next_req_valid), .next_req_write(writer_next_req_write),
    .next_req_ready(writer_next_req_ready), .next_req_word(writer_next_req_word),
    .next_req_data(writer_next_req_data), .next_rsp_valid(writer_next_rsp_valid),
    .next_rsp_ready(writer_next_rsp_ready), .next_rsp_error(pre_next_rsp_error),
    .next_rsp_data(pre_next_rsp_data), .done_valid(writer_done_valid),
    .done_ready(writer_done_ready), .done_error(writer_done_error),
    .epoch_fault(writer_epoch_fault), .active(writer_active), .idle(writer_idle),
    .done_tag(writer_done_tag), .done_layer(writer_done_layer), .done_epoch(writer_done_epoch),
    .done_original_root(writer_done_root), .done_input_rank(writer_done_input_rank),
    .done_kept_rank(writer_done_kept_rank), .done_exponent(writer_done_exponent),
    .accepted_strips(writer_accepted_strips), .acknowledged_lines(writer_acknowledged_lines),
    .descriptor_acknowledged(writer_descriptor_acknowledged)
  );
  tri_oracle_post_feature_store_v1 features (
    .clk, .rst_n, .abort_valid(writer_abort), .producer_idle(src_producer_idle),
    .next_context_owned(store_context_owned), .cfg_valid(feature_cfg_valid),
    .cfg_ready(feature_cfg_ready), .cfg_normalization_role(2'd1),
    .cfg_tag(saved_post_tag_base + 32'(post_rank)), .cfg_layer(saved_layer), .cfg_epoch(saved_epoch),
    .cfg_original_root(post_root), .cfg_input_rank(post_rank), .cfg_kept_rank(post_rank),
    .cfg_feature_base(saved_feature_base), .cfg_feature_bytes(saved_feature_bytes),
    .cfg_code_base(saved_code_base), .cfg_code_bytes(saved_code_bytes),
    .cfg_immutable_input_base(saved_immutable_base), .cfg_immutable_input_bytes(saved_immutable_bytes),
    .aux_valid, .aux_ready, .aux_last, .aux_error, .aux_tag, .aux_layer, .aux_epoch,
    .aux_original_root, .aux_input_rank, .aux_kept_rank, .aux_index, .aux_count,
    .aux_exponent, .aux_outlier_mask, .aux_normalized_negative, .aux_outlier_negative,
    .scalar_req_valid(feature_req_valid), .scalar_req_ready(feature_req_ready),
    .scalar_req_address(feature_req_address), .scalar_req_length(feature_req_length),
    .scalar_data_valid(feature_data_valid), .scalar_data_ready(feature_data_ready),
    .scalar_data_last(feature_data_last), .scalar_data(feature_data), .scalar_strobe(feature_strobe),
    .scalar_rsp_valid(feature_rsp_valid), .scalar_rsp_ready(feature_rsp_ready),
    .scalar_rsp_error(feature_rsp_error), .done_valid(feature_done_valid),
    .done_ready(feature_done_ready), .done_error(feature_done_error),
    .done_tag(feature_done_tag), .done_layer(feature_done_layer), .done_epoch(feature_done_epoch),
    .done_original_root(feature_done_root), .done_input_rank(feature_done_input_rank),
    .done_kept_rank(feature_done_kept_rank), .done_exponent(feature_done_exponent),
    .accepted_strips(feature_accepted_strips), .acknowledged_lines(feature_acknowledged_lines),
    .epoch_fault(feature_epoch_fault), .active(feature_active), .port_idle(feature_port_idle),
    .idle(feature_idle)
  );

  // Keep PRE's original atomic fork. A POST fault never feeds the retired
  // PRE abort cone: that would fence its already exposed NextOwner writes.
  assign pre_abort_valid = post_reserved ? 1'b0 : abort_valid;
  assign pre_cfg_valid = cfg_valid && phase == PreRun && !post_reserved;
  assign cfg_ready = pre_cfg_ready && phase == PreRun && !post_reserved;
  assign external_next_enabled = !post_reserved || post_handoff_seen;
  assign pre_next_release_valid = next_release_valid && phase == PostNext &&
    !next_c_granted && !post_epoch_fault && !abort_valid;
  assign next_release_ready = pre_next_release_ready && phase == PostNext &&
    !next_c_granted && !post_epoch_fault && !abort_valid;
  assign epoch_fault = pre_epoch_fault || post_epoch_fault;
  assign post_epoch_fault = rst_n && (post_fault_latched || post_fault_now);
  assign post_active = rst_n && post_reserved && phase != PostNext;
  assign port_idle = pre_port_idle && (!post_reserved || phase == PostNext) &&
    !post_epoch_fault && feature_port_idle;
  assign idle = pre_idle && phase == PreRun && !post_reserved && !post_epoch_fault;

  // PRE owns its original immutable completion; POST owns this separate slot.
  // No late fault rewrites or withdraws an offered status tuple.
  assign post_done_error = 1'b0;
  assign post_done_tag_base = saved_post_tag_base;
  assign post_done_layer = saved_layer;
  assign post_done_epoch = saved_epoch;
  assign post_done_count = saved_kept_rows;
  assign post_done_code_base = saved_code_base;
  assign post_done_feature_base = saved_feature_base;
  assign post_done_bundle_id = saved_bundle_id;

  assign post_cfg_fire = post_cfg_valid && post_cfg_ready;
  assign next_request_fire = pre_next_req_valid && pre_next_req_ready;
  assign next_response_fire = pre_next_rsp_valid && pre_next_rsp_ready;
  assign vector_request_fire = vector_req_valid && vector_req_ready;
  assign vector_response_fire = vector_rsp_valid && vector_rsp_ready;
  assign source_row_quiet = src_producer_idle && src_port_idle && !src_out_valid &&
    !read_req_valid && !read_rsp_valid;
  assign post_source_quiet = src_idle && source_row_quiet && !src_retire_valid;
  assign post_restore_quiet = post_retired_seen && post_source_quiet &&
    (phase == PostHeld || phase == PostNext) && !post_fault_latched;

  function automatic logic next_c_configuration_bad(
      input tri_oracle_next_c_types_v1::request_t q);
    // The parent binds ownership and retained image geometry. The SAME C
    // validates its generic tag/layer/epoch/address envelope and row metadata.
    // Do not turn prototype epoch2/layer1 into an FF publication policy.
    return $isunknown(q[541:76]) || q.cfg_new_image !== 1'b0 ||
      q.cfg_input_rows != saved_kept_rows || q.cfg_input_rows == 0 || q.cfg_input_rows > 576 ||
      q.cfg_image_start != saved_image_start;
  endfunction

  always_comb begin
    // POST handoff is reachable only through real PRE/POST completion ACKs.
    // The unchanged PRE parent retains OwnerNext until real physical release;
    // production logic uses that public handoff/lease protocol, not hierarchy.
    next_c_authority = (post_reserved === 1'b1) && (post_handoff_seen === 1'b1) &&
      (phase === PostNext) && (store_context_owned === 1'b1);
    next_c_cfg_bad = next_c_configuration_bad(next_c_request);
    next_c_row_bad = $isunknown(next_c_request[74:2]) ||
      next_c_request.row_request_input_rank != src_accepted_rows ||
      next_c_request.row_request_input_rank >= next_c_configured_rows ||
      next_c_request.row_request_original_root >= 576 ||
      {1'b0,next_c_request.row_request_tag} !=
        {1'b0,next_c_held_cfg.cfg_tag_base} + 33'(next_c_request.row_request_input_rank) ||
      next_c_request.row_request_layer != next_c_held_cfg.cfg_layer ||
      next_c_request.row_request_epoch != next_c_held_cfg.cfg_epoch;
    next_c_full_frame = next_c_frame_started &&
      (src_accepted_rows === next_c_configured_rows) &&
      (src_completed_rows === next_c_configured_rows);
    next_c_can_relinquish = next_c_retired_seen && post_source_quiet &&
      !next_c_cfg_offer && !next_c_row_offer && !next_c_retire_offer &&
      (next_c_request.cfg_valid === 1'b0) &&
      (next_c_request.row_request_valid === 1'b0) &&
      (next_c_request.retire_valid === 1'b0);
    next_c_check_controls = next_c_granted ||
      (next_c_authority && (next_release_valid === 1'b0));

    // Make uncertainty authoritative and known; never select a new client
    // from an unknown phase, lease or transfer-control value.
    next_c_fault_now = 1'b0;
    if (post_reserved !== 1'b0 || next_c_granted) begin
      if ($isunknown({post_reserved,phase,post_handoff_seen,saved_kept_rows,saved_image_start,
                      saved_epoch,saved_layer,next_release_valid}) ||
          (store_context_owned !== 1'b1) || (abort_valid !== 1'b0) ||
          (pre_epoch_fault !== 1'b0) || (src_row_source_error !== 1'b0) ||
          (writer_epoch_fault !== 1'b0) || (feature_epoch_fault !== 1'b0))
        next_c_fault_now = 1'b1;
    end
    if (next_c_check_controls &&
        $isunknown({next_c_request.selected,next_c_request.abort_valid,
          next_c_request.cfg_valid,next_c_request.row_request_valid,
          next_c_request.out_ready,next_c_request.retire_valid}))
      next_c_fault_now = 1'b1;
    if (next_c_check_controls && (next_c_request.abort_valid === 1'b1))
      next_c_fault_now = 1'b1;
    if (!next_c_granted && next_c_authority && (next_release_valid === 1'b0) &&
        (next_c_request.selected === 1'b1) && (next_c_request.cfg_valid === 1'b1) &&
        (next_c_used || next_c_cfg_bad)) next_c_fault_now = 1'b1;
    if (next_c_granted) begin
      if ((post_reserved !== 1'b1) || (post_handoff_seen !== 1'b1) ||
          (phase !== PostNext) || (store_context_owned !== 1'b1))
        next_c_fault_now = 1'b1;
      if ((next_c_request.selected !== 1'b1) &&
          !(next_c_can_relinquish && (next_c_request.selected === 1'b0)))
        next_c_fault_now = 1'b1;
      if ($isunknown({src_cfg_ready,src_row_request_ready,src_retire_ready,
          src_out_valid,src_producer_idle,src_port_idle,src_idle,
          src_accepted_rows,src_completed_rows,read_req_valid,read_rsp_valid,read_rsp_ready}))
        next_c_fault_now = 1'b1;
      if ((read_req_valid === 1'b1) &&
          $isunknown({read_req_address,read_req_length,read_req_ready})) next_c_fault_now = 1'b1;
      if ((read_rsp_valid === 1'b1) && $isunknown({read_rsp_last,read_rsp_error,read_rsp_data}))
        next_c_fault_now = 1'b1;
      if ((src_out_valid === 1'b1) && (src_out_error !== 1'b0)) next_c_fault_now = 1'b1;
      if ((src_out_valid === 1'b1) && $isunknown({src_out_last,src_out_error,
          src_out_tag,src_out_index,src_out_count,src_out_activation,src_out_exponent,
          src_out_outlier_mask,src_out_outlier_negative,src_out_normalized_negative}))
        next_c_fault_now = 1'b1;
      if (next_c_cfg_offer && ((next_c_request.cfg_valid !== 1'b1) ||
          next_c_request[541:76] !== next_c_held_cfg[541:76])) next_c_fault_now = 1'b1;
      if (next_c_frame_started && !next_c_cfg_just_fired &&
          (next_c_request.cfg_valid === 1'b1)) next_c_fault_now = 1'b1;
      if (next_c_row_offer && ((next_c_request.row_request_valid !== 1'b1) ||
          next_c_request[74:2] !== next_c_held_row[74:2])) next_c_fault_now = 1'b1;
      if (next_c_frame_started && !next_c_row_offer && !next_c_row_just_fired &&
          (next_c_request.row_request_valid === 1'b1) && next_c_row_bad)
        next_c_fault_now = 1'b1;
      // Generic C accepts any quiet retirement and faults only afterward.
      // This owner NEVER offers an incomplete target-frame retirement.
      if (next_c_frame_started && !next_c_retired_seen && !next_c_retire_offer &&
          (next_c_request.retire_valid === 1'b1) &&
          (!next_c_full_frame || !source_row_quiet || next_c_cfg_offer || next_c_row_offer))
        next_c_fault_now = 1'b1;
      if (next_c_retired_seen && !next_c_retire_just_fired &&
          (next_c_request.retire_valid === 1'b1)) next_c_fault_now = 1'b1;
    end

  end

  // Keep fault calculation independent of its downstream admission gates.
  // This separate block prevents a procedural always_comb feedback cycle.
  always_comb begin
    // Source status is real and observable before grant; status alone grants
    // no transfer permission. In particular retired POST counts are NOT zero.
    next_c_response = '0;
    next_c_response.row_source_error = src_row_source_error || post_epoch_fault;
    next_c_response.producer_idle = src_producer_idle;
    next_c_response.port_idle = src_port_idle;
    next_c_response.idle = src_idle;
    next_c_response.accepted_rows = src_accepted_rows;
    next_c_response.completed_rows = src_completed_rows;
    next_c_response.read_request_valid = read_req_valid;
    next_c_response.read_response_valid = read_rsp_valid;
    if (next_c_granted) begin
      next_c_response.cfg_ready = next_c_cfg_offer && (src_cfg_ready === 1'b1);
      next_c_response.row_request_ready = next_c_row_offer && (src_row_request_ready === 1'b1);
      next_c_response.out_valid = src_out_valid;
      next_c_response.out_last = src_out_last;
      next_c_response.out_error = src_out_error;
      next_c_response.out_tag = src_out_tag;
      next_c_response.out_index = src_out_index;
      next_c_response.out_count = src_out_count;
      next_c_response.out_activation = src_out_activation;
      next_c_response.out_exponent = src_out_exponent;
      next_c_response.out_outlier_mask = src_out_outlier_mask;
      next_c_response.out_outlier_negative = src_out_outlier_negative;
      next_c_response.out_normalized_negative = src_out_normalized_negative;
      next_c_response.retire_ready = next_c_retire_offer && (src_retire_ready === 1'b1);
    end
    next_c_cfg_fire = next_c_granted && next_c_cfg_offer && (src_cfg_ready === 1'b1);
    next_c_row_fire = next_c_granted && next_c_row_offer && (src_row_request_ready === 1'b1);
    next_c_retire_fire = next_c_granted && next_c_retire_offer && (src_retire_ready === 1'b1);
    // An existing release has priority over a fresh third-client offer.
    next_c_take_grant = next_c_authority && !next_c_granted && !next_c_used &&
      (next_release_valid === 1'b0) && !post_fault_latched && !post_fault_now &&
      !next_c_fault_latched && (src_idle === 1'b1) && (src_cfg_ready === 1'b1) &&
      source_row_quiet && post_retired_seen &&
      (src_accepted_rows === saved_kept_rows) && (src_completed_rows === saved_kept_rows) &&
      (next_c_request.selected === 1'b1) && (next_c_request.cfg_valid === 1'b1) && !next_c_cfg_bad;
    next_c_take_row = next_c_granted && next_c_frame_started && !next_c_retired_seen &&
      !next_c_cfg_offer && !next_c_row_offer && !next_c_row_just_fired && !next_c_retire_offer &&
      !post_fault_latched && !post_fault_now && !next_c_fault_latched &&
      (next_c_request.row_request_valid === 1'b1) && !next_c_row_bad;
    next_c_take_retire = next_c_granted && next_c_full_frame && !next_c_retired_seen &&
      source_row_quiet && !next_c_cfg_offer && !next_c_row_offer && !next_c_retire_offer &&
      !post_fault_latched && !post_fault_now && !next_c_fault_latched &&
      (next_c_request.retire_valid === 1'b1);
    next_c_drop_grant = next_c_granted && next_c_can_relinquish &&
      (next_c_request.selected === 1'b0) && !post_fault_latched && !post_fault_now &&
      !next_c_fault_latched;
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      next_c_granted <= 0; next_c_used <= 0; next_c_frame_started <= 0;
      next_c_retired_seen <= 0; next_c_cfg_offer <= 0; next_c_row_offer <= 0;
      next_c_retire_offer <= 0; next_c_fault_latched <= 0;
      next_c_cfg_just_fired <= 0; next_c_row_just_fired <= 0; next_c_retire_just_fired <= 0;
      next_c_configured_rows <= 0; next_c_held_cfg <= '0; next_c_held_row <= '0;
    end else begin
      next_c_cfg_just_fired <= next_c_cfg_fire;
      next_c_row_just_fired <= next_c_row_fire;
      next_c_retire_just_fired <= next_c_retire_fire;
      if (next_c_fault_now) next_c_fault_latched <= 1;
      if (!post_reserved && !next_c_granted) next_c_used <= 0;
      if (next_c_take_grant) begin
        next_c_granted <= 1; next_c_used <= 1; next_c_cfg_offer <= 1;
        next_c_held_cfg <= next_c_request; next_c_configured_rows <= next_c_request.cfg_input_rows;
        next_c_frame_started <= 0; next_c_retired_seen <= 0;
      end
      if (next_c_cfg_fire) begin next_c_cfg_offer <= 0; next_c_frame_started <= 1; end
      if (next_c_take_row) begin next_c_row_offer <= 1; next_c_held_row <= next_c_request; end
      if (next_c_row_fire) next_c_row_offer <= 0;
      if (next_c_take_retire) next_c_retire_offer <= 1;
      if (next_c_retire_fire) begin next_c_retire_offer <= 0; next_c_retired_seen <= 1; end
      if (next_c_drop_grant) begin
        next_c_granted <= 0; next_c_frame_started <= 0; next_c_retired_seen <= 0;
      end
    end
  end

  always_comb begin
    // Bounds retain carry before ANY truncation. The input envelope protects
    // all holes between the three immutable regions, as in the PRE contract.
    post_raw_last = {1'b0,post_cfg_raw_frame_base} + {1'b0,post_cfg_raw_frame_bytes} - 65'd1;
    post_metadata_last = {1'b0,post_cfg_metadata_base} + {1'b0,post_cfg_metadata_bytes} - 65'd1;
    post_gamma_last = {1'b0,post_cfg_gamma_base} + {1'b0,post_cfg_gamma_bytes} - 65'd1;
    post_feature_last = {1'b0,post_cfg_feature_base} + {1'b0,post_cfg_feature_bytes} - 65'd1;
    post_needed_raw = (65'(saved_image_start) + 65'(saved_kept_rows)) * 65'd8192;
    post_code_bytes = 65'(saved_kept_rows) * 65'd2048;
    post_code_last = {1'b0,saved_code_base} + post_code_bytes - 65'd1;
    post_tag_last = {1'b0,post_cfg_tag_base} + 33'd575;
    post_envelope_base = post_cfg_raw_frame_base;
    if (post_cfg_metadata_base < post_envelope_base) post_envelope_base = post_cfg_metadata_base;
    if (post_cfg_gamma_base < post_envelope_base) post_envelope_base = post_cfg_gamma_base;
    post_envelope_base[5:0] = 0;
    post_envelope_last = post_raw_last[63:0];
    if (post_metadata_last > post_raw_last) post_envelope_last = post_metadata_last[63:0];
    if (post_gamma_last > {1'b0,post_envelope_last}) post_envelope_last = post_gamma_last[63:0];
    post_envelope_last[5:0] = 6'b111111;
    post_envelope_span = {1'b0,post_envelope_last} + 65'd1 - {1'b0,post_envelope_base};
    post_configuration_bad = saved_kept_rows == 0 || saved_kept_rows > 576 || saved_layer >= 22 ||
      post_tag_last[32] || post_cfg_raw_frame_base[5:0] != 0 ||
      post_cfg_raw_frame_bytes == 0 || post_cfg_raw_frame_bytes[5:0] != 0 ||
      {1'b0,post_cfg_raw_frame_bytes} < post_needed_raw || post_raw_last[64] ||
      post_cfg_metadata_base[3:0] != 0 || post_cfg_metadata_bytes[3:0] != 0 ||
      {1'b0,post_cfg_metadata_bytes} < 65'(saved_kept_rows)*65'd16 || post_metadata_last[64] ||
      post_cfg_gamma_base[2:0] != 0 || post_cfg_gamma_bytes != 6144 || post_gamma_last[64] ||
      saved_code_base[5:0] != 0 || post_code_last[64] ||
      post_cfg_feature_base[5:0] != 0 || post_cfg_feature_bytes == 0 ||
      post_cfg_feature_bytes[5:0] != 0 ||
      {1'b0,post_cfg_feature_bytes} < 65'(saved_kept_rows)*65'd768 || post_feature_last[64] ||
      post_envelope_span == 0 || post_envelope_span[64] ||
      overlap(saved_code_base,post_envelope_base,post_code_last,{1'b0,post_envelope_last}) ||
      overlap(post_cfg_feature_base,post_envelope_base,post_feature_last,{1'b0,post_envelope_last}) ||
      overlap(saved_code_base,post_cfg_feature_base,post_code_last,post_feature_last);

    // Genuine size Idle, not merely map-accepting, is required at reservation.
    post_cfg_ready = rst_n && phase == PreRun && pre_success_seen && pre_retired_seen &&
      !post_reserved && store_context_owned && src_cfg_ready && source_row_quiet &&
      !pre_c_cfg_valid && !pre_c_retire_valid && !pre_c_row_request_valid && pre_port_idle &&
      !writer_epoch_fault && !feature_epoch_fault && feature_port_idle &&
      next_owner == NextNone && !external_offer && !external_size_offer &&
      vector_owner == VectorNone && !vector_pending && !next_req_valid && !pre_next_rsp_valid && !store_req_valid && !store_rsp_valid &&
      !next_release_valid && !next_size_request.frame_valid && !next_size_request.map_valid &&
      !next_size_request.query_valid && fabric_size_response.frame_ready &&
      !fabric_size_response.out_valid && !pre_epoch_fault && !abort_valid;

    descriptor_tag_delta = {1'b0,pre_next_rsp_data[31:0]} - {1'b0,saved_pre_tag_base};
    descriptor_bad = pre_next_rsp_error || pre_next_rsp_data[63:61] != 3'b010 ||
      pre_next_rsp_data[51:42] != post_rank || pre_next_rsp_data[41:32] >= 576 ||
      descriptor_tag_delta[32] || descriptor_tag_delta >= {23'b0,saved_pre_input_rows} ||
      (saved_pre_new_image && {23'b0,pre_next_rsp_data[41:32]} != descriptor_tag_delta) ||
      (post_rank != 0 && (pre_next_rsp_data[41:32] <= previous_root ||
                         descriptor_tag_delta <= {23'b0,previous_pre_rank}));
    unexpected_next_response = post_reserved && pre_next_rsp_valid && next_owner == NextNone;
    unexpected_vector_response = post_reserved && vector_rsp_valid &&
      (!vector_pending || vector_owner != VectorPost);
    row_status_good = writer_done_valid && feature_done_valid &&
      !writer_done_error && !feature_done_error &&
      writer_done_tag == saved_post_tag_base + 32'(post_rank) &&
      feature_done_tag == writer_done_tag && writer_done_layer == saved_layer &&
      feature_done_layer == saved_layer && writer_done_epoch == saved_epoch &&
      feature_done_epoch == saved_epoch && writer_done_root == post_root &&
      feature_done_root == post_root && writer_done_input_rank == post_rank &&
      feature_done_input_rank == post_rank && writer_done_kept_rank == post_rank &&
      feature_done_kept_rank == post_rank && writer_done_exponent == feature_done_exponent &&
      writer_accepted_strips == 256 && writer_acknowledged_lines == 32 &&
      writer_descriptor_acknowledged && feature_accepted_strips == 256 &&
      feature_acknowledged_lines == 12;
    row_status_bad = (writer_done_valid && writer_done_error) ||
      (feature_done_valid && feature_done_error) ||
      (writer_done_valid && feature_done_valid && !row_status_good) ||
      (phase == RowAcknowledge && writer_idle && feature_idle && source_row_quiet &&
       (src_accepted_rows != post_rank + 10'd1 || src_completed_rows != post_rank + 10'd1));
    post_fault_now = next_c_fault_latched || next_c_fault_now ||
      (post_reserved && (abort_valid || pre_epoch_fault ||
      !store_context_owned || src_row_source_error || writer_epoch_fault || feature_epoch_fault ||
      row_status_bad || next_quarantined || vector_quarantined ||
      unexpected_next_response || unexpected_vector_response)) ||
      (post_cfg_fire && post_configuration_bad) ||
      (next_response_fire && next_owner == NextDescriptor && descriptor_bad) ||
      (phase == WaitPostQuiet && post_retired_seen &&
       (src_accepted_rows != saved_kept_rows || src_completed_rows != saved_kept_rows));

    // All three row clients accept on one edge. Ready predicates are genuine,
    // independent of these internal valid pulses; no fake ready/cancellation.
    row_admit = rst_n && phase == RowAdmit && !post_fault_latched && !post_fault_now &&
      src_row_request_ready && writer_cfg_ready && feature_cfg_ready;
    writer_cfg_valid = row_admit;
    feature_cfg_valid = row_admit;
    writer_abort = post_reserved && (abort_valid || post_fault_latched);

    // Phase routing never drops an exposed C tuple or its memory bus.
    src_abort_valid = post_reserved ? (abort_valid || post_fault_latched) : pre_c_abort_valid;
    src_cfg_valid = post_reserved ?
      (phase == ConfigurePost && src_cfg_ready && !post_fault_latched && !post_fault_now) :
      pre_c_cfg_valid;
    pre_c_cfg_ready = !post_reserved && src_cfg_ready;
    src_cfg_new_image = post_reserved ? 1'b0 : pre_c_cfg_new_image;
    src_cfg_tag_base = post_reserved ? saved_post_tag_base : pre_c_cfg_tag_base;
    src_cfg_layer = post_reserved ? saved_layer : pre_c_cfg_layer;
    src_cfg_epoch = post_reserved ? saved_epoch : pre_c_cfg_epoch;
    src_cfg_image_start = post_reserved ? saved_image_start : pre_c_cfg_image_start;
    src_cfg_input_rows = post_reserved ? saved_kept_rows : pre_c_cfg_input_rows;
    src_cfg_raw_frame_base = post_reserved ? saved_raw_base : pre_c_cfg_raw_frame_base;
    src_cfg_raw_frame_bytes = post_reserved ? saved_raw_bytes : pre_c_cfg_raw_frame_bytes;
    src_cfg_metadata_base = post_reserved ? saved_metadata_base : pre_c_cfg_metadata_base;
    src_cfg_metadata_bytes = post_reserved ? saved_metadata_bytes : pre_c_cfg_metadata_bytes;
    src_cfg_gamma_base = post_reserved ? saved_gamma_base : pre_c_cfg_gamma_base;
    src_cfg_gamma_bytes = post_reserved ? saved_gamma_bytes : pre_c_cfg_gamma_bytes;
    src_cfg_gamma_exponent = post_reserved ? saved_gamma_exponent : pre_c_cfg_gamma_exponent;
    src_row_request_valid = row_admit;
    if (!post_reserved) src_row_request_valid = pre_c_row_request_valid;
    pre_c_row_request_ready = !post_reserved && src_row_request_ready;
    src_row_request_original_root = post_reserved ? post_root : pre_c_row_request_original_root;
    src_row_request_input_rank = post_reserved ? post_rank : pre_c_row_request_input_rank;
    src_row_request_tag = post_reserved ? saved_post_tag_base + 32'(post_rank) : pre_c_row_request_tag;
    src_row_request_layer = post_reserved ? saved_layer : pre_c_row_request_layer;
    src_row_request_epoch = post_reserved ? saved_epoch : pre_c_row_request_epoch;
    src_out_ready = post_reserved ? writer_in_ready : pre_c_out_ready;
    pre_c_out_valid = !post_reserved && src_out_valid;
    pre_c_out_last = src_out_last;
    pre_c_out_error = src_out_error;
    pre_c_out_tag = src_out_tag;
    pre_c_out_index = src_out_index;
    pre_c_out_count = src_out_count;
    pre_c_out_activation = src_out_activation;
    pre_c_out_exponent = src_out_exponent;
    pre_c_out_outlier_mask = src_out_outlier_mask;
    pre_c_out_outlier_negative = src_out_outlier_negative;
    pre_c_out_normalized_negative = src_out_normalized_negative;
    src_retire_valid = post_reserved ?
      (phase == RetirePost && src_retire_ready && !post_fault_latched && !post_fault_now) :
      pre_c_retire_valid;
    pre_c_retire_ready = !post_reserved && src_retire_ready;
    pre_c_row_source_error = post_reserved ? pre_source_error : src_row_source_error;
    pre_c_producer_idle = post_reserved ? post_restore_quiet : src_producer_idle;
    pre_c_port_idle = post_reserved ? post_restore_quiet : src_port_idle;
    pre_c_idle = post_reserved ? post_restore_quiet : src_idle;
    pre_c_accepted_rows = post_reserved ? pre_source_accepted : src_accepted_rows;
    pre_c_completed_rows = post_reserved ? pre_source_completed : src_completed_rows;
    pre_c_read_req_valid = read_req_valid;
    pre_c_read_rsp_valid = read_rsp_valid;

    // A registered owner, never the caller's current selected bit, owns C.
    // Existing PRE shadow observations above remain untouched. Offered source
    // tuples stay connected through a late fault; only fresh captures stop.
    if (next_c_granted) begin
      pre_c_cfg_ready = 1'b0;
      pre_c_row_request_ready = 1'b0;
      pre_c_out_valid = 1'b0;
      pre_c_retire_ready = 1'b0;
      pre_c_row_source_error = pre_source_error;
      pre_c_producer_idle = post_restore_quiet;
      pre_c_port_idle = post_restore_quiet;
      pre_c_idle = post_restore_quiet;
      pre_c_accepted_rows = pre_source_accepted;
      pre_c_completed_rows = pre_source_completed;
      src_abort_valid = (abort_valid === 1'b1) || post_fault_latched ||
        next_c_fault_latched || (next_c_request.abort_valid === 1'b1);
      src_cfg_valid = next_c_cfg_offer;
      src_cfg_new_image = next_c_held_cfg.cfg_new_image;
      src_cfg_tag_base = next_c_held_cfg.cfg_tag_base;
      src_cfg_layer = next_c_held_cfg.cfg_layer;
      src_cfg_epoch = next_c_held_cfg.cfg_epoch;
      src_cfg_image_start = next_c_held_cfg.cfg_image_start;
      src_cfg_input_rows = next_c_held_cfg.cfg_input_rows;
      src_cfg_raw_frame_base = next_c_held_cfg.cfg_raw_frame_base;
      src_cfg_raw_frame_bytes = next_c_held_cfg.cfg_raw_frame_bytes;
      src_cfg_metadata_base = next_c_held_cfg.cfg_metadata_base;
      src_cfg_metadata_bytes = next_c_held_cfg.cfg_metadata_bytes;
      src_cfg_gamma_base = next_c_held_cfg.cfg_gamma_base;
      src_cfg_gamma_bytes = next_c_held_cfg.cfg_gamma_bytes;
      src_cfg_gamma_exponent = next_c_held_cfg.cfg_gamma_exponent;
      src_row_request_valid = next_c_row_offer;
      src_row_request_original_root = next_c_held_row.row_request_original_root;
      src_row_request_input_rank = next_c_held_row.row_request_input_rank;
      src_row_request_tag = next_c_held_row.row_request_tag;
      src_row_request_layer = next_c_held_row.row_request_layer;
      src_row_request_epoch = next_c_held_row.row_request_epoch;
      src_out_ready = (next_c_request.out_ready === 1'b1);
      src_retire_valid = next_c_retire_offer;
    end

    // Once POST reserves NextOwner, external descriptor/Size clients wait.
    // The actual selected owner's response remains connected through faults.
    pre_next_size_request = '0;
    next_size_response = '0;
    next_size_out_origin = 0;
    if (external_next_enabled) begin
      // Retain prior Walk/Emit and an already sampled held query even on
      // late global fault; fence only creation of a fresh query.
      pre_next_size_request = next_size_request;
      pre_next_size_request.query_valid = next_size_request.query_valid &&
        (!post_epoch_fault || external_size_offer);
      next_size_response = pre_next_size_response;
      next_size_response.query_ready = pre_next_size_response.query_ready &&
        (!post_epoch_fault || external_size_offer);
      next_size_out_origin = pre_next_size_out_origin;
    end
    selected_next_descriptor = post_reserved && desc_offered;
    selected_next_writer = post_reserved && !desc_offered && writer_next_req_valid;
    pre_next_req_valid = 0;
    pre_next_req_write = 0;
    pre_next_req_word = 0;
    pre_next_req_data = 0;
    next_req_ready = 0;
    writer_next_req_ready = 0;
    if (selected_next_descriptor) begin
      pre_next_req_valid = 1;
      pre_next_req_word = 10'd256 + post_rank;
    end else if (selected_next_writer) begin
      pre_next_req_valid = writer_next_req_valid;
      pre_next_req_write = writer_next_req_write;
      pre_next_req_word = writer_next_req_word;
      pre_next_req_data = writer_next_req_data;
      writer_next_req_ready = pre_next_req_ready;
    end else if (external_next_enabled && (!post_epoch_fault || external_offer) &&
                 (next_owner == NextNone || external_offer)) begin
      pre_next_req_valid = next_req_valid;
      pre_next_req_write = next_req_write;
      pre_next_req_word = next_req_word;
      pre_next_req_data = next_req_data;
      next_req_ready = pre_next_req_ready;
    end
    next_rsp_valid = pre_next_rsp_valid && next_owner == NextExternal && !next_quarantined;
    next_rsp_error = pre_next_rsp_error;
    next_rsp_data = pre_next_rsp_data;
    writer_next_rsp_valid = pre_next_rsp_valid && next_owner == NextWriter && !next_quarantined;
    pre_next_rsp_ready = 0;
    case (next_owner)
      NextExternal: pre_next_rsp_ready = next_rsp_ready;
      NextDescriptor: pre_next_rsp_ready = !next_quarantined;
      NextWriter: pre_next_rsp_ready = writer_next_rsp_ready;
      default: begin end
    endcase

    if (next_quarantined) pre_next_rsp_ready = 0;

    // Lock selection from the first sampled offer through its actual ACK.
    selected_vector_post = vector_owner == VectorPost ||
      (vector_owner == VectorNone && post_reserved);
    vector_req_valid = !vector_pending &&
      (selected_vector_post ? writer_vector_req_valid : pre_vector_req_valid);
    vector_req_address = selected_vector_post ? writer_vector_req_address : pre_vector_req_address;
    vector_req_data = selected_vector_post ? writer_vector_req_data : pre_vector_req_data;
    writer_vector_req_ready = selected_vector_post && !vector_pending && vector_req_ready;
    pre_vector_req_ready = !selected_vector_post && !vector_pending && vector_req_ready;
    // PRE must retain its original unassociated-response fault detection.
    // POST ACK is NEVER returned to the retired PRE logical child.
    pre_vector_rsp_valid = vector_rsp_valid && (!post_reserved || vector_owner == VectorPre);
    writer_vector_rsp_valid = vector_rsp_valid && vector_owner == VectorPost && vector_pending &&
      !vector_quarantined;
    vector_rsp_ready = selected_vector_post ? writer_vector_rsp_ready : pre_vector_rsp_ready;
    if (post_reserved && vector_quarantined) vector_rsp_ready = 0;
    writer_done_ready = post_reserved && ((phase == RowWait && row_status_good &&
      source_row_quiet && src_accepted_rows == post_rank + 10'd1 &&
      src_completed_rows == post_rank + 10'd1 && next_owner == NextNone &&
      !pre_next_rsp_valid && vector_owner == VectorNone && !vector_pending &&
      !vector_rsp_valid && feature_port_idle && !feature_rsp_valid &&
      !post_epoch_fault) || post_fault_latched);
    feature_done_ready = writer_done_ready;
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      phase <= PreRun;
      next_owner <= NextNone;
      vector_owner <= VectorNone;
      vector_pending <= 0;
      next_quarantined <= 0;
      vector_quarantined <= 0;
      pre_success_seen <= 0;
      pre_retired_seen <= 0;
      post_retired_seen <= 0;
      post_reserved <= 0;
      post_handoff_seen <= 0;
      external_offer <= 0;
      external_size_offer <= 0;
      post_fault_latched <= 0;
      post_done_valid <= 0;
      pre_source_accepted <= 0;
      pre_source_completed <= 0;
      pre_source_error <= 0;
      saved_pre_new_image <= 0;
      previous_pre_rank <= 0;
      saved_pre_tag_base <= 0;
      saved_post_tag_base <= 0;
      saved_layer <= 0;
      saved_epoch <= 0;
      saved_image_start <= 0;
      saved_pre_input_rows <= 0;
      saved_kept_rows <= 0;
      saved_code_base <= 0;
      saved_raw_base <= 0;
      saved_raw_bytes <= 0;
      saved_metadata_base <= 0;
      saved_metadata_bytes <= 0;
      saved_gamma_base <= 0;
      saved_gamma_bytes <= 0;
      saved_feature_base <= 0;
      saved_feature_bytes <= 0;
      saved_gamma_exponent <= 0;
      saved_bundle_id <= 0;
      saved_immutable_base <= 0;
      saved_immutable_bytes <= 0;
      saved_code_bytes <= 0;
      post_rank <= 0;
      post_root <= 0;
      previous_root <= 0;
      desc_offered <= 0;
    end else begin
      if (cfg_valid && cfg_ready) begin
        pre_success_seen <= 0;
        pre_retired_seen <= 0;
        saved_pre_tag_base <= cfg_tag_base;
        saved_pre_new_image <= cfg_new_image;
        saved_layer <= cfg_layer;
        saved_epoch <= cfg_epoch;
        saved_image_start <= cfg_image_start;
        saved_pre_input_rows <= cfg_input_rows;
        saved_code_base <= cfg_compact_output_base;
      end
      if (!post_reserved && src_retire_valid && src_retire_ready) begin
        pre_retired_seen <= 1;
        pre_source_accepted <= src_accepted_rows;
        pre_source_completed <= src_completed_rows;
        pre_source_error <= src_row_source_error;
      end
      if (done_valid && done_ready && !done_error && !epoch_fault) begin
        pre_success_seen <= 1;
        saved_kept_rows <= done_kept_count;
      end

      // An external held offer also cannot disappear merely because the
      // phase owner reports a late fault after POST handoff.
      if (external_next_enabled && next_owner == NextNone && next_req_valid &&
          !post_epoch_fault && !next_req_ready) external_offer <= 1;
      if (next_request_fire && !selected_next_descriptor && !selected_next_writer)
        external_offer <= 0;
      if (external_next_enabled && next_size_request.query_valid &&
          !post_epoch_fault && !next_size_response.query_ready) external_size_offer <= 1;
      if (external_next_enabled && next_size_request.query_valid && next_size_response.query_ready)
        external_size_offer <= 0;
      if (vector_owner == VectorNone && vector_req_valid)
        vector_owner <= selected_vector_post ? VectorPost : VectorPre;
      if (vector_request_fire) vector_pending <= 1;
      if (vector_response_fire) begin
        vector_pending <= 0;
        vector_owner <= VectorNone;
      end
      if (next_request_fire) begin
        if (selected_next_descriptor) next_owner <= NextDescriptor;
        else if (selected_next_writer) next_owner <= NextWriter;
        else next_owner <= NextExternal;
      end
      if (next_response_fire) next_owner <= NextNone;
      if (unexpected_next_response) next_quarantined <= 1;
      if (unexpected_vector_response) vector_quarantined <= 1;
      if (next_request_fire && selected_next_descriptor) desc_offered <= 0;

      if (post_fault_now) post_fault_latched <= 1;
      if (post_done_valid && post_done_ready) post_done_valid <= 0;

      case (phase)
        PreRun: if (post_cfg_fire) begin
          post_reserved <= 1;
          post_retired_seen <= 0;
          saved_post_tag_base <= post_cfg_tag_base;
          saved_raw_base <= post_cfg_raw_frame_base;
          saved_raw_bytes <= post_cfg_raw_frame_bytes;
          saved_metadata_base <= post_cfg_metadata_base;
          saved_metadata_bytes <= post_cfg_metadata_bytes;
          saved_gamma_base <= post_cfg_gamma_base;
          saved_gamma_bytes <= post_cfg_gamma_bytes;
          saved_feature_base <= post_cfg_feature_base;
          saved_feature_bytes <= post_cfg_feature_bytes;
          saved_gamma_exponent <= post_cfg_gamma_exponent;
          saved_bundle_id <= post_cfg_bundle_id;
          saved_immutable_base <= post_envelope_base;
          saved_immutable_bytes <= post_envelope_span[63:0];
          saved_code_bytes <= post_code_bytes[63:0];
          post_rank <= 0;
          post_root <= 0;
          previous_root <= 0;
          phase <= post_configuration_bad ? FaultLock : ConfigurePost;
        end
        ConfigurePost: if (src_cfg_valid && src_cfg_ready) begin
          desc_offered <= 1;
          phase <= DescriptorOffer;
        end
        DescriptorOffer: if (next_request_fire && selected_next_descriptor) phase <= DescriptorWait;
        DescriptorWait: if (next_response_fire && next_owner == NextDescriptor) begin
          if (!descriptor_bad) begin
            post_root <= pre_next_rsp_data[41:32];
            previous_pre_rank <= descriptor_tag_delta[9:0];
            phase <= RowAdmit;
          end
        end
        RowAdmit: if (row_admit) phase <= RowWait;
        RowWait: if (writer_done_valid && writer_done_ready &&
                    feature_done_valid && feature_done_ready) phase <= RowAcknowledge;
        RowAcknowledge: if (writer_idle && feature_idle && source_row_quiet &&
            src_accepted_rows == post_rank + 10'd1 && src_completed_rows == post_rank + 10'd1) begin
          if (post_rank + 10'd1 == saved_kept_rows) phase <= RetirePost;
          else begin
            previous_root <= post_root;
            post_rank <= post_rank + 1'b1;
            desc_offered <= 1;
            phase <= DescriptorOffer;
          end
        end
        RetirePost: if (src_retire_valid && src_retire_ready) begin
          post_retired_seen <= 1;
          phase <= WaitPostQuiet;
        end
        WaitPostQuiet: if (post_retired_seen && post_source_quiet && writer_idle && feature_idle &&
            next_owner == NextNone && !desc_offered && !pre_next_req_valid && !pre_next_rsp_valid &&
            vector_owner == VectorNone && !vector_pending && !vector_req_valid && !vector_rsp_valid &&
            feature_port_idle && !feature_req_valid && !feature_data_valid && !feature_rsp_valid &&
            !post_fault_latched && !post_fault_now) begin
          post_done_valid <= 1;
          phase <= PostHeld;
        end
        PostHeld: if (post_done_valid && post_done_ready) begin
          if (!post_epoch_fault) post_handoff_seen <= 1;
          phase <= PostNext;
        end
        PostNext: if (store_release_valid && store_release_ready) begin
          post_reserved <= 0;
          post_handoff_seen <= 0;
          pre_success_seen <= 0;
          pre_retired_seen <= 0;
          post_retired_seen <= 0;
          phase <= PreRun;
        end
        FaultLock: begin
          // Never cancel known offers or forge a drained error completion.
          // The selected clients keep draining; reset is the recovery boundary.
        end
        default: begin post_fault_latched <= 1; phase <= FaultLock; end
      endcase
      // Fault wins new admission/advance/ACK. An existing public slot is only
      // removed by its genuine ACK, retaining all tuple bits through late fault.
      if (post_reserved && (post_fault_latched || post_fault_now)) phase <= FaultLock;
    end
  end
endmodule
