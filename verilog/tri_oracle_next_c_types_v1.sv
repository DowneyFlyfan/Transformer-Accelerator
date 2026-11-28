`timescale 1ns/1ps
// Draft additive application programming interface for a third logical C client.
// selected requests bus selection; it is NOT a physical owner or lease grant.
// Owner/descriptor authority must come from the retained real POST handoff.
package tri_oracle_next_c_types_v1;
  typedef struct packed {
    logic selected;
    logic abort_valid;
    logic cfg_valid;
    logic cfg_new_image;
    logic [31:0] cfg_tag_base;
    logic [4:0] cfg_layer;
    logic [15:0] cfg_epoch;
    logic [9:0] cfg_image_start;
    logic [9:0] cfg_input_rows;
    logic [63:0] cfg_raw_frame_base;
    logic [63:0] cfg_raw_frame_bytes;
    logic [63:0] cfg_metadata_base;
    logic [63:0] cfg_metadata_bytes;
    logic [63:0] cfg_gamma_base;
    logic [63:0] cfg_gamma_bytes;
    logic signed [7:0] cfg_gamma_exponent;
    logic row_request_valid;
    logic [9:0] row_request_original_root;
    logic [9:0] row_request_input_rank;
    logic [31:0] row_request_tag;
    logic [4:0] row_request_layer;
    logic [15:0] row_request_epoch;
    logic out_ready;
    logic retire_valid;
  } request_t;
  typedef struct packed {
    logic cfg_ready;
    logic row_request_ready;
    logic out_valid;
    logic out_last;
    logic out_error;
    logic [31:0] out_tag;
    logic [9:0] out_index;
    logic [3:0] out_count;
    logic [63:0] out_activation;
    logic signed [8:0] out_exponent;
    logic [7:0] out_outlier_mask;
    logic [7:0] out_outlier_negative;
    logic [7:0] out_normalized_negative;
    logic retire_ready;
    logic row_source_error;
    logic producer_idle;
    logic port_idle;
    logic idle;
    logic [9:0] accepted_rows;
    logic [9:0] completed_rows;
    logic read_request_valid;
    logic read_response_valid;
  } response_t;
  localparam int unsigned REQUEST_BITS = $bits(request_t);
  localparam int unsigned RESPONSE_BITS = $bits(response_t);
endpackage
