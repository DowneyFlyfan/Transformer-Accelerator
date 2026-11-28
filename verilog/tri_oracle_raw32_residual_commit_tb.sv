`timescale 1ns/1ps
// One trained feed-forward row, residual publication, and native normalization.
// Replayed inputs retain the parent owner for the remaining 263 rows.
// Expected tensors are scoreboards; live attention and full-model execution
// require separate integration checks.
package full_ff_counts;
  integer cells[0:8] = '{default:0};
  integer next_uid = 0;
  integer strip_accepts[0:19] = '{default:0};
  integer strip_results[0:19] = '{default:0};
  integer pe_uid = 0;
  integer pe_accepts[0:19] = '{default:0};
  integer pe_results[0:19] = '{default:0};
endpackage
module full_ff_cell_marker #(parameter integer ROLE=0) ();
  initial full_ff_counts::cells[ROLE] = full_ff_counts::cells[ROLE]+1;
endmodule
module full_ff_pe_marker(input logic clk,rst_n,in_valid,in_ready,out_valid,out_ready);
  integer uid;
  initial begin
    uid=full_ff_counts::pe_uid;full_ff_counts::pe_uid=uid+1;
    if(uid>=20)$fatal(1,"FULL_FF_TOO_MANY_PHYSICAL_PE_WITNESSES");
  end
  always @(posedge clk or negedge rst_n)begin
    if(!rst_n)begin full_ff_counts::pe_accepts[uid]<=0;full_ff_counts::pe_results[uid]<=0;end
    else begin
      if(in_valid && in_ready)full_ff_counts::pe_accepts[uid]<=full_ff_counts::pe_accepts[uid]+1;
      if(out_valid && out_ready)full_ff_counts::pe_results[uid]<=full_ff_counts::pe_results[uid]+1;
    end
  end
endmodule
module full_ff_strip_marker(input logic clk,rst_n,input logic [146:0] request,input logic [39:0] response);
  integer uid;
  initial begin
    uid=full_ff_counts::next_uid;full_ff_counts::next_uid=uid+1;
    if(uid>=20)$fatal(1,"FULL_FF_TOO_MANY_PHYSICAL_CORE_WITNESSES");
  end
  always @(posedge clk or negedge rst_n) begin
    if(!rst_n)begin full_ff_counts::strip_accepts[uid]<=0;full_ff_counts::strip_results[uid]<=0;end
    else begin
      if(request[146] && response[39])full_ff_counts::strip_accepts[uid]<=full_ff_counts::strip_accepts[uid]+1;
      if(response[38] && request[144])begin
        if(response[37])$fatal(1,"FULL_FF_PHYSICAL_PREDICTOR_ERROR");
        full_ff_counts::strip_results[uid]<=full_ff_counts::strip_results[uid]+1;
      end
    end
  end
endmodule

module tri_oracle_raw32_residual_commit_tb;
  import raw32_residual_commit_types_v1::*;
  // All addresses are disjoint logical reservations. Only acknowledged bytes
  // become readable. Reserving 264 rows does not publish the remaining rows.
  localparam logic [63:0] OLD_RAW=64'h80000000,OLD_META=64'h81000000,DOWN_SCRATCH=64'h82000000;
  localparam logic [63:0] TARGET_RAW=64'h83000000,TARGET_META=64'h84000000,PRE1_GAMMA=64'h85003000;
  localparam logic [63:0] RAW_EXTENT=64'd2203648,META_EXTENT=64'd4224;
  localparam logic [31:0] TARGET_TAG=32'h50520000;
  job_t seam_job;
  logic seam_cfg_valid,seam_cfg_ready,seam_launch,seam_active,seam_fault,seam_packet;
  logic seam_req,seam_req_ready,seam_rsp,seam_rsp_ready,seam_last,seam_error;
  logic [63:0] seam_address,seam_data;logic[4:0]seam_length;
  logic seam_wr_req,seam_wr_ready,seam_wr_valid,seam_wr_data_ready,seam_wr_last,seam_wr_rsp,seam_wr_rsp_ready,seam_wr_error;
  logic [63:0]seam_wr_address,seam_wr_data;logic[4:0]seam_wr_length;logic[7:0]seam_wr_strobe;
  logic seam_c_selected,seam_c_cfg,seam_c_demand,seam_c_retire,seam_done,seam_done_error;
  logic[7:0] seam_table_words;logic[1:0]seam_metadata_words;logic[5119:0]seam_held_packet,first_down_observed;
  logic seam_in_ready,commit_write_selected,aux_phase_busy,held_aux_phase;
  logic c_cfg_ready,c_demand_ready,c_retire_ready,c_fault,c_producer_idle,c_port_idle,c_idle;
  logic c_valid,c_last,c_error,c_ready,c_req,c_req_ready,c_rsp,c_rsp_ready,c_rsp_last,c_rsp_error;
  logic[31:0]c_tag;logic[9:0]c_index,c_accepted,c_completed;logic[3:0]c_count;
  logic[63:0]c_activation,c_req_address,c_rsp_data;logic[4:0]c_req_length;
  logic signed[8:0]c_exponent;logic[7:0]c_outlier,c_outlier_negative,c_normalized_negative;
  logic[1:0]aux_req,aux_ready,aux_rsp,aux_rsp_ready,aux_last,aux_error;
  logic[1:0][63:0]aux_address,aux_data;logic[1:0][4:0]aux_length;
  logic aux_mem_req,aux_mem_ready,aux_mem_rsp,aux_mem_rsp_ready,aux_mem_last,aux_mem_error;
  logic[63:0]aux_mem_address,aux_mem_data;logic[4:0]aux_mem_length;
  logic native_mem_req,native_mem_ready,native_mem_rsp,native_mem_rsp_ready,native_mem_last,native_mem_error;
  logic[63:0]native_mem_address,native_mem_data;logic[4:0]native_mem_length;
  logic[1:0]outer_req,outer_ready,outer_rsp,outer_rsp_ready,outer_last,outer_error;
  logic[1:0][63:0]outer_address,outer_data;logic[1:0][4:0]outer_length;
  logic bus_wr_req,bus_wr_ready,bus_wr_valid,bus_wr_data_ready,bus_wr_last,bus_wr_rsp,bus_wr_rsp_ready;
  logic[63:0]bus_wr_address,bus_wr_data;logic[4:0]bus_wr_length;logic[7:0]bus_wr_strobe;
  integer commit_write_requests,commit_write_responses,commit_write_bytes,progress_wait,c_strips,c_cfg_fires,c_demand_fires,c_retire_fires;
  byte unsigned original_raw[],original_metadata[],pre1_gamma[];
  byte unsigned down_scratch[0:8191],target_raw[0:2203647],target_metadata[0:4223];
  bit down_committed[0:8191],target_raw_committed[0:2203647],target_meta_committed[0:4223];
  job_t seam_held_job;
  logic seam_native_drained,seam_metadata_ack;
  logic signed[7:0] seam_selected_unit;
  logic[63:0] seam_selected_epsilon;
  logic[8:0] seam_scratch_acks,seam_raw_acks;
  logic[31:0] seam_done_tag;
  integer scratch_write_requests,scratch_write_responses,raw_write_requests,raw_write_responses;
  integer metadata_write_requests,metadata_write_responses,metadata_ack_delay_cycles;
  integer commit_request_stalls,commit_data_stalls,held_done_cycles;
  logic seam_write_req_held,seam_write_data_held;
  logic[68:0] seam_saved_write_request;
  logic[72:0] seam_saved_write_data;
  logic[31:0] observed_down[0:2047];
  bit observed_down_present[0:2047];
  string seam_input_root;

  localparam logic [63:0] GATE_SIG=64'h50000000,UP_SIG=64'h60000000;
  localparam logic [63:0] GATE_W=64'h70000000,UP_W=64'h71000000,DOWN_W=64'h72000000;
  localparam logic [63:0] ROW_UNITS=64'h73000000,SCRATCH=64'h74000000,DOWN_SCALE=64'h75000000;
  logic clk,rst_n,abort_valid,next_context_owned,strip_fabric_owned,top_fault;
  logic a_cfg_valid,a_cfg_ready,a_done,a_done_ready,a_error,a_fault,a_active,a_idle;
  logic next_req,next_write,next_ready,next_rsp,next_rsp_ready,next_rsp_error,next_release,next_release_ready;
  logic [9:0] next_word;
  logic [63:0] next_data,next_rsp_data;
  logic next_owned;
  logic [63:0] descriptor[0:0],context_words[0:25];
  logic frame_offer,frame_offer_ready,frame_cfg_valid,frame_cfg_ready;
  logic frame_row_enable,frame_correction_enable;
  logic [31:0] frame_tag,frame_stride;
  logic [4:0] frame_tokens;
  logic [15:0] frame_h,frame_k;
  logic [16:0] frame_o;
  logic [63:0] frame_activation,frame_gate,frame_up,frame_down,frame_scratch,frame_units;
  logic [95:0] frame_gate_shifts,frame_up_shifts,frame_down_shifts;
  logic frame_done,frame_done_ready,frame_done_error,frame_out_drained;
  logic [31:0] frame_done_tag;
  logic row_context;
  logic [31:0] row_tag;
  logic [4:0] row_layer;
  logic [15:0] row_epoch;
  logic [9:0] row_root,row_input,row_kept;
  logic signed [8:0] row_ea,row_ed;
  logic signed [10:0] row_gain;
  logic [5:0] row_down_shift;
  logic signed [11:0] row_output_exp;
  logic [63:0] row_down_table;
  logic [127:0] row_bundle;
  logic legacy_writer;
  logic pred_cfg_valid,pred_cfg_ready,pred_done,pred_done_ready,pred_error,pred_fault,pred_active,pred_idle,pred_port_idle,strip_quiet;
  logic [31:0] pred_done_tag;
  logic [4:0] pred_done_layer;
  logic [15:0] pred_done_epoch;
  logic [9:0] pred_done_root,pred_done_input,pred_done_kept;
  logic signed [8:0] pred_done_exp;
  logic [127:0] pred_done_bundle;
  logic [7:0] pred_groups;
  logic [15:0] pred_strips;
  logic [6:0] pred_masks;
  logic pred_done_seen;
  logic mask_valid,mask_ready,mask_last,frame_mask_valid,frame_mask_ready;
  logic [31:0] mask_tag;
  logic [15:0] mask_start;
  logic [6:0] mask_count;
  logic [1279:0] mask_bits;
  logic [533:0] strip_request;
  logic [111:0] strip_response;
  logic [1:0] client_req_valid,client_req_ready,client_rsp_valid,client_rsp_ready,client_rsp_last,client_rsp_error;
  logic [1:0][63:0] client_req_address,client_rsp_data;
  logic [1:0][4:0] client_req_length;
  logic mem_req,mem_ready,mem_rsp,mem_rsp_ready,mem_last,mem_error,read_owned;
  logic [63:0] mem_address,mem_data,read_address;
  logic [4:0] mem_length,read_length;
  integer read_beat,read_delay;
  logic wr_req,wr_ready,wr_data_valid,wr_data_ready,wr_last,wr_rsp,wr_rsp_ready,wr_error,write_owned,write_all;
  logic [63:0] wr_address,wr_data,write_address;
  logic [4:0] wr_length,write_length;
  logic [7:0] wr_strobe;
  integer write_beat,write_delay;
  byte unsigned write_packet[0:79];
  logic ff_valid,ff_ready,ff_last;
  logic [31:0] ff_tag;
  logic [3:0] ff_token;
  logic [15:0] ff_start;
  logic [7:0] ff_count;
  logic [5119:0] ff_data;
  tri_oracle_fabric_owner_types::request_t backend_request;
  tri_oracle_fabric_owner_types::response_t backend_response;
  tri_oracle_wac_softmax_types::request_t softmax_idle;
  tri_oracle_wac_softmax_types::response_t softmax_reply;
  tri_oracle_token_size_types::request_t token_idle;
  tri_oracle_token_size_types::response_t token_reply;
  tri_oracle_merge_range_types::request_t merge_idle;
  tri_oracle_merge_range_types::response_t merge_reply;
  tri_oracle_attention_tensor437 attention();
  logic [119:0] unused_sign_counts;
  logic [79:0] unused_merge_word;
  logic [72:0] unused_head_reply;
  byte unsigned codes[],features[];
  byte unsigned gate_signs[],up_signs[];
  byte unsigned gate_weights[],up_weights[],down_weights[];
  byte unsigned scratch[0:5631];
  byte unsigned row_units[],down_scales[];
  bit scratch_committed[0:5631];
  // These expected buffers are read ONLY in scoreboard checks, never provider.
  byte unsigned expected_raw_bytes[],expected_down_input[];
  logic [1279:0] expected_keep[0:70];
  // CHECK_ONLY: compare arithmetic even when odd outlier count makes all KEEP bits one.
  logic [111:0] expected_groups[0:175];
  logic group_live;
  logic [2:0] group_cluster;
  integer group_inputs,group_results;
  string fixture_root,weight_root,golden_root,config_path;
  integer fd,loaded,extra,cycles,limit,mode,mask_fires,raw_packets,raw_values;
  integer write_requests,write_responses,write_bytes,read_requests,read_responses;
  integer adapter_cfg_fires,descriptor_requests,descriptor_responses,frame_cfg_fires,pred_hold;
  integer mask_stalls,output_stalls,read_stalls,write_stalls;
  logic [2:0] first_raw_stall_count;
  logic [2:0] first_read_stall_count;
  integer backend_commands,backend_loads;
  logic req_held,rsp_held,wr_req_held,wr_data_held,mask_held,out_held,a_done_held;
  logic [68:0] held_req,held_wr_req;
  logic [65:0] held_rsp;
  logic [72:0] held_wr_data;
  logic held_a_error;
  typedef struct packed {logic last;logic[31:0]tag;logic[15:0]start;logic[6:0]count;logic[1279:0]bits;} mask_packet_t;
  typedef struct packed {logic[31:0]tag;logic[3:0]token;logic[15:0]start;logic[7:0]count;logic last;logic[5119:0]data;} raw_packet_t;
  mask_packet_t held_mask;
  raw_packet_t held_output;

  initial clk=0;
  always #5 clk=~clk;
  assign softmax_idle='0;assign token_idle='0;assign merge_idle='0;
  assign {attention.cfg_valid,attention.cfg_tag,attention.cfg_activation_stride,attention.cfg_tokens,
    attention.cfg_feature_words,attention.cfg_dense_rows,attention.cfg_count,attention.cfg_channels,attention.cfg_keep,
    attention.cfg_activation_base,attention.cfg_weight_base,attention.out_ready,attention.done_ready}='0;
  // One atomic actual descriptor-derived admission to prediction and compute.
  assign frame_cfg_valid=frame_offer && pred_cfg_ready;
  assign pred_cfg_valid=frame_offer && frame_cfg_ready;
  assign frame_offer_ready=frame_cfg_ready && pred_cfg_ready;
  assign frame_mask_valid=mask_valid && mode!=1;
  assign mask_ready=frame_mask_ready && mode!=1;
  assign ff_ready=rst_n && first_raw_stall_count==3'd4 && seam_in_ready;
  assign pred_done_ready=pred_done && pred_hold>=4;
  // This is the native-FF terminal join, independent of residual/C completion.
  // Its former seam_done dependency would make nativeDone and CDone circular.
  assign frame_out_drained=raw_values==2048 && !ff_valid && pred_done_seen &&
    write_responses==71 && write_bytes==5632 && !wr_req && !wr_data_valid && !wr_rsp &&
    !client_req_valid[0] && !client_req_valid[1] && !client_rsp_valid[0] && !client_rsp_valid[1] && seam_native_drained;
  assign next_ready=rst_n && !next_owned && !next_rsp && cycles%3!=1;
  assign next_rsp_error=0;assign next_release_ready=next_context_owned;
  assign mem_ready=rst_n && !read_owned && !mem_rsp && cycles%5!=1 && (!mem_req || first_read_stall_count==3'd4);
  assign mem_error=0;
  assign bus_wr_ready=rst_n && !write_owned && !bus_wr_rsp && cycles%4!=1;
  assign bus_wr_data_ready=rst_n && write_owned && !write_all && cycles%4!=2;
  assign bus_wr_req=commit_write_selected ? seam_wr_req:wr_req;
  assign bus_wr_address=commit_write_selected ? seam_wr_address:wr_address;
  assign bus_wr_length=commit_write_selected ? seam_wr_length:wr_length;
  assign bus_wr_valid=commit_write_selected ? seam_wr_valid:wr_data_valid;
  assign bus_wr_data=commit_write_selected ? seam_wr_data:wr_data;
  assign bus_wr_strobe=commit_write_selected ? seam_wr_strobe:wr_strobe;
  assign bus_wr_last=commit_write_selected ? seam_wr_last:wr_last;
  assign bus_wr_rsp_ready=commit_write_selected ? seam_wr_rsp_ready:wr_rsp_ready;
  assign wr_ready=!commit_write_selected && bus_wr_ready;
  assign wr_data_ready=!commit_write_selected && bus_wr_data_ready;
  assign wr_rsp=!commit_write_selected && bus_wr_rsp;
  assign seam_wr_ready=commit_write_selected && bus_wr_ready;
  assign seam_wr_data_ready=commit_write_selected && bus_wr_data_ready;
  assign seam_wr_rsp=commit_write_selected && bus_wr_rsp;
  assign wr_error=0;assign seam_wr_error=0;
  assign c_ready=rst_n && cycles%4!=2;
  assign aux_req={c_req && seam_c_selected,seam_req && !seam_c_selected};
  assign aux_address={c_req_address,seam_address};assign aux_length={c_req_length,seam_length};
  assign seam_req_ready=aux_ready[0] && !seam_c_selected;assign c_req_ready=aux_ready[1] && seam_c_selected;
  assign {c_rsp,seam_rsp}=aux_rsp;assign aux_rsp_ready={c_rsp_ready,seam_rsp_ready};
  assign {c_rsp_last,seam_last}=aux_last;assign {c_rsp_error,seam_error}=aux_error;
  assign {c_rsp_data,seam_data}=aux_data;
  assign outer_req={aux_mem_req,native_mem_req};assign outer_address={aux_mem_address,native_mem_address};
  assign outer_length={aux_mem_length,native_mem_length};assign {aux_mem_ready,native_mem_ready}=outer_ready;
  assign {aux_mem_rsp,native_mem_rsp}=outer_rsp;assign outer_rsp_ready={aux_mem_rsp_ready,native_mem_rsp_ready};
  assign {aux_mem_last,native_mem_last}=outer_last;assign {aux_mem_error,native_mem_error}=outer_error;
  assign {aux_mem_data,native_mem_data}=outer_data;


  tri_oracle_row_unit_frame_adapter_v1 adapter (
    .clk,.rst_n,.abort_valid(abort_valid || top_fault),.cfg_valid(a_cfg_valid),.cfg_ready(a_cfg_ready),
    .cfg_parent_context_valid(1'b1),.cfg_parent_error(1'b0),.cfg_tag_base(context_words[0][31:0]),
    .cfg_layer(context_words[1][4:0]),.cfg_bundle_layer(context_words[1][4:0]),.cfg_epoch(context_words[2][15:0]),
    .cfg_image_start(context_words[3][9:0]),.cfg_input_count(context_words[4][9:0]),.cfg_kept_count(context_words[5][9:0]),
    .cfg_kept_rank(context_words[6][9:0]),.cfg_expected_root(context_words[7][9:0]),.cfg_expected_input_rank(context_words[8][9:0]),
    .cfg_release_after_row(1'b0),.cfg_normalization_role(2'd1),.cfg_phase(2'd1),.cfg_bundle_id({context_words[19],context_words[20]}),
    .cfg_gate_exponent(context_words[10][8:0]),.cfg_up_exponent(context_words[11][8:0]),.cfg_down_max_exponent(context_words[12][8:0]),
    .cfg_gate_delta_max(3'd0),.cfg_up_delta_max(3'd0),.cfg_bucket_count(context_words[13][2:0]),
    .cfg_bucket_exponents(context_words[14][35:0]),.cfg_bucket_gain_caps(context_words[15][35:0]),.cfg_bucket_down_offsets(context_words[16][35:0]),
    .cfg_fallback_gain_cap(context_words[17][8:0]),.cfg_fallback_down_offset(context_words[18][8:0]),
    .cfg_compact_output_base(64'h20000000),.cfg_gate_base(GATE_W),.cfg_up_base(UP_W),.cfg_down_base(DOWN_W),
    .cfg_row_units_base(ROW_UNITS),.cfg_intermediate_base(SCRATCH),.cfg_down_scale_base(DOWN_SCALE),.next_context_owned,
    .next_req_valid(next_req),.next_req_write(next_write),.next_req_ready(next_ready),.next_req_word(next_word),.next_req_data(next_data),
    .next_rsp_valid(next_rsp),.next_rsp_error,.next_rsp_data,.next_rsp_ready,.next_release_valid(next_release),.next_release_ready,
    .frame_cfg_valid(frame_offer),.frame_cfg_ready(frame_offer_ready),.frame_cfg_row_enable(frame_row_enable),.frame_cfg_correction_enable(frame_correction_enable),
    .frame_cfg_tag(frame_tag),.frame_cfg_tokens(frame_tokens),.frame_cfg_input_features(frame_h),.frame_cfg_intermediate_features(frame_k),.frame_cfg_output_features(frame_o),
    .frame_cfg_activation_base(frame_activation),.frame_cfg_gate_base(frame_gate),.frame_cfg_up_base(frame_up),.frame_cfg_down_base(frame_down),
    .frame_cfg_intermediate_base(frame_scratch),.frame_cfg_row_units_base(frame_units),.frame_cfg_activation_stride(frame_stride),
    .frame_cfg_gate_shifts(frame_gate_shifts),.frame_cfg_up_shifts(frame_up_shifts),.frame_cfg_down_shifts(frame_down_shifts),
    .frame_done_valid(frame_done),.frame_done_error,.frame_done_tag,.frame_done_ready,.frame_out_drained,
    .row_context_valid(row_context),.row_tag,.row_layer,.row_epoch,.row_original_root(row_root),.row_input_rank(row_input),.row_kept_rank(row_kept),
    .row_activation_exponent(row_ea),.row_down_max_exponent(row_ed),.row_up_gain(row_gain),.row_down_shift,
    .row_down_physical_exponent(row_output_exp),.row_down_scale_base(row_down_table),.row_bundle_id(row_bundle),
    .legacy_residual_writeback_enable(legacy_writer),.done_valid(a_done),.done_error(a_error),.epoch_fault(a_fault),.frame_active(a_active),.idle(a_idle),.done_ready(a_done_ready)
  );
  tri_oracle_post_feature_prediction_v1 prediction (
    .clk,.rst_n,.abort_valid(abort_valid || top_fault),.next_context_owned,.strip_fabric_owned,
    .cfg_valid(pred_cfg_valid),.cfg_ready(pred_cfg_ready),.cfg_archive_committed(1'b1),.cfg_scalar_weight_units(1'b1),.cfg_normalization_role(2'd1),
    .cfg_tag(row_tag),.cfg_layer(row_layer),.cfg_epoch(row_epoch),.cfg_original_root(row_root),.cfg_input_rank(row_input),.cfg_kept_rank(row_kept),
    .cfg_exponent(row_ea),.cfg_bundle_id(row_bundle),.cfg_feature_base(64'h40000000),.cfg_feature_bytes(64'd442368),
    .cfg_gate_sign_base(GATE_SIG),.cfg_gate_sign_bytes(64'd1441792),.cfg_up_sign_base(UP_SIG),.cfg_up_sign_bytes(64'd1441792),
    .req_valid(client_req_valid[0]),.req_ready(client_req_ready[0]),.req_address(client_req_address[0]),.req_length(client_req_length[0]),
    .rsp_valid(client_rsp_valid[0]),.rsp_ready(client_rsp_ready[0]),.rsp_last(client_rsp_last[0]),.rsp_error(client_rsp_error[0]),.rsp_data(client_rsp_data[0]),
    .strip_request,.strip_response,.mask_valid,.mask_ready,.mask_last,.mask_tag,.mask_start,.mask_count,.mask_bits,
    .done_valid(pred_done),.done_ready(pred_done_ready),.done_error(pred_error),.done_tag(pred_done_tag),.done_layer(pred_done_layer),.done_epoch(pred_done_epoch),
    .done_original_root(pred_done_root),.done_input_rank(pred_done_input),.done_kept_rank(pred_done_kept),.done_exponent(pred_done_exp),.done_bundle_id(pred_done_bundle),
    .completed_groups(pred_groups),.accepted_strips(pred_strips),.accepted_masks(pred_masks),.epoch_fault(pred_fault),.active(pred_active),
    .port_idle(pred_port_idle),.strip_quiet,.idle(pred_idle)
  );
  tri_oracle_external_row_frame row_frame (
    .clk,.rst_n,.cfg_valid(frame_cfg_valid),.cfg_ready(frame_cfg_ready),.cfg_row_enable(frame_row_enable),.cfg_correction_enable(frame_correction_enable),
    .cfg_row_units_base(frame_units),.cfg_tag(frame_tag),.cfg_tokens(frame_tokens),.cfg_input_features(frame_h),.cfg_intermediate_features(frame_k),.cfg_output_features(frame_o),
    .cfg_activation_base(frame_activation),.cfg_gate_base(frame_gate),.cfg_up_base(frame_up),.cfg_down_base(frame_down),.cfg_intermediate_base(frame_scratch),
    .cfg_activation_stride(frame_stride),.cfg_gate_shifts(frame_gate_shifts),.cfg_up_shifts(frame_up_shifts),.cfg_down_shifts(frame_down_shifts),
    .mask_valid(frame_mask_valid),.mask_ready(frame_mask_ready),.mask_tag,.mask_start,.mask_count,.mask_last,.mask_bits,
    .out_valid(ff_valid),.out_ready(ff_ready),.out_tag(ff_tag),.out_token(ff_token),.out_start(ff_start),.out_count(ff_count),.out_last(ff_last),.out_data(ff_data),
    .done_valid(frame_done),.done_ready(frame_done_ready),.done_error(frame_done_error),.done_tag(frame_done_tag),
    .req_valid(client_req_valid[1]),.req_ready(client_req_ready[1]),.req_address(client_req_address[1]),.req_length(client_req_length[1]),
    .rsp_valid(client_rsp_valid[1]),.rsp_ready(client_rsp_ready[1]),.rsp_last(client_rsp_last[1]),.rsp_error(client_rsp_error[1]),.rsp_data(client_rsp_data[1]),
    .wr_req_valid(wr_req),.wr_req_ready(wr_ready),.wr_address,.wr_length,.wr_data_valid,.wr_data_ready,.wr_data,.wr_strobe,.wr_data_last(wr_last),
    .wr_rsp_valid(wr_rsp),.wr_rsp_error(wr_error),.wr_rsp_ready,.attention_enable(1'b0),.attention,.softmax_request(softmax_idle),.backend_request,.backend_response
  );
  tri_oracle_narrow_read_arbiter reads (
    .clk,.rst_n,.client_req_valid,.client_req_ready,.client_req_address,.client_req_length,
    .client_rsp_valid,.client_rsp_ready,.client_rsp_last,.client_rsp_error,.client_rsp_data,
    .mem_req_valid(native_mem_req),.mem_req_ready(native_mem_ready),.mem_req_address(native_mem_address),.mem_req_length(native_mem_length),
    .mem_rsp_valid(native_mem_rsp),.mem_rsp_ready(native_mem_rsp_ready),.mem_rsp_last(native_mem_last),.mem_rsp_error(native_mem_error),.mem_rsp_data(native_mem_data)
  );
  tri_oracle_narrow_read_arbiter auxiliary_reads (
    .clk,.rst_n,.client_req_valid(aux_req),.client_req_ready(aux_ready),.client_req_address(aux_address),.client_req_length(aux_length),
    .client_rsp_valid(aux_rsp),.client_rsp_ready(aux_rsp_ready),.client_rsp_last(aux_last),.client_rsp_error(aux_error),.client_rsp_data(aux_data),
    .mem_req_valid(aux_mem_req),.mem_req_ready(aux_mem_ready),.mem_req_address(aux_mem_address),.mem_req_length(aux_mem_length),
    .mem_rsp_valid(aux_mem_rsp),.mem_rsp_ready(aux_mem_rsp_ready),.mem_rsp_last(aux_mem_last),.mem_rsp_error(aux_mem_error),.mem_rsp_data(aux_mem_data));
  tri_oracle_narrow_read_arbiter physical_reads (
    .clk,.rst_n,.client_req_valid(outer_req),.client_req_ready(outer_ready),.client_req_address(outer_address),.client_req_length(outer_length),
    .client_rsp_valid(outer_rsp),.client_rsp_ready(outer_rsp_ready),.client_rsp_last(outer_last),.client_rsp_error(outer_error),.client_rsp_data(outer_data),
    .mem_req_valid(mem_req),.mem_req_ready(mem_ready),.mem_req_address(mem_address),.mem_req_length(mem_length),
    .mem_rsp_valid(mem_rsp),.mem_rsp_ready,.mem_rsp_last(mem_last),.mem_rsp_error(mem_error),.mem_rsp_data(mem_data));
  tri_oracle_raw32_residual_commit_v1 consumer (
    .clk,.rst_n,.abort_valid(abort_valid || top_fault),.owner_held(next_context_owned),.cfg_valid(seam_cfg_valid),.cfg_ready(seam_cfg_ready),.cfg_job(seam_job),
    .held_job(seam_held_job),.launch_allowed(seam_launch),.active(seam_active),.epoch_fault(seam_fault),
    .native_input_drained(seam_native_drained),.row_context_valid(row_context),.row_tag,.row_layer,.row_epoch,
    .row_root,.row_input_rank(row_input),.row_kept_rank(row_kept),.row_bundle,.row_down_unit(row_output_exp),.row_down_table,
    .row_activation_unit(row_ea),.row_gain(row_gain[8:0]),.row_gate_shift(frame_gate_shifts[5:0]),
    .row_up_shift(frame_up_shifts[5:0]),.row_down_shift,
    .in_valid(ff_valid && first_raw_stall_count==3'd4),.in_ready(seam_in_ready),.in_tag(ff_tag),.in_token(ff_token),.in_start(ff_start),.in_count(ff_count),.in_last(ff_last),.in_data(ff_data),
    .native_done_fire(frame_done && frame_done_ready),.native_done_error(frame_done_error),.native_done_tag(frame_done_tag),
    .req_valid(seam_req),.req_ready(seam_req_ready),.req_address(seam_address),.req_length(seam_length),
    .rsp_valid(seam_rsp),.rsp_last(seam_last),.rsp_error(seam_error),.rsp_ready(seam_rsp_ready),.rsp_data(seam_data),.physical_unowned_response(mem_rsp && !read_owned),
    .write_req_valid(seam_wr_req),.write_req_ready(seam_wr_ready),.write_address(seam_wr_address),.write_length(seam_wr_length),
    .write_data_valid(seam_wr_valid),.write_data_ready(seam_wr_data_ready),.write_data(seam_wr_data),.write_strobe(seam_wr_strobe),.write_last(seam_wr_last),
    .write_rsp_valid(seam_wr_rsp),.write_rsp_error(seam_wr_error),.write_rsp_ready(seam_wr_rsp_ready),
    .c_read_selected(seam_c_selected),.c_cfg_valid(seam_c_cfg),.c_demand_valid(seam_c_demand),.c_retire_valid(seam_c_retire),
    .c_cfg_ready,.c_demand_ready,.c_retire_ready,.c_fault,.c_producer_idle,.c_port_idle,.c_idle,.c_accepted_rows(c_accepted),.c_completed_rows(c_completed),
    .c_output_valid(c_valid),.c_read_request_valid(c_req),.c_read_response_valid(c_rsp),
    .c_output_fire(c_valid && c_ready),.c_output_last(c_last),.c_output_error(c_error),.c_output_tag(c_tag),.c_output_index(c_index),.c_output_count(c_count),
    .row_done_valid(seam_done),.row_done_error(seam_done_error),.row_done_tag(seam_done_tag),.row_done_ready(1'b0),
    .table_words(seam_table_words),.metadata_words(seam_metadata_words),.packet_captured(seam_packet),.held_packet(seam_held_packet),
    .selected_raw_unit(seam_selected_unit),.selected_epsilon(seam_selected_epsilon),
    .scratch_ack_count(seam_scratch_acks),.raw_ack_count(seam_raw_acks),.metadata_acknowledged(seam_metadata_ack));
  tri_oracle_raw32_frame_source_v1 next_C (
    .clk,.rst_n,.abort_valid(abort_valid || top_fault),.cfg_valid(seam_c_cfg),.cfg_ready(c_cfg_ready),.cfg_new_image(1'b0),
    .cfg_tag_base(seam_held_job.target_tag_base),.cfg_layer(seam_held_job.target_layer),.cfg_epoch(seam_held_job.target_epoch),
    .cfg_image_start(seam_held_job.image_start),.cfg_input_rows(seam_held_job.target_count),
    .cfg_raw_frame_base(seam_held_job.target_raw_base),.cfg_raw_frame_bytes(seam_held_job.target_raw_bytes),
    .cfg_metadata_base(seam_held_job.target_metadata_base),.cfg_metadata_bytes(seam_held_job.target_metadata_bytes),
    .cfg_gamma_base(seam_held_job.target_gamma_base),.cfg_gamma_bytes(seam_held_job.target_gamma_bytes),
    .cfg_gamma_exponent(seam_held_job.target_gamma_exponent),
    .row_request_valid(seam_c_demand),.row_request_ready(c_demand_ready),.row_request_original_root(seam_held_job.original_root),
    .row_request_input_rank(seam_held_job.target_rank),.row_request_tag(seam_held_job.target_tag_base+32'(seam_held_job.target_rank)),
    .row_request_layer(seam_held_job.target_layer),.row_request_epoch(seam_held_job.target_epoch),
    .out_valid(c_valid),.out_last(c_last),.out_error(c_error),.out_ready(c_ready),.out_tag(c_tag),.out_index(c_index),.out_count(c_count),.out_activation(c_activation),
    .out_exponent(c_exponent),.out_outlier_mask(c_outlier),.out_outlier_negative(c_outlier_negative),.out_normalized_negative(c_normalized_negative),
    .read_req_valid(c_req),.read_req_ready(c_req_ready),.read_req_address(c_req_address),.read_req_length(c_req_length),
    .read_rsp_valid(c_rsp),.read_rsp_last(c_rsp_last),.read_rsp_error(c_rsp_error),.read_rsp_ready(c_rsp_ready),.read_rsp_data(c_rsp_data),
    .retire_valid(seam_c_retire),.retire_ready(c_retire_ready),.row_source_error(c_fault),.producer_idle(c_producer_idle),.port_idle(c_port_idle),.idle(c_idle),
    .accepted_rows(c_accepted),.completed_rows(c_completed));
  // EXACT legal native family. The frontend's real reset output is observed,
  // never forced high to conceal FLUSH; strip/head use only coupled reset.
  tri_oracle_compute_fabric #(.AGGREGATOR_SIGN_BANK(1),.AGGREGATOR_MERGE_TABLE(1),.LOCAL_TOKEN_SIZES(1),.LOCAL_TOKEN_MERGE(1),
    .CORE_STRIP_PREDICTOR(1),.CORE_HEAD_PREDICTOR(1)) fabric (
    .clk,.rst_n(backend_request.rst_n),.load_valid(backend_request.load_valid),.load_core(backend_request.load_core),.load_kind(backend_request.load_kind),
    .load_addr(backend_request.load_addr),.load_data(backend_request.load_data),.load_row_enable(backend_request.load_rows),.load_error(backend_response.load_error),
    .cmd_valid(backend_request.cmd_valid),.cmd_ready(backend_response.cmd_ready),.cmd_clusters(backend_request.cmd_clusters),.cmd_weight(backend_request.cmd_weight),
    .cmd_mask(backend_request.cmd_mask),.cmd_activation(backend_request.cmd_activation),.cmd_output(backend_request.cmd_output),
    .cmd_accumulate(backend_request.cmd_accumulate),.cmd_reduce(backend_request.cmd_reduce),.out_valid(backend_response.out_valid),.out_ready(backend_request.out_ready),
    .out_output(backend_response.out_output),.out_data(backend_response.out_data),.activation_reloaded(backend_request.activation_reloaded),.core_score_select(backend_request.core_select),
    .merge_sign_data(2048'd0),.merge_sign_control(13'd0),.merge_sign_counts(unused_sign_counts),.merge_table_request(22'd0),.merge_table_word(unused_merge_word),
    .softmax_request(softmax_idle),.softmax_response(softmax_reply),.token_sizes_request(token_idle),.token_sizes_response(token_reply),.merge_request(merge_idle),.merge_response(merge_reply),
    .strip_rst_n(rst_n),.strip_request,.strip_response,.head_request(400'd0),.head_response(unused_head_reply)
  );

  function automatic logic [63:0] input_word(input logic [63:0] address);
    logic [63:0] value;
    logic [63:0] a;
    value=0;
    for(integer lane=0;lane<8;lane++)begin
      a=address+64'(lane);
      if(a>=64'h20000000 && a<64'h20000800)value[lane*8+:8]=codes[int'(a-64'h20000000)];
      else if(a>=64'h40000000 && a<64'h40000300)value[lane*8+:8]=features[int'(a-64'h40000000)];
      else if(a>=GATE_SIG && a<GATE_SIG+1441792)value[lane*8+:8]=gate_signs[int'(a-GATE_SIG)];
      else if(a>=UP_SIG && a<UP_SIG+1441792)value[lane*8+:8]=up_signs[int'(a-UP_SIG)];
      else if(a>=GATE_W && a<GATE_W+11534336)value[lane*8+:8]=gate_weights[int'(a-GATE_W)];
      else if(a>=UP_W && a<UP_W+11534336)value[lane*8+:8]=up_weights[int'(a-UP_W)];
      else if(a>=DOWN_W && a<DOWN_W+11534336)value[lane*8+:8]=down_weights[int'(a-DOWN_W)];
      else if(a>=ROW_UNITS && a<ROW_UNITS+4544)value[lane*8+:8]=row_units[int'(a-ROW_UNITS)];
      else if(a>=DOWN_SCALE && a<DOWN_SCALE+1024)value[lane*8+:8]=down_scales[int'(a-DOWN_SCALE)];
      else if(a>=SCRATCH && a<SCRATCH+5632)begin
        if(!scratch_committed[int'(a-SCRATCH)])$fatal(1,"FULL_FF_DOWN_READ_BEFORE_ACTUAL_WRITE_ACK byte=%0d",int'(a-SCRATCH));
        value[lane*8+:8]=scratch[int'(a-SCRATCH)];
      end else if(a>=OLD_RAW+5*8192 && a<OLD_RAW+6*8192)value[lane*8+:8]=original_raw[int'(a-OLD_RAW-5*8192)];
      else if(a>=OLD_META && a<OLD_META+16)value[lane*8+:8]=original_metadata[int'(a-OLD_META)];
      else if(a>=PRE1_GAMMA && a<PRE1_GAMMA+6144)value[lane*8+:8]=pre1_gamma[int'(a-PRE1_GAMMA)];
      else if(a>=DOWN_SCRATCH && a<DOWN_SCRATCH+8192)begin
        if(!down_committed[int'(a-DOWN_SCRATCH)])$fatal(1,"RAW32_RESIDUAL_UNCOMMITTED_DOWN_READ");
        value[lane*8+:8]=down_scratch[int'(a-DOWN_SCRATCH)];
      end else if(a>=TARGET_RAW && a<TARGET_RAW+RAW_EXTENT)begin
        if(!target_raw_committed[int'(a-TARGET_RAW)])$fatal(1,"RAW32_RESIDUAL_UNPUBLISHED_RAW_READ");
        value[lane*8+:8]=target_raw[int'(a-TARGET_RAW)];
      end else if(a>=TARGET_META && a<TARGET_META+META_EXTENT)begin
        if(!target_meta_committed[int'(a-TARGET_META)])$fatal(1,"RAW32_RESIDUAL_UNPUBLISHED_METADATA_READ");
        value[lane*8+:8]=target_metadata[int'(a-TARGET_META)];
      end else $fatal(1,"FULL_FF_UNMAPPED_READ address=%016h",a);
    end
    return value;
  endfunction
  function automatic logic signed [31:0] expected_raw(input integer channel);
    return $signed({expected_raw_bytes[4*channel+3],expected_raw_bytes[4*channel+2],expected_raw_bytes[4*channel+1],expected_raw_bytes[4*channel]});
  endfunction

  always @(posedge clk or negedge rst_n)begin : descriptor_fixture_peer
    if(!rst_n)begin next_owned<=0;next_rsp<=0;next_rsp_data<=0;descriptor_requests<=0;descriptor_responses<=0;end
    else begin
      if(next_req && next_ready)begin
        if(next_write || next_word!=256 || next_data!=0 || next_owned)$fatal(1,"FULL_FF_WRONG_FIRST_REAL_DESCRIPTOR_READ");
        next_owned<=1;descriptor_requests<=descriptor_requests+1;
      end
      if(next_owned && !next_rsp)begin next_rsp<=1;next_rsp_data<=descriptor[0];end
      if(next_rsp && next_rsp_ready)begin next_rsp<=0;next_owned<=0;descriptor_responses<=descriptor_responses+1;end
      if(next_release)$fatal(1,"FULL_FF_NONFINAL_ROW_RELEASED_NEXT_OWNER");
    end
  end
  always @(posedge clk or negedge rst_n)begin : read_provider
    if(!rst_n)begin read_owned<=0;mem_rsp<=0;mem_last<=0;mem_data<=0;read_address<=0;read_length<=0;read_beat<=0;read_delay<=0;read_requests<=0;read_responses<=0;end
    else begin
      if(mem_req && mem_ready)begin
        if(read_owned || mem_rsp || mem_length==0 || mem_length>16 || mem_address[2:0]!=0)$fatal(1,"FULL_FF_BAD_READ_OWNERSHIP");
        read_owned<=1;read_address<=mem_address;read_length<=mem_length;read_beat<=0;read_delay<=0;read_requests<=read_requests+1;
      end
      if(read_owned && !mem_rsp)begin
        if(read_delay>=1)begin mem_rsp<=1;mem_last<=read_beat+1==int'(read_length);mem_data<=input_word(read_address+64'(read_beat)*8);end
        else read_delay<=read_delay+1;
      end
      if(mem_rsp && mem_rsp_ready)begin
        read_delay<=0;read_responses<=read_responses+1;
        if(mem_last)begin mem_rsp<=0;read_owned<=0;end
        else begin
          read_beat<=read_beat+1;mem_rsp<=1;
          mem_last<=read_beat+2==int'(read_length);
          mem_data<=input_word(read_address+64'(read_beat+1)*8);
        end
      end
    end
  end
  always @(posedge clk or negedge rst_n)begin : single_physical_write_provider
    if(!rst_n)begin
      write_owned<=0;write_all<=0;bus_wr_rsp<=0;write_address<=0;write_length<=0;write_beat<=0;write_delay<=0;
      write_requests<=0;write_responses<=0;write_bytes<=0;
      commit_write_requests<=0;commit_write_responses<=0;commit_write_bytes<=0;
      scratch_write_requests<=0;scratch_write_responses<=0;raw_write_requests<=0;raw_write_responses<=0;
      metadata_write_requests<=0;metadata_write_responses<=0;metadata_ack_delay_cycles<=0;
    end else begin
      if(bus_wr_rsp && !write_owned)$fatal(1,"RAW32_RESIDUAL_UNASSOCIATED_PHYSICAL_WRITE_ACK");
      if(bus_wr_req && bus_wr_ready)begin
        if(write_owned || bus_wr_rsp)$fatal(1,"RAW32_RESIDUAL_BAD_WRITE_OWNERSHIP");
        if(!commit_write_selected)begin
          if(bus_wr_address!==SCRATCH+64'(write_bytes) || bus_wr_length!=(write_requests==70 ? 4:10))
            $fatal(1,"FULL_FF_WRONG_REAL_INTERMEDIATE_WRITE");
          write_requests<=write_requests+1;
        end else begin
          if(bus_wr_address>=DOWN_SCRATCH && bus_wr_address<DOWN_SCRATCH+8192)begin
            if(bus_wr_address!==DOWN_SCRATCH+64'(scratch_write_requests)*64 || bus_wr_length!=8 || scratch_write_requests>=128 || raw_write_requests!=0)
              $fatal(1,"RAW32_RESIDUAL_SCRATCH_SEQUENCE");
            scratch_write_requests<=scratch_write_requests+1;
          end else if(bus_wr_address>=TARGET_RAW+5*8192 && bus_wr_address<TARGET_RAW+6*8192)begin
            if(bus_wr_address!==TARGET_RAW+5*8192+64'(raw_write_requests)*64 || bus_wr_length!=8 ||
               scratch_write_responses!=128 || raw_write_requests>=128 || metadata_write_requests!=0)
              $fatal(1,"RAW32_RESIDUAL_RAW_SEQUENCE_OR_EARLY_PUBLICATION");
            raw_write_requests<=raw_write_requests+1;
          end else if(bus_wr_address==TARGET_META)begin
            if(bus_wr_length!=2 || scratch_write_responses!=128 || raw_write_responses!=128 || metadata_write_requests!=0)
              $fatal(1,"RAW32_RESIDUAL_METADATA_BEFORE_ALL_RAW_ACKS");
            metadata_write_requests<=metadata_write_requests+1;
          end else $fatal(1,"RAW32_RESIDUAL_WRONG_COMMIT_DESTINATION");
          commit_write_requests<=commit_write_requests+1;
        end
        write_owned<=1;write_all<=0;write_address<=bus_wr_address;write_length<=bus_wr_length;write_beat<=0;write_delay<=0;
      end
      if(bus_wr_valid && bus_wr_data_ready)begin
        if(!write_owned || write_all || bus_wr_strobe!=8'hff || bus_wr_last!=(write_beat+1==int'(write_length)))
          $fatal(1,"RAW32_RESIDUAL_BAD_PHYSICAL_WRITE_DATA");
        if(commit_write_selected && write_address>=DOWN_SCRATCH && write_address<DOWN_SCRATCH+8192)begin
          for(integer half=0;half<2;half++)begin
            integer feature;
            feature=int'((write_address-DOWN_SCRATCH)/4)+2*write_beat+half;
            if(!observed_down_present[feature] || bus_wr_data[half*32+:32]!==observed_down[feature])
              $fatal(1,"RAW32_RESIDUAL_SCRATCH_NOT_ACTUAL_DOWN feature=%0d",feature);
          end
        end
        for(integer lane=0;lane<8;lane++)write_packet[write_beat*8+lane]<=bus_wr_data[lane*8+:8];
        if(bus_wr_last)write_all<=1;else write_beat<=write_beat+1;
      end
      if(write_owned && write_all && !bus_wr_rsp)begin
        // Last metadata ACK deliberately remains pending for twelve cycles.
        if(write_address==TARGET_META)metadata_ack_delay_cycles<=metadata_ack_delay_cycles+1;
        if(write_delay>=(write_address==TARGET_META ? 12:3))bus_wr_rsp<=1;else write_delay<=write_delay+1;
      end
      if(bus_wr_rsp && bus_wr_rsp_ready)begin
        if(!commit_write_selected)begin
          for(integer lane=0;lane<80;lane++)if(lane<int'(write_length)*8)begin
            scratch[int'(write_address-SCRATCH)+lane]<=write_packet[lane];scratch_committed[int'(write_address-SCRATCH)+lane]<=1;
          end
          write_bytes<=write_bytes+int'(write_length)*8;write_responses<=write_responses+1;
        end else begin
          if(write_address>=DOWN_SCRATCH && write_address<DOWN_SCRATCH+8192)begin
            for(integer lane=0;lane<64;lane++)begin down_scratch[int'(write_address-DOWN_SCRATCH)+lane]<=write_packet[lane];down_committed[int'(write_address-DOWN_SCRATCH)+lane]<=1;end
            scratch_write_responses<=scratch_write_responses+1;
            $display("RAW32_RESIDUAL_SCRATCH_ACK cycle=%0d line=%0d address=%016h bytes=64",cycles,scratch_write_responses,write_address);$fflush();
          end else if(write_address>=TARGET_RAW+5*8192 && write_address<TARGET_RAW+6*8192)begin
            for(integer lane=0;lane<64;lane++)begin target_raw[int'(write_address-TARGET_RAW)+lane]<=write_packet[lane];target_raw_committed[int'(write_address-TARGET_RAW)+lane]<=1;end
            raw_write_responses<=raw_write_responses+1;
            for(integer beat=0;beat<8;beat++)begin
              $display("RAW32_RESIDUAL_RAW_ACK_DATA cycle=%0d line=%0d beat=%0d address=%016h data=%02h%02h%02h%02h%02h%02h%02h%02h",cycles,raw_write_responses,beat,write_address+64'(beat)*8,
                write_packet[beat*8+7],write_packet[beat*8+6],write_packet[beat*8+5],write_packet[beat*8+4],write_packet[beat*8+3],write_packet[beat*8+2],write_packet[beat*8+1],write_packet[beat*8]);$fflush();
            end
          end else begin
            for(integer lane=0;lane<16;lane++)begin target_metadata[lane]<=write_packet[lane];target_meta_committed[lane]<=1;end
            metadata_write_responses<=metadata_write_responses+1;
            $display("RAW32_RESIDUAL_METADATA_ACK cycle=%0d address=%016h unit=%0d epsilon=%0d bytes=%02h%02h%02h%02h%02h%02h%02h%02h%02h%02h%02h%02h%02h%02h%02h%02h",cycles,write_address,$signed(seam_selected_unit),seam_selected_epsilon,
              write_packet[15],write_packet[14],write_packet[13],write_packet[12],write_packet[11],write_packet[10],write_packet[9],write_packet[8],write_packet[7],write_packet[6],write_packet[5],write_packet[4],write_packet[3],write_packet[2],write_packet[1],write_packet[0]);$fflush();
          end
          commit_write_bytes<=commit_write_bytes+int'(write_length)*8;commit_write_responses<=commit_write_responses+1;
        end
        write_owned<=0;write_all<=0;bus_wr_rsp<=0;
      end
    end
  end
  always @(posedge clk or negedge rst_n)begin : seam_observations
    if(!rst_n)begin
      aux_phase_busy<=0;held_aux_phase<=0;commit_write_selected<=0;first_down_observed<=0;progress_wait<=0;
      c_strips<=0;c_cfg_fires<=0;c_demand_fires<=0;c_retire_fires<=0;held_done_cycles<=0;
      commit_request_stalls<=0;commit_data_stalls<=0;seam_write_req_held<=0;seam_write_data_held<=0;
      seam_saved_write_request<=0;seam_saved_write_data<=0;
      for(integer feature=0;feature<2048;feature++)begin observed_down[feature]<='x;observed_down_present[feature]<=0;end
    end else begin
      if(aux_phase_busy && seam_c_selected!==held_aux_phase)$fatal(1,"RAW32_RESIDUAL_REASSOCIATED_AUXILIARY_BURST");
      if(aux_mem_req && aux_mem_ready)begin aux_phase_busy<=1;held_aux_phase<=seam_c_selected;end
      if(aux_mem_rsp && aux_mem_rsp_ready && aux_mem_last)aux_phase_busy<=0;
      if(seam_fault || c_fault)$fatal(1,"RAW32_RESIDUAL_ACTUAL_COMPONENT_FAULT");
      if(ff_valid && ff_ready)begin
        if(raw_packets==0)begin
          if(group_results!=176 || mask_fires!=71 || write_responses!=71 || write_bytes!=5632 || write_owned || bus_wr_rsp || wr_req || wr_data_valid)
            $fatal(1,"RAW32_RESIDUAL_DOWN_BEFORE_REAL_NATIVE_DRAIN");
          first_down_observed<=ff_data;commit_write_selected<=1;
        end
        for(integer feature=0;feature<160;feature++)if(feature<int'(ff_count))begin
          observed_down[int'(ff_start)+feature]<=ff_data[feature*32+:32];observed_down_present[int'(ff_start)+feature]<=1;
        end
      end
      if(seam_write_req_held && (!seam_wr_req || {seam_wr_address,seam_wr_length}!==seam_saved_write_request))
        $fatal(1,"RAW32_RESIDUAL_RETRACTED_COMMIT_REQUEST");
      if(seam_write_data_held && (!seam_wr_valid || {seam_wr_data,seam_wr_strobe,seam_wr_last}!==seam_saved_write_data))
        $fatal(1,"RAW32_RESIDUAL_RETRACTED_COMMIT_DATA");
      seam_write_req_held<=seam_wr_req && !seam_wr_ready;seam_saved_write_request<={seam_wr_address,seam_wr_length};
      seam_write_data_held<=seam_wr_valid && !seam_wr_data_ready;seam_saved_write_data<={seam_wr_data,seam_wr_strobe,seam_wr_last};
      if(seam_wr_req && !seam_wr_ready)commit_request_stalls<=commit_request_stalls+1;
      if(seam_wr_valid && !seam_wr_data_ready)commit_data_stalls<=commit_data_stalls+1;
      if((seam_c_cfg || seam_c_demand || seam_c_selected || c_req || c_valid) &&
         (metadata_write_responses!=1 || commit_write_responses!=257 || !seam_metadata_ack))
        $fatal(1,"RAW32_RESIDUAL_C_BEFORE_FINAL_METADATA_ACK");
      if(seam_c_cfg && c_cfg_ready)begin c_cfg_fires<=c_cfg_fires+1;$display("RAW32_RESIDUAL_C_CFG cycle=%0d count=%0d",cycles,seam_held_job.target_count);$fflush();end
      if(seam_c_demand && c_demand_ready)begin c_demand_fires<=c_demand_fires+1;$display("RAW32_RESIDUAL_C_DEMAND cycle=%0d rank=%0d root=%0d",cycles,seam_held_job.target_rank,seam_held_job.original_root);$fflush();end
      if(seam_c_retire)c_retire_fires<=c_retire_fires+1;
      if(seam_c_retire || next_release || !next_context_owned)$fatal(1,"RAW32_RESIDUAL_PREMATURE_PARENT_OR_C_RETIRE");
      if(seam_done)begin
        if(seam_done_error || seam_done_tag!==TARGET_TAG || c_strips!=256 || c_accepted!=1 || c_completed!=1 ||
           !c_producer_idle || !c_port_idle || c_valid || c_req || c_rsp || !c_demand_ready || c_idle || !row_context || !a_done)
          $fatal(1,"RAW32_RESIDUAL_DONE_BEFORE_NATIVE_C_DRAIN_OR_OWNER_HOLD");
        held_done_cycles<=held_done_cycles+1;
      end
      if(c_valid && c_ready)begin
        if(c_error || c_tag!==TARGET_TAG || c_index!==10'(c_strips) || c_count!=8 || c_last!==(c_strips==255))
          $fatal(1,"RAW32_RESIDUAL_NEXT_C_SEQUENCE");
        c_strips<=c_strips+1;
        $display("RAW32_RESIDUAL_C_STRIP cycle=%0d tag=%08h index=%0d count=%0d last=%b eA=%0d code=%016h mask=%02h negative=%02h outlier_negative=%02h",cycles,c_tag,c_index,c_count,c_last,$signed(c_exponent),c_activation,c_outlier,c_normalized_negative,c_outlier_negative);$fflush();
      end
    end
  end

  always @(posedge clk or negedge rst_n)begin : scoreboard_and_owned_fences
    if(!rst_n)begin
      group_live<=0;group_cluster<=0;group_inputs<=0;group_results<=0;
      cycles<=0;top_fault<=0;adapter_cfg_fires<=0;frame_cfg_fires<=0;mask_fires<=0;raw_packets<=0;raw_values<=0;
      pred_hold<=0;pred_done_seen<=0;mask_stalls<=0;output_stalls<=0;read_stalls<=0;write_stalls<=0;backend_commands<=0;backend_loads<=0;
      first_raw_stall_count<=0;first_read_stall_count<=0;
      req_held<=0;rsp_held<=0;wr_req_held<=0;wr_data_held<=0;mask_held<=0;out_held<=0;a_done_held<=0;
      held_req<=0;held_rsp<=0;held_wr_req<=0;held_wr_data<=0;held_mask<='0;held_output<='0;held_a_error<=0;
    end else begin
      cycles<=cycles+1;
      if(cycles>64000000)$fatal(1,"FULL_FF_WATCHDOG");
      // The narrow arbiter has no native unknown-response quarantine. This
      // validation fence classifies a bad run; it never manufactures an ACK.
      if(mem_rsp && !read_owned)begin top_fault<=1;$fatal(1,"FULL_FF_UNASSOCIATED_READ_RESPONSE");end
      if(!backend_request.rst_n)begin top_fault<=1;$fatal(1,"FULL_FF_LOCAL_BACKEND_RESET_INVALIDATES_EPOCH");end
      if(a_fault || pred_fault || backend_response.load_error)$fatal(1,"FULL_FF_ACTUAL_COMPONENT_FAULT");
      if(legacy_writer)$fatal(1,"FULL_FF_LEGACY_RESIDUAL_WRITER_ENABLED");
      if(backend_request.load_valid)backend_loads<=backend_loads+1;
      if(backend_request.cmd_valid && backend_response.cmd_ready)begin
        if(backend_request.cmd_clusters!==5'b11111)$fatal(1,"FULL_FF_NOT_ALL_FIVE_COMPUTE_CLUSTERS");
        backend_commands<=backend_commands+1;
      end
      // This observes the real fabric channel, not the packetizer's derived KEEP.
      if(group_live && strip_request[533:531]!==group_cluster)
        $fatal(1,"FULL_FF_PREDICTOR_CLUSTER_CHANGED_BEFORE_RESULT_ACK group=%0d",group_results);
      if(strip_request[530])begin
        if(group_results>=176 || strip_request[533:531]!==3'(group_results%5))
          $fatal(1,"FULL_FF_WRONG_GROUP_CLUSTER group=%0d",group_results);
        if(!group_live)begin group_live<=1;group_cluster<=strip_request[533:531];end
      end
      if(strip_request[530] && strip_response[111])begin
        if(group_inputs>=256 || strip_request[529]!==(group_inputs==255))
          $fatal(1,"FULL_FF_WRONG_GROUP_STRIP_LAST group=%0d strip=%0d",group_results,group_inputs);
        group_inputs<=group_inputs+1;
      end
      if(strip_response[110] && strip_request[528])begin
        if(group_results>=176 || !group_live || group_inputs!=256 || strip_response[109] ||
           strip_request[533:531]!==3'(group_results%5) ||
           strip_response[108:0]!==expected_groups[group_results][108:0])
          $fatal(1,"FULL_FF_FULL_PREDICTOR_RESULT_MISMATCH group=%0d cluster=%0d actual=%028h expected=%028h",group_results,strip_request[533:531],strip_response,expected_groups[group_results]);
        $display("FULL_FF_GROUP_RESULT cycle=%0d group=%0d cluster=%0d result=%028h",cycles,group_results,strip_request[533:531],strip_response);$fflush();
        group_results<=group_results+1;group_inputs<=0;group_live<=0;
      end
      if(a_cfg_valid && a_cfg_ready)adapter_cfg_fires<=adapter_cfg_fires+1;
      if(frame_offer && frame_offer_ready)begin
        $display("FULL_FF_CONFIG cycle=%0d tag=%08h eA=%0d gate_shift=%0d up_shift=%0d down_shift=%0d gain=%0d raw_exponent=%0d",cycles,frame_tag,$signed(row_ea),frame_gate_shifts[5:0],frame_up_shifts[5:0],frame_down_shifts[5:0],$signed(row_gain),$signed(row_output_exp));$fflush();
        frame_cfg_fires<=frame_cfg_fires+1;
        if(!row_context || frame_tokens!=1 || frame_h!=2048 || frame_k!=5632 || frame_o!=2048 || !frame_row_enable || frame_correction_enable ||
           frame_gate_shifts!=={90'd0,context_words[21][5:0]} || frame_up_shifts!=={90'd0,context_words[22][5:0]} || frame_down_shifts!=={90'd0,context_words[23][5:0]})
          $fatal(1,"FULL_FF_ADAPTER_COMMAND_NOT_ACTUAL_DERIVATION");
      end
      if(req_held && (!mem_req || {mem_address,mem_length}!==held_req))$fatal(1,"FULL_FF_RETRACTED_READ");
      if(rsp_held && (!mem_rsp || {mem_data,mem_last,mem_error}!==held_rsp))$fatal(1,"FULL_FF_PROVIDER_RETRACTED_RESPONSE");
      if(wr_req_held && (!wr_req || {wr_address,wr_length}!==held_wr_req))$fatal(1,"FULL_FF_RETRACTED_WRITE_REQUEST");
      if(wr_data_held && (!wr_data_valid || {wr_data,wr_strobe,wr_last}!==held_wr_data))$fatal(1,"FULL_FF_RETRACTED_WRITE_DATA");
      if(mask_held && (!mask_valid || {mask_last,mask_tag,mask_start,mask_count,mask_bits}!==held_mask))$fatal(1,"FULL_FF_RETRACTED_KEEP");
      if(out_held && (!ff_valid || {ff_tag,ff_token,ff_start,ff_count,ff_last,ff_data}!==held_output))$fatal(1,"FULL_FF_RETRACTED_RAW_OUTPUT");
      if(a_done_held && (!a_done || a_error!==held_a_error))$fatal(1,"FULL_FF_RETRACTED_ROW_DONE");
      if(wr_data_valid && wr_data_ready)
        for(integer lane=0;lane<8;lane++)
          if(wr_data[lane*8+:8]!==expected_down_input[int'(write_address-SCRATCH)+write_beat*8+lane])
            $fatal(1,"FULL_FF_INTERMEDIATE_REFERENCE_MISMATCH channel=%0d",int'(write_address-SCRATCH)+write_beat*8+lane);
      if(wr_data_valid && wr_data_ready)begin $display("FULL_FF_INTERMEDIATE_DATA cycle=%0d address=%016h beat=%0d data=%016h last=%b",cycles,write_address,write_beat,wr_data,wr_last);$fflush();end
      if(wr_rsp && wr_rsp_ready)begin $display("FULL_FF_INTERMEDIATE_ACK cycle=%0d address=%016h length=%0d",cycles,write_address,write_length);$fflush();end
      if(mask_valid && mask_ready)begin
        $display("FULL_FF_KEEP cycle=%0d tag=%08h start=%0d count=%0d last=%b bits=%0320h",cycles,mask_tag,mask_start,mask_count,mask_last,mask_bits);$fflush();
        if(mask_fires>=71 || mask_tag!==descriptor[0][31:0] || mask_start!==16'(mask_fires*80) || mask_count!==(mask_fires==70 ? 7'd32 : 7'd80) ||
           mask_last!==(mask_fires==70) || mask_bits!==expected_keep[mask_fires])$fatal(1,"FULL_FF_ACTUAL_KEEP_MISMATCH packet=%0d",mask_fires);
        mask_fires<=mask_fires+1;
      end
      if(ff_valid && ff_ready)begin
        $display("FULL_FF_RAW cycle=%0d tag=%08h start=%0d count=%0d last=%b eOut=%0d data=%01280h",cycles,ff_tag,ff_start,ff_count,ff_last,$signed(row_output_exp),ff_data);$fflush();
        if(!row_context || ff_tag!==descriptor[0][31:0] || ff_token!=0 || ff_start!==16'(raw_packets*160) ||
           ff_count!==(raw_packets==12 ? 8'd128 : 8'd160) || ff_last!==(raw_packets==12) || raw_packets>=13 ||
           $signed(row_output_exp)!=$signed(context_words[25]) || $signed(row_gain)!=$signed(context_words[24]) || row_down_shift!==context_words[23][5:0])
          $fatal(1,"FULL_FF_RAW_IDENTITY_UNIT_OR_SHAPE_MISMATCH packet=%0d",raw_packets);
        for(integer lane=0;lane<160;lane++)begin
          if(lane<int'(ff_count))begin
            if(ff_data[lane*32+:32]!==expected_raw(int'(ff_start)+lane))
              $fatal(1,"FULL_FF_RAW_REFERENCE_MISMATCH channel=%0d actual=%0d expected=%0d",int'(ff_start)+lane,$signed(ff_data[lane*32+:32]),expected_raw(int'(ff_start)+lane));
          end else if(ff_data[lane*32+:32]!==32'd0)$fatal(1,"FULL_FF_RAW_PADDING_NOT_ZERO");
        end
        raw_packets<=raw_packets+1;raw_values<=raw_values+int'(ff_count);
      end
      if(pred_done)begin
        pred_hold<=pred_hold+1;
        if(pred_error || pred_groups!=176 || pred_strips!=45056 || pred_masks!=71 || mask_fires!=71 || group_results!=176 || group_live ||
           pred_done_tag!==descriptor[0][31:0] || pred_done_root!==context_words[7][9:0] || pred_done_kept!=0 ||
           pred_done_layer!==context_words[1][4:0] || pred_done_epoch!==context_words[2][15:0] || pred_done_exp!==descriptor[0][60:52] ||
           pred_done_input!==context_words[8][9:0] || pred_done_bundle!=={context_words[19],context_words[20]})
          $fatal(1,"FULL_FF_PREDICTION_EARLY_OR_WRONG_DONE");
      end
      if(pred_done && pred_done_ready)pred_done_seen<=1;
      // Observe the actual producer completion at its real public handshake.
      // No delay/gating or provider/owner/drain behavior changes accompany this.
      if(frame_done && frame_done_ready)begin
        $display("FULL_FF_NATIVE_DONE cycle=%0d tag=%08h error=%b scratch_ACKs=%0d native_input_drained=%b",cycles,frame_done_tag,frame_done_error,seam_scratch_acks,seam_native_drained);$fflush();
      end
      if(frame_done && (frame_done_error || raw_values!=2048 || raw_packets!=13 || write_responses!=71 || write_bytes!=5632))$fatal(1,"FULL_FF_FRAME_EARLY_DONE");
      if(a_done && (a_error || !frame_out_drained || adapter_cfg_fires!=1 || frame_cfg_fires!=1 || descriptor_requests!=1 || descriptor_responses!=1))$fatal(1,"FULL_FF_ADAPTER_EARLY_DONE");
      if(mask_valid && !mask_ready)mask_stalls<=mask_stalls+1;
      if(ff_valid && !ff_ready)output_stalls<=output_stalls+1;
      if(ff_valid && !ff_ready && first_raw_stall_count<3'd4)first_raw_stall_count<=first_raw_stall_count+3'd1;
      if(mem_req && !mem_ready)read_stalls<=read_stalls+1;
      if(mem_req && !mem_ready && first_read_stall_count<3'd4)first_read_stall_count<=first_read_stall_count+3'd1;
      if(wr_req && !wr_ready)write_stalls<=write_stalls+1;
      req_held<=mem_req && !mem_ready;rsp_held<=mem_rsp && !mem_rsp_ready;
      wr_req_held<=wr_req && !wr_ready;wr_data_held<=wr_data_valid && !wr_data_ready;
      mask_held<=mask_valid && !mask_ready;out_held<=ff_valid && !ff_ready;a_done_held<=a_done && !a_done_ready;
      held_req<={mem_address,mem_length};held_rsp<={mem_data,mem_last,mem_error};held_wr_req<={wr_address,wr_length};held_wr_data<={wr_data,wr_strobe,wr_last};
      held_mask<={mask_last,mask_tag,mask_start,mask_count,mask_bits};held_output<={ff_tag,ff_token,ff_start,ff_count,ff_last,ff_data};held_a_error<=a_error;
    end
  end

  task automatic load_exact(input string path,input integer count,ref byte unsigned target[]);
    integer handle,n,tail;
    handle=$fopen(path,"rb");if(handle==0)$fatal(1,"FULL_FF_REQUIRED_FILE_MISSING path=%s",path);
    target=new[count];
    n=$fread(target,handle);tail=$fgetc(handle);$fclose(handle);
    if(n!=count || tail!=-1)$fatal(1,"FULL_FF_REQUIRED_FILE_WRONG_SIZE path=%s got=%0d",path,n);
  endtask
  task automatic check_census();
    integer n35,n36,total_accepts,total_results;
    n35=0;n36=0;total_accepts=0;total_results=0;
    if(full_ff_counts::cells[0]!=360 || full_ff_counts::cells[1]!=40 || full_ff_counts::cells[2]!=200 || full_ff_counts::cells[3]!=16 ||
       full_ff_counts::cells[4]!=4 || full_ff_counts::cells[5]!=1 || full_ff_counts::cells[6]!=20 || full_ff_counts::cells[7]!=20 || full_ff_counts::cells[8]!=20 || full_ff_counts::next_uid!=20 || full_ff_counts::pe_uid!=20)
      $fatal(1,"FULL_FF_NATIVE_CENSUS_MISMATCH");
    for(integer core=0;core<20;core++)begin
      if(backend_commands<=0 || backend_loads<=0 || full_ff_counts::pe_accepts[core]!=backend_commands ||
         full_ff_counts::pe_results[core]!=backend_commands)$fatal(1,"FULL_FF_PHYSICAL_PE_COMMAND_CENSUS_WRONG core=%0d",core);
      if(full_ff_counts::strip_results[core]==35)n35++;
      else if(full_ff_counts::strip_results[core]==36)n36++;
      else $fatal(1,"FULL_FF_PHYSICAL_STRIP_RESULTS_WRONG core=%0d",core);
      if(full_ff_counts::strip_accepts[core]!=256*full_ff_counts::strip_results[core])
        $fatal(1,"FULL_FF_PHYSICAL_STRIP_TRANSFERS_WRONG core=%0d",core);
      total_accepts+=full_ff_counts::strip_accepts[core];total_results+=full_ff_counts::strip_results[core];
    end
    if(n35!=16 || n36!=4 || total_accepts!=180224 || total_results!=704)$fatal(1,"FULL_FF_CORE_GROUP_CENSUS_WRONG");
  endtask
  task automatic check_progress_census();
    integer total_accepts,total_results,n35,n36;
    total_accepts=0;total_results=0;n35=0;n36=0;
    if(full_ff_counts::cells[0]!=360 || full_ff_counts::cells[1]!=40 || full_ff_counts::cells[2]!=200 || full_ff_counts::cells[3]!=16 ||
       full_ff_counts::cells[4]!=4 || full_ff_counts::cells[5]!=1 || full_ff_counts::cells[6]!=20 || full_ff_counts::cells[7]!=20 || full_ff_counts::cells[8]!=20 || full_ff_counts::next_uid!=20 || full_ff_counts::pe_uid!=20)
      $fatal(1,"RAW32_RESIDUAL_NATIVE_CENSUS_MISMATCH");
    for(integer core=0;core<20;core++)begin
      if(full_ff_counts::pe_accepts[core]<=0 || full_ff_counts::pe_results[core]<=0 || full_ff_counts::pe_results[core]>full_ff_counts::pe_accepts[core])
        $fatal(1,"RAW32_RESIDUAL_PHYSICAL_PE_PATH_MISSING core=%0d",core);
      if(full_ff_counts::strip_results[core]==35)n35++;
      else if(full_ff_counts::strip_results[core]==36)n36++;
      else $fatal(1,"RAW32_RESIDUAL_PHYSICAL_STRIP_RESULTS_WRONG core=%0d",core);
      if(full_ff_counts::strip_accepts[core]!=256*full_ff_counts::strip_results[core])$fatal(1,"RAW32_RESIDUAL_PHYSICAL_STRIP_TRANSFERS_WRONG");
      total_accepts+=full_ff_counts::strip_accepts[core];total_results+=full_ff_counts::strip_results[core];
    end
    if(n35!=16 || n36!=4 || total_accepts!=180224 || total_results!=704)$fatal(1,"RAW32_RESIDUAL_CORE_GROUP_CENSUS_WRONG");
  endtask
  initial begin
    rst_n=0;abort_valid=0;next_context_owned=1;strip_fabric_owned=1;a_cfg_valid=0;a_done_ready=0;mode=0;seam_cfg_valid=0;seam_job='0;
    if(!$value$plusargs("SEAM_INPUT_ROOT=%s",seam_input_root))$fatal(1,"RAW32_RESIDUAL_REQUIRED_INPUT_ROOT_MISSING");
    if(!$value$plusargs("ROW_FIXTURE=%s",fixture_root) || !$value$plusargs("WEIGHT_ROOT=%s",weight_root) || !$value$plusargs("GOLDEN_ROOT=%s",golden_root))
      $fatal(1,"FULL_FF_REQUIRED_ROOT_ARGUMENTS_MISSING");
    if($test$plusargs("FULL_FF_INERT_KEEP") || $test$plusargs("FULL_FF_INERT_WRITE"))$fatal(1,"RAW32_RESIDUAL_WRONG_INERT_MODE");
    $readmemh({fixture_root,"/row_config.hex"},context_words);
    $readmemh({fixture_root,"/actual_descriptor.hex"},descriptor);
    for(integer index=0;index<26;index++)
      if($isunknown(context_words[index]))$fatal(1,"FULL_FF_UNKNOWN_OR_MISSING_CONTEXT_WORD index=%0d",index);
    if($isunknown(descriptor[0]))$fatal(1,"FULL_FF_UNKNOWN_OR_MISSING_DESCRIPTOR");
    // Never silently rebase rank13: fresh adapter must consume real rank0.
    if(context_words[6]!=0 || context_words[5]<=1 || context_words[4]<context_words[5] ||
       descriptor[0][63:61]!=3'b010 || descriptor[0][51:42]!=0 || descriptor[0][41:32]!==context_words[7][9:0] ||
       descriptor[0][31:0]!==context_words[0][31:0]+context_words[8][31:0] || descriptor[0][60:52]!==context_words[9][8:0])
      $fatal(1,"FULL_FF_NOT_AUTHENTIC_FIRST_DESCRIPTOR_CONTEXT");
    load_exact({fixture_root,"/actual_codes_i8.bin"},2048,codes);load_exact({fixture_root,"/actual_feature_archive.bin"},768,features);
    load_exact({fixture_root,"/row_units.bin"},4544,row_units);load_exact({fixture_root,"/down_scale_deltas.bin"},1024,down_scales);
    for(integer index=0;index<4544;index++)if(row_units[index]!==8'd0)$fatal(1,"FULL_FF_NONSCALAR_ROW_UNIT_TABLE");
    for(integer index=0;index<1024;index++)if(down_scales[index]!==8'd0)$fatal(1,"FULL_FF_NONSCALAR_DOWN_SCALE_TABLE");
    load_exact({weight_root,"/gate_signs_group_major.bin"},1441792,gate_signs);load_exact({weight_root,"/up_signs_group_major.bin"},1441792,up_signs);
    load_exact({weight_root,"/gate_full_i8.bin"},11534336,gate_weights);load_exact({weight_root,"/up_full_i8.bin"},11534336,up_weights);load_exact({weight_root,"/down_full_i8.bin"},11534336,down_weights);
    load_exact({golden_root,"/actual_C_raw.bin"},8192,expected_raw_bytes);load_exact({golden_root,"/actual_C_down_input.bin"},5632,expected_down_input);
    $readmemh({golden_root,"/expected_groups.hex"},expected_groups);
    for(integer index=0;index<176;index++)
      if($isunknown(expected_groups[index]))$fatal(1,"FULL_FF_UNKNOWN_OR_MISSING_CHECK_ONLY_GROUP index=%0d",index);
    $readmemh({golden_root,"/expected_keep_packets.hex"},expected_keep);
    for(integer index=0;index<71;index++)
      if($isunknown(expected_keep[index]))$fatal(1,"FULL_FF_UNKNOWN_OR_MISSING_CHECK_ONLY_KEEP index=%0d",index);
    for(integer index=0;index<5632;index++)begin scratch[index]='x;scratch_committed[index]=0;end
    load_exact({seam_input_root,"/actual_original_raw_i32_le.bin"},8192,original_raw);
    load_exact({seam_input_root,"/actual_original_metadata_le.bin"},16,original_metadata);
    load_exact({seam_input_root,"/actual_PRE1_gamma_i24_le.bin"},6144,pre1_gamma);
    if(context_words[4]!=264 || context_words[5]!=264 || context_words[7]!=0 || context_words[8]!=0 || context_words[3]!=5 || context_words[1]!=0 || context_words[2]!=1)
      $fatal(1,"RAW32_RESIDUAL_NOT_ACTUAL_264_FIRST_IMAGE_CONTEXT");
    seam_job.source_tag=context_words[0][31:0];seam_job.source_layer=0;seam_job.source_epoch=1;
    seam_job.original_root=0;seam_job.source_rank=0;seam_job.kept_rank=0;seam_job.image_start=5;seam_job.input_count=264;seam_job.kept_count=264;
    seam_job.bundle={context_words[19],context_words[20]};seam_job.phase=1;seam_job.normalization_role=1;
    seam_job.raw_unit=-8'sd30;seam_job.epsilon=64'd755578637259143234;seam_job.down_unit=context_words[25][11:0];
    seam_job.raw_base=OLD_RAW;seam_job.raw_bytes=RAW_EXTENT;seam_job.metadata_base=OLD_META;seam_job.metadata_bytes=META_EXTENT;seam_job.down_table_base=DOWN_SCALE;
    seam_job.down_scratch_base=DOWN_SCRATCH;seam_job.down_scratch_bytes=8192;
    seam_job.target_raw_base=TARGET_RAW;seam_job.target_raw_bytes=RAW_EXTENT;seam_job.target_metadata_base=TARGET_META;seam_job.target_metadata_bytes=META_EXTENT;
    seam_job.target_gamma_base=PRE1_GAMMA;seam_job.target_gamma_bytes=6144;seam_job.target_gamma_exponent=-8'sd23;
    seam_job.target_layer=1;seam_job.target_epoch=2;seam_job.target_tag_base=TARGET_TAG;seam_job.target_count=264;seam_job.target_role=0;
    seam_job.target_rank=0;seam_job.gamma_table_base=PRE1_GAMMA-64'd12288;seam_job.gamma_table_bytes=64'd276480;seam_job.target_gamma_index=2;
    seam_job.activation_unit=context_words[9][8:0];seam_job.gate_weight_unit=context_words[10][8:0];
    seam_job.up_weight_unit=context_words[11][8:0];seam_job.down_weight_unit=context_words[12][8:0];
    seam_job.gate_shift=context_words[21][5:0];seam_job.up_shift=context_words[22][5:0];seam_job.down_shift=context_words[23][5:0];seam_job.gain=context_words[24][8:0];
    seam_job.gain_cap=context_words[17][8:0];seam_job.down_offset=context_words[18][8:0];
    for(integer bucket=0;bucket<4;bucket++)if(bucket<int'(context_words[13][2:0]) &&
      $signed(context_words[14][bucket*9+:9])==$signed(context_words[9][8:0]))begin
        seam_job.gain_cap=context_words[15][bucket*9+:9];seam_job.down_offset=context_words[16][bucket*9+:9];
    end
    seam_job.protected_count=12;
    seam_job.protected_base[0]=64'h20000000;seam_job.protected_bytes[0]=2048;
    seam_job.protected_base[1]=64'h40000000;seam_job.protected_bytes[1]=442368;
    seam_job.protected_base[2]=GATE_SIG;seam_job.protected_bytes[2]=1441792;
    seam_job.protected_base[3]=UP_SIG;seam_job.protected_bytes[3]=1441792;
    seam_job.protected_base[4]=GATE_W;seam_job.protected_bytes[4]=11534336;
    seam_job.protected_base[5]=UP_W;seam_job.protected_bytes[5]=11534336;
    seam_job.protected_base[6]=DOWN_W;seam_job.protected_bytes[6]=11534336;
    seam_job.protected_base[7]=ROW_UNITS;seam_job.protected_bytes[7]=4544;
    seam_job.protected_base[8]=SCRATCH;seam_job.protected_bytes[8]=5632;
    seam_job.protected_base[9]=DOWN_SCALE;seam_job.protected_bytes[9]=1024;
    seam_job.protected_base[10]=OLD_RAW;seam_job.protected_bytes[10]=RAW_EXTENT;
    seam_job.protected_base[11]=OLD_META;seam_job.protected_bytes[11]=META_EXTENT;
    for(integer index=0;index<8192;index++)begin down_scratch[index]='x;down_committed[index]=0;end
    for(integer index=0;index<2203648;index++)begin target_raw[index]='x;target_raw_committed[index]=0;end
    for(integer index=0;index<4224;index++)begin target_metadata[index]='x;target_meta_committed[index]=0;end
    repeat(4)@(negedge clk);rst_n=1;repeat(3)@(negedge clk);seam_cfg_valid=1;
    limit=0;forever begin @(posedge clk);if(seam_cfg_ready)break;limit++;if(limit>50)$fatal(1,"RAW32_RESIDUAL_PREFLIGHT_CFG_NOT_ACCEPTED");end
    @(negedge clk);seam_cfg_valid=0;
    limit=0;while(!seam_launch && limit<5000)begin @(negedge clk);limit++;end
    if(!seam_launch || seam_table_words!=128 || seam_metadata_words!=2 || seam_fault || adapter_cfg_fires!=0)
      $fatal(1,"RAW32_RESIDUAL_PREFLIGHT_FAILED_BEFORE_ADAPTER");
    $display("RAW32_RESIDUAL_PREFLIGHT_OK table_words=%0d metadata_words=%0d input_count=264 target_count=264 raw_unit=-30 epsilon=755578637259143234 PRE1_gamma_exponent=-23",seam_table_words,seam_metadata_words);$fflush();
    a_cfg_valid=1;
    limit=0;
    forever begin @(posedge clk);if(a_cfg_ready)break;limit++;if(limit>50)$fatal(1,"FULL_FF_ADAPTER_CFG_NOT_ACCEPTED");end
    @(negedge clk);a_cfg_valid=0;
    // Full continuation: all13 genuine packets must traverse actual ACKed
    // scratch and residual storage before metadata can publish the first C row.
    limit=0;while(!seam_done && limit<63500000)begin @(negedge clk);limit++;end
    if(!seam_done)$fatal(1,"RAW32_RESIDUAL_COMPLETE_NATIVE_PROGRESS_MISSING packets=%0d scratch=%0d raw=%0d metadata=%0d Cstrips=%0d",raw_packets,scratch_write_responses,raw_write_responses,metadata_write_responses,c_strips);
    if(raw_packets!=13 || raw_values!=2048 || group_results!=176 || mask_fires!=71 || write_responses!=71 || write_bytes!=5632 ||
       adapter_cfg_fires!=1 || frame_cfg_fires!=1 || !pred_done_seen || !row_context || !next_context_owned || next_release ||
       scratch_write_requests!=128 || scratch_write_responses!=128 || raw_write_requests!=128 || raw_write_responses!=128 ||
       metadata_write_requests!=1 || metadata_write_responses!=1 || commit_write_requests!=257 || commit_write_responses!=257 || commit_write_bytes!=16400 ||
       seam_scratch_acks!=128 || seam_raw_acks!=128 || !seam_metadata_ack || !seam_native_drained ||
       c_cfg_fires!=1 || c_demand_fires!=1 || c_retire_fires!=0 || c_strips!=256 || c_accepted!=1 || c_completed!=1 ||
       !c_demand_ready || c_idle || !c_producer_idle || !c_port_idle || c_valid || c_req || c_rsp ||
       seam_done_error || seam_done_tag!==TARGET_TAG || seam_held_job.target_count!=264 || seam_held_job.target_rank!=0 ||
       seam_table_words!=128 || seam_metadata_words!=2 || metadata_ack_delay_cycles<12 || commit_request_stalls<1 || commit_data_stalls<1)
      $fatal(1,"RAW32_RESIDUAL_COMPLETE_NATIVE_TERMINAL_TUPLE");
    check_census();
    for(integer feature=0;feature<2048;feature++)if(!observed_down_present[feature])$fatal(1,"RAW32_RESIDUAL_MISSING_ACTUAL_DOWN_LANE");
    // Retain both Done tuples under explicit backpressure. Parent and native C
    // still own all264 frame slots; only one first row has been completed.
    repeat(8)@(negedge clk);
    if(!seam_done || seam_done_error || seam_done_tag!==TARGET_TAG || !a_done || a_error || held_done_cycles<8 ||
       !row_context || !next_context_owned || next_release || !c_demand_ready || c_idle || c_retire_fires!=0 ||
       c_accepted!=1 || c_completed!=1 || c_valid || c_req || c_rsp || !c_producer_idle || !c_port_idle)
      $fatal(1,"RAW32_RESIDUAL_HELD_COMPLETE_DONE_RETRACTED");
    $display("RAW32_RESIDUAL_COMPLETE_NATIVE_PASS packets=13 lanes=2048 native_intermediate_ACKs=71 native_intermediate_bytes=5632 scratch_ACKs=128 raw_ACKs=128 metadata_ACKs=1 total_commit_ACKs=257 commit_bytes=16400 Cstrips=256 Caccepted=1 Ccompleted=1 frame_count=264 AwaitDemand=1 owner_held=1 retire=0 done_held=1 unit=%0d epsilon=%0d RAMs=621 PEarrays=20 full_model=0 paper_matching=0 physical_advancement_allowed=0",$signed(seam_selected_unit),seam_selected_epsilon);$fflush();
    $finish;
  end
endmodule

bind TS5N28HPCPSVTA32X128M2FW full_ff_cell_marker #(.ROLE(0)) ff_probe0();
bind TS5N28HPCPSVTA512X64M4F full_ff_cell_marker #(.ROLE(1)) ff_probe1();
bind TS6N28HPCPSVTA16X128M2F full_ff_cell_marker #(.ROLE(2)) ff_probe2();
bind TS5N28HPCPSVTA24X128M2FW full_ff_cell_marker #(.ROLE(3)) ff_probe3();
bind TS5N28HPCPSVTA16X80M2FW full_ff_cell_marker #(.ROLE(4)) ff_probe4();
bind TS5N28HPCPSVTA8X80M2FW full_ff_cell_marker #(.ROLE(5)) ff_probe5();
bind tri_oracle_pe_array full_ff_cell_marker #(.ROLE(6)) ff_probe6();
bind tri_oracle_core_strip448 full_ff_cell_marker #(.ROLE(7)) ff_probe7();
bind tri_oracle_core_head450 full_ff_cell_marker #(.ROLE(8)) ff_probe8();
bind tri_oracle_core_strip448 full_ff_strip_marker ff_actual_transfers(.clk,.rst_n,.request,.response);
bind tri_oracle_pe_array full_ff_pe_marker ff_actual_computes(.clk,.rst_n,.in_valid,.in_ready,.out_valid,.out_ready);
