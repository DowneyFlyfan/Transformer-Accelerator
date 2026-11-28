`timescale 1ns/1ps
// Draft source-only interfaces; no candidate/runtime acceptance is implied.
package tri_oracle_FF_frame_types_v2;
  // common supplies the already-held source/target publication context, scalar
  // trained-weight policy, gamma table and protected extents. Its row-varying
  // legacy fields are not used as a substitute for an actual row descriptor.
  typedef struct packed {
    raw32_residual_commit_types_v1::job_t common;
    logic [9:0] upstream_input_count;
    logic [63:0] post_code_base,post_feature_base,post_feature_bytes;
    logic [63:0] gate_base,up_base,down_base;
    logic [63:0] gate_sign_base,gate_sign_bytes,up_sign_base,up_sign_bytes;
    logic [63:0] row_units_base,row_units_bytes;
    logic [63:0] intermediate_base,intermediate_bytes;
  } frame_t;
  typedef struct packed {
    logic [31:0] source_tag;
    logic [9:0] original_root,upstream_input_rank,raw_input_rank,frame_rank;
    logic signed [8:0] activation_unit;
  } row_t;
  typedef struct packed {
    logic [31:0] tag;
    logic [9:0] start_rank;
    logic [4:0] tokens;
    row_t [15:0] rows;
  } batch_t;
  typedef struct packed {
    logic row_enable,correction_enable;
    logic [31:0] tag;
    logic [4:0] tokens;
    logic [15:0] input_features,intermediate_features;
    logic [16:0] output_features;
    logic [63:0] activation_base,gate_base,up_base,down_base;
    logic [63:0] intermediate_base,row_units_base;
    logic [31:0] activation_stride;
    logic [95:0] gate_shifts,up_shifts,down_shifts;
  } native_cfg_t;
endpackage
