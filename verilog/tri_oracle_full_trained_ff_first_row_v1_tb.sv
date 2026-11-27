`timescale 1ns/1ps
// Prospective ONE-row composition, genuine FIRST kept rank0 only. Inputs are
// replayed prior physical C/write/descriptor observations, NOT live attention
// or a continuous parent epoch. Expected tensors are scoreboard-only.
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

module tri_oracle_full_trained_ff_tb;
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
  assign ff_ready=rst_n && cycles%5!=2 && (!ff_valid || first_raw_stall_count==3'd4);
  assign pred_done_ready=pred_done && pred_hold>=4;
  assign frame_out_drained=raw_values==2048 && !ff_valid && pred_done_seen &&
    !write_owned && !wr_rsp && !read_owned && !mem_rsp && !client_req_valid[0] && !client_req_valid[1];
  assign next_ready=rst_n && !next_owned && !next_rsp && cycles%3!=1;
  assign next_rsp_error=0;assign next_release_ready=next_context_owned;
  assign mem_ready=rst_n && !read_owned && !mem_rsp && cycles%5!=1 && (!mem_req || first_read_stall_count==3'd4);
  assign mem_error=0;
  assign wr_ready=rst_n && !write_owned && !wr_rsp && mode!=2 && cycles%4!=1;
  assign wr_data_ready=rst_n && write_owned && !write_all && cycles%4!=2;
  assign wr_error=0;

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
    .mem_req_valid(mem_req),.mem_req_ready(mem_ready),.mem_req_address(mem_address),.mem_req_length(mem_length),
    .mem_rsp_valid(mem_rsp),.mem_rsp_ready,.mem_rsp_last(mem_last),.mem_rsp_error(mem_error),.mem_rsp_data(mem_data)
  );
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
  always @(posedge clk or negedge rst_n)begin : actual_intermediate_write_provider
    if(!rst_n)begin write_owned<=0;write_all<=0;wr_rsp<=0;write_address<=0;write_length<=0;write_beat<=0;write_delay<=0;write_requests<=0;write_responses<=0;write_bytes<=0;end
    else begin
      if(wr_req && wr_ready)begin
        if(write_owned || wr_rsp || wr_address!==SCRATCH+64'(write_bytes) || wr_length!=(write_requests==70 ? 4 : 10))
          $fatal(1,"FULL_FF_WRONG_REAL_INTERMEDIATE_WRITE packet=%0d",write_requests);
        write_owned<=1;write_all<=0;write_address<=wr_address;write_length<=wr_length;write_beat<=0;write_delay<=0;write_requests<=write_requests+1;
      end
      if(wr_data_valid && wr_data_ready)begin
        if(!write_owned || write_all || wr_strobe!=8'hff || wr_last!=(write_beat+1==int'(write_length)))$fatal(1,"FULL_FF_BAD_INTERMEDIATE_DATA");
        for(integer lane=0;lane<8;lane++)begin
          write_packet[write_beat*8+lane]<=wr_data[lane*8+:8];
        end
        if(wr_last)write_all<=1;else write_beat<=write_beat+1;
      end
      if(write_owned && write_all && !wr_rsp)begin
        if(write_delay>=3)wr_rsp<=1;else write_delay<=write_delay+1;
      end
      if(wr_rsp && wr_rsp_ready)begin
        // The real ACK commits the actual write bytes to subsequent reads.
        for(integer lane=0;lane<80;lane++)if(lane<int'(write_length)*8)begin
          scratch[int'(write_address-SCRATCH)+lane]<=write_packet[lane];
          scratch_committed[int'(write_address-SCRATCH)+lane]<=1;
        end
        write_bytes<=write_bytes+int'(write_length)*8;write_responses<=write_responses+1;
        write_owned<=0;write_all<=0;wr_rsp<=0;
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
  initial begin
    rst_n=0;abort_valid=0;next_context_owned=1;strip_fabric_owned=1;a_cfg_valid=0;a_done_ready=0;mode=0;
    if(!$value$plusargs("ROW_FIXTURE=%s",fixture_root) || !$value$plusargs("WEIGHT_ROOT=%s",weight_root) || !$value$plusargs("GOLDEN_ROOT=%s",golden_root))
      $fatal(1,"FULL_FF_REQUIRED_ROOT_ARGUMENTS_MISSING");
    if($test$plusargs("FULL_FF_INERT_KEEP"))mode=1;
    if($test$plusargs("FULL_FF_INERT_WRITE"))mode=2;
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
    repeat(4)@(negedge clk);rst_n=1;repeat(3)@(negedge clk);a_cfg_valid=1;
    limit=0;
    forever begin @(posedge clk);if(a_cfg_ready)break;limit++;if(limit>50)$fatal(1,"FULL_FF_ADAPTER_CFG_NOT_ACCEPTED");end
    @(negedge clk);a_cfg_valid=0;
    if(mode==1)begin
      limit=0;while(!mask_valid && limit<1000000)begin @(negedge clk);limit++;end
      if(!mask_valid || frame_cfg_fires!=1)$fatal(1,"FULL_FF_INERT_KEEP_NOT_ARMED");
      repeat(16)@(negedge clk);
      if(mask_fires || raw_values || frame_done || a_done || !a_active)$fatal(1,"FULL_FF_FALSE_DONE_WITHOUT_KEEP");
      $fatal(1,"FULL_TRAINED_FF_EXPECTED_KEEP_HANDSHAKE mask_offer=1 accepted=0 raw=0");
    end
    if(mode==2)begin
      limit=0;while(!wr_req && limit<1000000)begin @(negedge clk);limit++;end
      if(!wr_req || mask_fires<1)$fatal(1,"FULL_FF_INERT_WRITE_NOT_ARMED");
      repeat(16)@(negedge clk);
      if(write_responses || raw_values || frame_done || a_done || !a_active)$fatal(1,"FULL_FF_FALSE_DONE_WITHOUT_INTERMEDIATE_ACK");
      $fatal(1,"FULL_TRAINED_FF_EXPECTED_INTERMEDIATE_WRITE_ACK request_offer=1 accepted=0 raw=0");
    end
    limit=0;while(!a_done && limit<63000000)begin @(negedge clk);limit++;end
    if(!a_done)$fatal(1,"FULL_FF_NO_COMPLETE_ROW_DONE");
    repeat(4)@(negedge clk);check_census();
    if(group_results!=176 || group_live || group_inputs!=0 || raw_packets!=13 || raw_values!=2048 || mask_fires!=71 || write_requests!=71 || write_responses!=71 || write_bytes!=5632 ||
       !pred_done_seen || first_raw_stall_count!==3'd4 || first_read_stall_count!==3'd4 || output_stalls<4 || read_stalls<4)$fatal(1,"FULL_FF_COMPLETE_ROW_CENSUS_FAILED");
    a_done_ready=1;@(posedge clk);@(negedge clk);a_done_ready=0;repeat(4)@(negedge clk);
    // One first-row validation leaves the frame/owner retained for rank1.
    if(a_done || !a_active || a_idle || !next_context_owned || next_release || a_fault || pred_fault ||
       !pred_idle || pred_active || !pred_port_idle || !strip_quiet || read_owned || mem_rsp || write_owned || wr_rsp || ff_valid || frame_done)
      $fatal(1,"FULL_FF_NONFINAL_CONTEXT_OR_TRANSPORT_NOT_RETAINED");
    $display("FULL_TRAINED_FF_FIRST_ROW_PASS rank=0 predictor_results=176 masks=71 intermediate_ACKs=71 intermediate_bytes=5632 raw_packets=13 raw_values=2048 RAMs=621 PEarrays=20 predictor_cores=20 layer=0 context_retained=1 prior_C_fixture=1 full_model=0 recurrence=0 paper_matching=0 physical_advancement_allowed=0 cycles=%0d",cycles);$fflush();
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
