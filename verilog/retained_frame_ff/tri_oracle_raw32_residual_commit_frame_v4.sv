`timescale 1ns/1ps
// Unqualified separate successor. One shared exact155-bit lane path, one packet
// buffer and two line registers; sixteen scalar row contexts spill DOWN into
// disjoint external8192-byte slots. No compute fabric/C/SRAM is instantiated.
module tri_oracle_raw32_residual_commit_frame_v4 (
  input logic clk,rst_n,external_cancel_q,owner_held,parent_fault,
  input logic correction_enable_cfg,
  input logic frame_valid,output logic frame_ready,
  input tri_oracle_FF_frame_types_v2::frame_t frame_context,
  output tri_oracle_FF_frame_types_v2::frame_t held_frame,
  input logic batch_valid,output logic batch_ready,
  input tri_oracle_FF_frame_types_v2::batch_t batch_context,
  output tri_oracle_FF_frame_types_v2::batch_t held_batch,
  output logic batch_launch_valid,input logic batch_launch_ready,
  output tri_oracle_FF_frame_types_v2::native_cfg_t batch_launch_context,
  input logic in_valid,output logic in_ready,
  input logic [31:0] in_tag,input logic [3:0] in_token,
  input logic [15:0] in_start,input logic [7:0] in_count,
  input logic in_last,input logic [5119:0] in_data,
  input logic native_done_fire,native_done_error,input logic [31:0] native_done_tag,
  output logic req_valid,input logic req_ready,
  output logic [63:0] req_address,output logic [4:0] req_length,
  input logic rsp_valid,rsp_last,rsp_error,output logic rsp_ready,
  input logic [63:0] rsp_data,input logic physical_unowned_response,
  output logic write_req_valid,input logic write_req_ready,
  output logic [63:0] write_address,output logic [4:0] write_length,
  output logic write_data_valid,input logic write_data_ready,
  output logic [63:0] write_data,output logic [7:0] write_strobe,
  output logic write_last,input logic write_rsp_valid,write_rsp_error,
  output logic write_rsp_ready,
  output logic c_read_selected,c_cfg_valid,c_demand_valid,c_retire_valid,c_output_ready,
  output logic [9:0] c_demand_rank,c_demand_root,
  input logic c_cfg_ready,c_demand_ready,c_retire_ready,
  input logic c_fault,c_producer_idle,c_port_idle,c_idle,
  input logic [9:0] c_accepted_rows,c_completed_rows,
  input logic c_output_valid,c_read_request_valid,c_read_response_valid,
  input logic c_output_fire,c_output_last,c_output_error,
  input logic [31:0] c_output_tag,input logic [9:0] c_output_index,
  input logic [3:0] c_output_count,
  output logic row_done_valid,row_done_error,input logic row_done_ready,
  output logic [31:0] row_done_tag,output logic [9:0] row_done_rank,
  output logic batch_done_valid,batch_done_error,input logic batch_done_ready,
  output logic frame_done_valid,frame_done_error,input logic frame_done_ready,
  output logic [9:0] completed_rows,
  output logic active,epoch_fault,abort_registered,native_input_drained,
  // Immediate independent RAW/transport failures only: no C/parent response cone.
  output logic independent_admission_fault,
  output logic scratch_ACK,raw_ACK,metadata_ACK,output logic [9:0] ACK_rank
);
  import raw32_residual_math_v1::*;
  import raw32_residual_bindings_v1::*;
  import tri_oracle_FF_frame_types_v2::*;
  typedef enum logic [5:0] {Idle,AwaitBatch,TableSetup,TableWait,MetaSetup,MetaWait,CheckMeta,
    LaunchHold,WaitPacket,ScratchSetup,ScratchWait,OriginalSetup,OriginalWait,PeakLane,
    PeakScaleSetup,PeakScaleWait,WaitNative,SelectUnit,ReplayOriginalSetup,ReplayOriginalWait,ReplayDownSetup,ReplayDownWait,
    ReplayScaleSetup,ReplayScaleWait,RecodeLane,RawSetup,RawWait,PublishSetup,PublishWait,CConfigure,CWaitReset,CDemand,CRun,
    RowDoneHold,BatchDoneHold,RetireSetup,RetireWait,RetireQuiet,FrameDoneHold,FaultDrain,Stopped,Quarantine} state_t;
  state_t state;
  frame_t saved_frame;
  batch_t saved_batch;
  native_cfg_t saved_launch;
  logic frame_active,poison_q,fresh_work,quarantine_q;
  logic correction_enable_saved;
  logic [2:0] maximum_decrement,table_word_max,lane_decrement;
  logic [47:0] scale_word;
  logic scale_response_bad,lane_math_bad;
  logic signed [8:0] lane_common_unit;
  logic signed [11:0] lane_unit;
  logic launch_offer,launch_accepted,native_terminal_seen,native_success,accepted_complete,spool_complete;
  logic target_configured,target_retired,c_cfg_offer,c_demand_offer,c_retire_offer,c_demand_seen;
  logic read_offer,read_owned,write_offer,write_owned,write_all;
  logic [63:0] read_address,write_address_saved;
  logic [4:0] read_length,write_length_saved;
  logic [3:0] read_beat,write_beat,table_burst,preflight_token,packet_token,packet_line,publish_token;
  logic [3:0] expected_group,expected_token,packet_group;
  logic [7:0] line_index;
  logic [3:0] lane;
  logic [8:0] table_words,native_packets,c_strips;
  logic [1:0] metadata_words;
  logic [5119:0] packet_buffer;
  logic [511:0] residual_buffer,write_buffer;
  logic [127:0] source_metadata,target_metadata;
  logic [15:0] metadata_checked,peak_complete;
  logic signed [7:0] raw_units[0:15];
  logic [63:0] raw_epsilons[0:15];
  logic signed [11:0] down_units[0:15];
  logic signed [8:0] common_units[0:15];
  logic [154:0] peaks[0:15];
  logic [8:0] scratch_acks[0:15],raw_acks[0:15];
  logic [15:0] metadata_acks;
  logic signed [7:0] unit_scan,selected_unit;
  logic [63:0] selected_epsilon;
  logic [9:0] committed_rows,last_root,last_upstream_rank;
  logic last_row_seen;
  logic [31:0] current_target_tag;
  logic [9:0] current_rank;
  logic signed [31:0] raw_lane,down_lane;
  logic signed [154:0] lane_sum;
  logic [154:0] lane_magnitude;
  recode_t recoded;
  logic frame_bad,batch_bad,packet_bad,metadata_bad,lane_bad,c_health_bad,c_status_bad;
  logic read_fire,read_response_fire,read_complete,write_fire,data_fire,ACK_fire;
  logic frame_fire,batch_fire,launch_fire,c_cfg_fire,c_demand_fire,c_retire_fire;
  logic controls_ambiguous,response_association_bad,response_payload_bad,native_bad,c_output_bad;
  logic local_bad,raw_local_bad,raw_controls_ambiguous,quiet_owned,c_quiet,all_spooled;
  logic [7:0] fault_observations;

  function automatic logic overlap(input logic [63:0] a,b,input logic [64:0] ae,be);
    return {1'b0,a}<=be && {1'b0,b}<=ae;
  endfunction
  function automatic scalar_policy_t policy(input frame_t f,input row_t r);
    return derive_scalar_policy(int'($signed(r.activation_unit)),int'($signed(f.common.gate_weight_unit)),
      int'($signed(f.common.up_weight_unit)),int'($signed(f.common.down_weight_unit)),
      bound_gain_cap(int'(f.common.source_layer),int'($signed(r.activation_unit))),
      bound_down_offset(int'(f.common.source_layer),int'($signed(r.activation_unit))));
  endfunction
  function automatic logic valid_frame(input frame_t f,input logic correction_mode);
    logic bad;
    logic [63:0] wbase[0:3],ibase[0:11];
    logic [64:0] wend[0:3],iend[0:11],e;
    integer B;
    B=int'(f.common.kept_count)>16 ? 16:int'(f.common.kept_count);
    bad=$isunknown({f,correction_mode}) || f.common.phase!=1 || f.common.normalization_role!=1 || f.common.source_layer>=22 ||
      f.common.kept_count==0 || f.common.kept_count>576 || f.common.input_count!=f.common.kept_count ||
      f.common.target_count!=f.common.kept_count || f.upstream_input_count!=f.common.input_count ||
      11'(f.common.image_start)+11'd575>1023 || 33'(f.common.source_tag)+33'd575>33'hffffffff ||
      33'(f.common.target_tag_base)+33'd575>33'hffffffff ||
      int'($signed(f.common.gate_weight_unit))!=bound_weight_unit(int'(f.common.source_layer),0) ||
      int'($signed(f.common.up_weight_unit))!=bound_weight_unit(int'(f.common.source_layer),1) ||
      int'($signed(f.common.down_weight_unit))!=bound_weight_unit(int'(f.common.source_layer),2) ||
      f.common.raw_base[5:0]!=0 || f.common.raw_bytes[5:0]!=0 ||
      65'(f.common.raw_bytes)<(65'(f.common.image_start)+65'(f.common.input_count))*8192 ||
      f.common.metadata_base[3:0]!=0 || f.common.metadata_bytes[3:0]!=0 || 65'(f.common.metadata_bytes)<65'(f.common.input_count)*16 ||
      f.common.target_raw_base[5:0]!=0 || f.common.target_raw_bytes[5:0]!=0 ||
      65'(f.common.target_raw_bytes)<(65'(f.common.image_start)+65'(f.common.target_count))*8192 ||
      f.common.target_metadata_base[3:0]!=0 || f.common.target_metadata_bytes[3:0]!=0 || 65'(f.common.target_metadata_bytes)<65'(f.common.target_count)*16 ||
      f.common.down_scratch_base[5:0]!=0 || f.common.down_scratch_bytes[5:0]!=0 || 65'(f.common.down_scratch_bytes)<65'(B)*8192 ||
      f.intermediate_base[5:0]!=0 || 65'(f.intermediate_bytes)<65'(B)*5632*(correction_mode ? 65'd2:65'd1) ||
      f.post_code_base[5:0]!=0 || f.post_feature_base[5:0]!=0 || 65'(f.post_feature_bytes)<65'(f.common.kept_count)*768 ||
      f.gate_base[2:0]!=0 || f.up_base[2:0]!=0 || f.down_base[2:0]!=0 ||
      f.gate_sign_base[5:0]!=0 || f.up_sign_base[5:0]!=0 || f.gate_sign_bytes!=1441792 || f.up_sign_bytes!=1441792 ||
      f.row_units_base[5:0]!=0 || f.row_units_bytes!=4544 || f.common.down_table_base[2:0]!=0 ||
      f.common.gamma_table_base[2:0]!=0 || f.common.gamma_table_bytes!=276480 ||
      f.common.target_gamma_base[2:0]!=0 || f.common.target_gamma_bytes!=6144 ||
      (f.common.source_layer==21 ? (f.common.target_layer!=21 || f.common.target_role!=2 || f.common.target_gamma_index!=44) :
        (f.common.target_layer!=f.common.source_layer+1 || f.common.target_role!=0 || f.common.target_gamma_index!=2*(f.common.source_layer+1))) ||
      65'(f.common.target_gamma_base)!=65'(f.common.gamma_table_base)+65'(f.common.target_gamma_index)*6144 ||
      int'($signed(f.common.target_gamma_exponent))!=bound_gamma_unit(int'(f.common.target_gamma_index)) ||
      f.common.protected_count==0 || f.common.protected_count>16;
    // Epoch is an explicit held published context, NOT source_epoch+1.
    wbase[0]=f.common.down_scratch_base;wend[0]=65'(wbase[0])+65'(f.common.down_scratch_bytes)-1;
    wbase[1]=f.common.target_raw_base;wend[1]=65'(wbase[1])+65'(f.common.target_raw_bytes)-1;
    wbase[2]=f.common.target_metadata_base;wend[2]=65'(wbase[2])+65'(f.common.target_metadata_bytes)-1;
    wbase[3]=f.intermediate_base;wend[3]=65'(wbase[3])+65'(f.intermediate_bytes)-1;
    ibase[0]=f.common.raw_base;iend[0]=65'(ibase[0])+65'(f.common.raw_bytes)-1;
    ibase[1]=f.common.metadata_base;iend[1]=65'(ibase[1])+65'(f.common.metadata_bytes)-1;
    ibase[2]=f.common.down_table_base;iend[2]=65'(ibase[2])+1023;
    ibase[3]=f.common.gamma_table_base;iend[3]=65'(ibase[3])+65'(f.common.gamma_table_bytes)-1;
    ibase[4]=f.post_code_base;iend[4]=65'(ibase[4])+65'(f.common.kept_count)*2048-1;
    ibase[5]=f.post_feature_base;iend[5]=65'(ibase[5])+65'(f.post_feature_bytes)-1;
    ibase[6]=f.gate_base;iend[6]=65'(ibase[6])+11534335;
    ibase[7]=f.up_base;iend[7]=65'(ibase[7])+11534335;
    ibase[8]=f.down_base;iend[8]=65'(ibase[8])+11534335;
    ibase[9]=f.gate_sign_base;iend[9]=65'(ibase[9])+65'(f.gate_sign_bytes)-1;
    ibase[10]=f.up_sign_base;iend[10]=65'(ibase[10])+65'(f.up_sign_bytes)-1;
    ibase[11]=f.row_units_base;iend[11]=65'(ibase[11])+65'(f.row_units_bytes)-1;
    for(integer w=0;w<4;w++)begin
      if(wend[w][64])bad=1;
      for(integer j=0;j<4;j++)if(w<j && overlap(wbase[w],wbase[j],wend[w],wend[j]))bad=1;
      for(integer j=0;j<12;j++)if(iend[j][64] || overlap(wbase[w],ibase[j],wend[w],iend[j]))bad=1;
      for(integer j=0;j<16;j++)if(j<int'(f.common.protected_count))begin
        e=65'(f.common.protected_base[j])+65'(f.common.protected_bytes[j])-1;
        if(f.common.protected_bytes[j]==0 || e[64])bad=1;
        // A declared native intermediate extent is writable by its real native
        // owner, but remains protected against this consumer's other3 writes.
        if(!(w==3 && f.common.protected_base[j]==f.intermediate_base && f.common.protected_bytes[j]==f.intermediate_bytes) &&
          overlap(wbase[w],f.common.protected_base[j],wend[w],e))bad=1;
      end
    end
    return !bad;
  endfunction
  function automatic logic valid_batch(input frame_t f,input batch_t b,input logic [9:0] next_rank,
      previous_root,previous_upstream,input logic have_previous);
    logic bad;scalar_policy_t p;logic [32:0] tag_sum;
    bad=$isunknown(b) || b.start_rank!=next_rank || b.start_rank>=f.common.kept_count ||
      b.tokens!=(int'(f.common.kept_count)-int'(b.start_rank)>16 ? 5'd16:5'(f.common.kept_count-b.start_rank)) ||
      b.tag!=f.common.source_tag+32'(b.start_rank);
    for(integer t=0;t<16;t++)begin
      if(t<int'(b.tokens))begin
        p=policy(f,b.rows[t]);tag_sum=33'(f.common.source_tag)+33'(b.rows[t].upstream_input_rank);
        if(b.rows[t].frame_rank!=b.start_rank+10'(t) || b.rows[t].raw_input_rank!=b.rows[t].upstream_input_rank ||
          b.rows[t].raw_input_rank>=f.common.input_count || b.rows[t].upstream_input_rank>=f.upstream_input_count ||
          b.rows[t].original_root>=576 || 11'(f.common.image_start)+11'(b.rows[t].original_root)>1023 ||
          11'(f.common.image_start)+11'(b.rows[t].original_root)==0 || tag_sum[32] || b.rows[t].source_tag!=tag_sum[31:0] ||
          !p.valid || !supported_down(int'($signed(p.down_unit))))bad=1;
        if(t==0 && have_previous && (b.rows[t].original_root<=previous_root || b.rows[t].upstream_input_rank<=previous_upstream))bad=1;
        if(t>0 && (b.rows[t].original_root<=b.rows[t-1].original_root || b.rows[t].upstream_input_rank<=b.rows[t-1].upstream_input_rank))bad=1;
      end else if(b.rows[t]!=='0)bad=1;
    end
    return !bad;
  endfunction

  // Operand inputs are pure projections of registered context/buffers. This
  // block never reads the lane response, RAW response classification or Parent.
  always_comb begin
    raw_lane=$signed(residual_buffer[int'(lane)*32+:32]);
    down_lane=$signed(write_buffer[int'(lane)*32+:32]);
    lane_decrement=maximum_decrement==0 ? 3'd0:scale_word[int'(lane)*3+:3];
  end
  tri_oracle_calibrated_raw32_lane_v1 lane_alignment (
    .raw_value(raw_lane),.down_value(down_lane),
    .raw_unit(raw_units[state==PeakLane ? packet_token:publish_token]),
    .base_down_unit(down_units[state==PeakLane ? packet_token:publish_token]),
    .maximum_decrement,.lane_decrement,.correction_enable(correction_enable_saved),
    .bad(lane_math_bad),.common_unit(lane_common_unit),.lane_unit,
    .exact_sum(lane_sum),.magnitude(lane_magnitude)
  );
  // Pure physical-response classification; it cannot feed its own producer.
  always_comb begin
    table_word_max=0;
    scale_response_bad=$isunknown(rsp_data) || rsp_data[63:48]!==16'd0;
    if(!$isunknown(rsp_data))begin
      for(integer k=0;k<16;k++)begin
        if(rsp_data[k*3+:3]>table_word_max)table_word_max=rsp_data[k*3+:3];
        if((state==PeakScaleWait || state==ReplayScaleWait) && rsp_data[k*3+:3]>maximum_decrement)scale_response_bad=1;
      end
    end
  end

  tri_oracle_FF_registered_poison_v1 #(.FaultBits(8)) poison (
    .clk,.rst_n,.active(frame_active),.owner_held,.external_cancel_q,
    .fault_observations,.poison_q,.abort_registered,.fresh_work_permitted(fresh_work)
  );
  // Pure projections of registered state. No Parent response/ready/health
  // input belongs to this producer block; returning C request fields therefore
  // cannot be re-triggered by a packed Parent response's intermediate writes.
  always_comb begin
    batch_launch_valid=(rst_n===1'b1) && launch_offer;
    held_frame=saved_frame;held_batch=saved_batch;batch_launch_context=saved_launch;
    active=frame_active;epoch_fault=poison_q || quarantine_q;completed_rows=committed_rows;
    current_rank=saved_batch.start_rank+10'(publish_token);
    current_target_tag=saved_frame.common.target_tag_base+32'(current_rank);
    frame_bad=!valid_frame(frame_context,correction_enable_cfg);
    batch_bad=!valid_batch(saved_frame,batch_context,committed_rows,last_root,last_upstream_rank,last_row_seen);
    c_cfg_valid=(rst_n===1'b1) && c_cfg_offer;c_demand_valid=(rst_n===1'b1) && c_demand_offer;c_retire_valid=(rst_n===1'b1) && c_retire_offer;
    c_read_selected=(rst_n===1'b1) && frame_active && target_configured && !target_retired;
    c_output_ready=(rst_n===1'b1) && c_read_selected && (state==CRun || poison_q) && !quarantine_q;
    c_demand_rank=current_rank;c_demand_root=saved_batch.rows[publish_token].original_root;
  end
  // RAW/native/physical-memory cone ONLY. In particular packet_bad's bounded
  // default/override scan cannot re-run merely because a Parent C/Size response
  // was rewritten. The current RAW fault fences new logical admission directly.
  always_comb begin
    req_valid=(rst_n===1'b1) && read_offer;req_address=read_address;req_length=read_length;
    rsp_ready=(rst_n===1'b1) && read_owned && !quarantine_q;
    write_req_valid=(rst_n===1'b1) && write_offer;write_address=write_address_saved;write_length=write_length_saved;
    write_data_valid=(rst_n===1'b1) && write_owned && !write_all;
    write_data=write_buffer[int'(write_beat)*64+:64];write_strobe=8'hff;write_last=write_beat+1==write_length_saved;
    write_rsp_ready=(rst_n===1'b1) && write_owned && write_all && !quarantine_q;
    read_fire=req_valid && (req_ready===1'b1);read_response_fire=(rsp_valid===1'b1) && rsp_ready;read_complete=read_response_fire && rsp_last;
    write_fire=write_req_valid && (write_req_ready===1'b1);data_fire=write_data_valid && (write_data_ready===1'b1);ACK_fire=(write_rsp_valid===1'b1) && write_rsp_ready;
    quiet_owned=!read_offer && !read_owned && !write_offer && !write_owned && (rsp_valid===1'b0) && (write_rsp_valid===1'b0);
    packet_bad=$isunknown({in_tag,in_token,in_start,in_count,in_last}) || in_tag!=saved_batch.tag ||
      in_token!=expected_token || in_start!=16'(expected_group)*160 ||
      in_count!=(expected_group==12 ? 128:160) || in_last!=(expected_group==12 && expected_token+1==saved_batch.tokens);
    for(integer k=0;k<160;k++)if(k<int'(in_count) && $isunknown(in_data[k*32+:32]))packet_bad=1;
    all_spooled=spool_complete;
    for(integer t=0;t<16;t++)if(t<int'(saved_batch.tokens) && (!metadata_checked[t] || !peak_complete[t] || scratch_acks[t]!=128))all_spooled=0;
    native_input_drained=(rst_n===1'b1) && all_spooled && !poison_q;
    native_bad=(native_done_fire===1'b1) && (!launch_accepted || native_terminal_seen || native_done_error!==1'b0 ||
      native_done_tag!=saved_batch.tag || !accepted_complete || in_valid!==1'b0 || $isunknown(native_done_tag));
    metadata_bad=$isunknown(source_metadata) || source_metadata[127:123]!=0 ||
      source_metadata[122:107]!=saved_frame.common.source_epoch || source_metadata[106:102]!=saved_frame.common.source_layer ||
      source_metadata[101:92]!=saved_frame.common.image_start+saved_batch.rows[preflight_token].original_root ||
      source_metadata[91:82]!=saved_batch.rows[preflight_token].raw_input_rank ||
      source_metadata[81:72]!=saved_batch.rows[preflight_token].original_root ||
      $signed(source_metadata[71:64])< -32 || $signed(source_metadata[71:64])>97 ||
      source_metadata[63:0]!=physical_epsilon($signed(source_metadata[71:64]));
    lane_bad=lane_math_bad || lane_common_unit!==common_units[state==PeakLane ? packet_token:publish_token];
    recoded=calibrated_raw32_recode_math_v1::recode_once_155(lane_sum,int'($signed(common_units[publish_token])),int'($signed(selected_unit)));
    target_metadata={5'd0,saved_frame.common.target_epoch,saved_frame.common.target_layer,
      10'(saved_frame.common.image_start+saved_batch.rows[publish_token].original_root),current_rank,
      saved_batch.rows[publish_token].original_root,selected_unit,selected_epsilon};
    raw_controls_ambiguous=(state==Idle && ($isunknown(frame_valid) || (frame_valid===1'b1 && $isunknown({owner_held,correction_enable_cfg})))) ||
      (state==AwaitBatch && $isunknown(batch_valid)) ||
      (frame_active && $isunknown({in_valid,native_done_fire})) ||
      ((read_offer && $isunknown(req_ready)) || (write_offer && $isunknown(write_req_ready)) || (write_data_valid && $isunknown(write_data_ready))) ||
      ((rst_n===1'b1) && $isunknown({rsp_valid,write_rsp_valid,native_done_fire,physical_unowned_response}));
    response_association_bad=(physical_unowned_response===1'b1) || ((rsp_valid===1'b1) && !read_owned) ||
      ((write_rsp_valid===1'b1) && (!write_owned || !write_all)) ||
      (read_response_fire && rsp_last!==(read_beat+1==read_length));
    response_payload_bad=(read_response_fire && (rsp_error!==1'b0 || $isunknown({rsp_data,rsp_last}))) ||
      (ACK_fire && write_rsp_error!==1'b0);
    // This cone intentionally excludes parent_fault, C status/ready/output and
    // all C-derived health checks. Only independent saved context, native data,
    // RAW memory responses and local arithmetic may fence fresh Parent admission.
    raw_local_bad=(state==Idle && frame_valid===1'b1 && frame_bad) ||
      (state==AwaitBatch && batch_valid===1'b1 && batch_bad) ||
      (state==WaitPacket && in_valid===1'b1 && packet_bad) ||
      (accepted_complete && in_valid===1'b1 && !poison_q) || native_bad ||
      ((state==PeakLane || state==RecodeLane) && lane_bad) || (state==RecodeLane && recoded.bad) ||
      (read_response_fire && (state==TableWait || state==PeakScaleWait || state==ReplayScaleWait) && scale_response_bad) ||
      (state==CheckMeta && (metadata_bad || table_words!=128 || metadata_words!=2)) ||
      (state==PublishSetup && (scratch_acks[publish_token]!=128 || raw_acks[publish_token]!=128 || !native_success));
    independent_admission_fault=raw_controls_ambiguous || response_association_bad || response_payload_bad || raw_local_bad;
    scratch_ACK=ACK_fire && state==ScratchWait && write_rsp_error===1'b0;
    raw_ACK=ACK_fire && state==RawWait && write_rsp_error===1'b0;
    metadata_ACK=ACK_fire && state==PublishWait && write_rsp_error===1'b0;
    ACK_rank=saved_batch.start_rank+10'(state==ScratchWait ? packet_token:publish_token);
  end
  // Response/control observations may affect REGISTERED state/poison only.
  // They never procedurally write a returning packed request-field producer.
  always_comb begin
    launch_fire=batch_launch_valid && (batch_launch_ready===1'b1);
    c_quiet=(c_output_valid===1'b0) && (c_read_request_valid===1'b0) && (c_read_response_valid===1'b0) &&
      (c_producer_idle===1'b1) && (c_port_idle===1'b1);
    c_health_bad=$isunknown({c_idle,c_producer_idle,c_port_idle,c_accepted_rows,c_completed_rows,c_fault,
      c_output_valid,c_read_request_valid,c_read_response_valid}) || (c_fault!==1'b0);
    c_status_bad=0;
    if(frame_active && !target_configured)begin
      c_status_bad=((c_idle!==1'b0) && (c_idle!==1'b1)) ||
        (c_cfg_offer!==1'b1 && c_idle!==1'b1) ||
        (c_cfg_offer===1'b1 && c_cfg_ready===1'b1 && c_idle!==1'b0) ||
        !c_quiet || c_accepted_rows!=saved_frame.common.kept_count || c_completed_rows!=saved_frame.common.kept_count;
    end else if(frame_active && target_configured && !target_retired)begin
      if(c_idle!==1'b0 || c_accepted_rows<committed_rows || c_completed_rows<committed_rows ||
        c_accepted_rows>committed_rows+10'd1 || c_completed_rows>c_accepted_rows)c_status_bad=1;
      if(state!=CRun && state!=CDemand && (c_accepted_rows!=committed_rows || c_completed_rows!=committed_rows || !c_quiet))c_status_bad=1;
    end else if(frame_active && target_retired)begin
      if(c_idle!==1'b1 || !c_quiet || c_accepted_rows!=saved_frame.common.kept_count || c_completed_rows!=saved_frame.common.kept_count)c_status_bad=1;
    end
    // Public ready never depends on a fault generated from its own handshake.
    // Invalid payload denies admission and latches poison directly from valid.
    frame_ready=(rst_n===1'b1) && state==Idle && !poison_q && !quarantine_q &&
      (owner_held===1'b1) && (external_cancel_q===1'b0) && (parent_fault===1'b0) &&
      !frame_bad && !c_health_bad && (c_idle===1'b1) && c_quiet &&
      c_accepted_rows==frame_context.common.kept_count && c_completed_rows==frame_context.common.kept_count;
    batch_ready=(rst_n===1'b1) && state==AwaitBatch && !poison_q && !quarantine_q &&
      (owner_held===1'b1) && (external_cancel_q===1'b0) && (parent_fault===1'b0) && !batch_bad && !c_health_bad && !c_status_bad;
    frame_fire=(frame_valid===1'b1) && frame_ready;batch_fire=(batch_valid===1'b1) && batch_ready;
    in_ready=(rst_n===1'b1) && !quarantine_q && launch_accepted &&
      ((state==WaitPacket && !poison_q && (parent_fault===1'b0) && (external_cancel_q===1'b0) && owner_held===1'b1) ||
       (poison_q && !native_terminal_seen));
    c_cfg_fire=c_cfg_valid && (c_cfg_ready===1'b1);c_demand_fire=c_demand_valid && (c_demand_ready===1'b1);c_retire_fire=c_retire_valid && (c_retire_ready===1'b1);
    c_output_bad=(c_output_fire===1'b1) && (!c_demand_seen || c_output_valid!==1'b1 || c_strips>=256 ||
      c_output_tag!=current_target_tag || c_output_index!=10'(c_strips) || c_output_count!=8 ||
      c_output_last!=(c_strips==255) || c_output_error!==1'b0 || $isunknown({c_output_tag,c_output_index,c_output_count,c_output_last}));
    controls_ambiguous=raw_controls_ambiguous || (state==Idle && $isunknown(frame_valid)) || (state==AwaitBatch && $isunknown(batch_valid)) ||
      (frame_active && $isunknown({owner_held,external_cancel_q,parent_fault,in_valid,native_done_fire,c_output_fire})) ||
      ((read_offer && $isunknown(req_ready)) || (write_offer && $isunknown(write_req_ready)) || (write_data_valid && $isunknown(write_data_ready))) ||
      ((rst_n===1'b1) && $isunknown({rsp_valid,write_rsp_valid,native_done_fire,physical_unowned_response})) ||
      (launch_offer && $isunknown(batch_launch_ready)) || (c_cfg_offer && $isunknown(c_cfg_ready)) ||
      (c_demand_offer && $isunknown(c_demand_ready)) || (c_retire_offer && $isunknown(c_retire_ready)) ||
      (row_done_valid && $isunknown(row_done_ready)) || (batch_done_valid && $isunknown(batch_done_ready)) || (frame_done_valid && $isunknown(frame_done_ready));
    local_bad=(state==Idle && frame_valid===1'b1 && (frame_bad || c_health_bad || c_accepted_rows!=frame_context.common.kept_count || c_completed_rows!=frame_context.common.kept_count)) ||
      (state==AwaitBatch && batch_valid===1'b1 && batch_bad) ||
      (state==WaitPacket && in_valid===1'b1 && packet_bad) ||
      (accepted_complete && in_valid===1'b1 && !poison_q) || native_bad ||
      (frame_active && (c_health_bad || c_status_bad)) || c_output_bad ||
      ((state==PeakLane || state==RecodeLane) && lane_bad) || (state==RecodeLane && recoded.bad) ||
      (read_response_fire && (state==TableWait || state==PeakScaleWait || state==ReplayScaleWait) && scale_response_bad) ||
      (state==CheckMeta && (metadata_bad || table_words!=128 || metadata_words!=2)) ||
      (state==PublishSetup && (scratch_acks[publish_token]!=128 || raw_acks[publish_token]!=128 || !native_success));
    fault_observations={2'b0,quarantine_q,(parent_fault!==1'b0),controls_ambiguous,response_association_bad,response_payload_bad,local_bad};
  end

  always_ff @(posedge clk or negedge rst_n)begin
    if(rst_n===1'b0)begin
      state<=Idle;saved_frame<='0;saved_batch<='0;saved_launch<='0;frame_active<=0;quarantine_q<=0;
      correction_enable_saved<=0;maximum_decrement<=0;scale_word<='0;
      launch_offer<=0;launch_accepted<=0;native_terminal_seen<=0;native_success<=0;accepted_complete<=0;spool_complete<=0;
      target_configured<=0;target_retired<=0;c_cfg_offer<=0;c_demand_offer<=0;c_retire_offer<=0;c_demand_seen<=0;
      read_offer<=0;read_owned<=0;write_offer<=0;write_owned<=0;write_all<=0;read_address<=0;write_address_saved<=0;
      read_length<=0;write_length_saved<=0;read_beat<=0;write_beat<=0;table_burst<=0;preflight_token<=0;packet_token<=0;packet_line<=0;publish_token<=0;
      expected_group<=0;expected_token<=0;packet_group<=0;line_index<=0;lane<=0;table_words<=0;native_packets<=0;c_strips<=0;metadata_words<=0;
      packet_buffer<=0;residual_buffer<=0;write_buffer<=0;source_metadata<=0;metadata_checked<=0;peak_complete<=0;metadata_acks<=0;
      unit_scan<=-8'sd32;selected_unit<=0;selected_epsilon<=0;committed_rows<=0;last_root<=0;last_upstream_rank<=0;last_row_seen<=0;
      row_done_valid<=0;row_done_error<=0;row_done_tag<=0;row_done_rank<=0;batch_done_valid<=0;batch_done_error<=0;frame_done_valid<=0;frame_done_error<=0;
      for(integer t=0;t<16;t++)begin raw_units[t]<=0;raw_epsilons[t]<=0;down_units[t]<=0;common_units[t]<=0;peaks[t]<=0;scratch_acks[t]<=0;raw_acks[t]<=0;end
    end else begin
      // Exposed transport advances only by known handshakes, even on faults.
      if(read_fire)begin read_offer<=0;read_owned<=1;read_beat<=0;end
      if(read_response_fire)begin
        if(state==TableWait)begin
          table_words<=table_words+1'b1;
          if(!scale_response_bad && !response_payload_bad && !response_association_bad && table_word_max>maximum_decrement)maximum_decrement<=table_word_max;
        end
        if((state==PeakScaleWait || state==ReplayScaleWait) && !scale_response_bad && !response_payload_bad && !response_association_bad)scale_word<=rsp_data[47:0];
        if(state==MetaWait)begin source_metadata[int'(read_beat)*64+:64]<=rsp_data;metadata_words<=metadata_words+1'b1;end
        if(state==OriginalWait || state==ReplayOriginalWait)residual_buffer[int'(read_beat)*64+:64]<=rsp_data;
        if(state==ReplayDownWait)write_buffer[int'(read_beat)*64+:64]<=rsp_data;
        if(rsp_last && !response_association_bad)read_owned<=0;else if(read_beat<15)read_beat<=read_beat+1'b1;
      end
      if(write_fire)begin write_offer<=0;write_owned<=1;write_all<=0;write_beat<=0;end
      if(data_fire)begin if(write_last)write_all<=1;else write_beat<=write_beat+1'b1;end
      if(ACK_fire)begin write_owned<=0;write_all<=0;end
      if(launch_fire)begin launch_offer<=0;launch_accepted<=1;end
      if(c_cfg_fire)begin c_cfg_offer<=0;target_configured<=1;end
      if(c_demand_fire)begin c_demand_offer<=0;c_demand_seen<=1;end
      if(c_retire_fire)begin c_retire_offer<=0;target_retired<=1;end
      if(c_output_fire===1'b1 && !c_output_bad)c_strips<=c_strips+1'b1;
      if(native_done_fire===1'b1 && launch_accepted && !native_terminal_seen && native_done_tag==saved_batch.tag && !$isunknown({native_done_tag,native_done_error}))begin
        native_terminal_seen<=1;
        if(native_done_error===1'b0 && accepted_complete && in_valid===1'b0 && !poison_q && !local_bad && !controls_ambiguous && !response_association_bad)native_success<=1;
      end
      if(in_valid===1'b1 && in_ready)begin
        native_packets<=native_packets+1'b1;
        if(expected_token+1==saved_batch.tokens)begin expected_token<=0;expected_group<=expected_group+1'b1;end
        else expected_token<=expected_token+1'b1;
        if(expected_group==12 && expected_token+1==saved_batch.tokens)accepted_complete<=1;
      end
      // Terminal transfers are transport events, not revocable healthy grants.
      // A late fault preserves the tuple but cannot cause it to be accepted
      // repeatedly. Faulted acceptance never rearms a frame or releases lease.
      if(row_done_valid && row_done_ready===1'b1)begin
        row_done_valid<=0;
        if(!fresh_work || poison_q)state<=quarantine_q ? Quarantine:FaultDrain;
      end
      if(batch_done_valid && batch_done_ready===1'b1)begin
        batch_done_valid<=0;
        if(!fresh_work || poison_q)state<=quarantine_q ? Quarantine:FaultDrain;
      end
      if(frame_done_valid && frame_done_ready===1'b1)begin
        frame_done_valid<=0;
        if(!fresh_work || poison_q)state<=Stopped;
      end
      if(controls_ambiguous || response_association_bad)begin quarantine_q<=1;state<=Quarantine;end
      if(fresh_work && !quarantine_q)begin
        case(state)
          Idle:if(frame_fire)begin saved_frame<=frame_context;correction_enable_saved<=correction_enable_cfg;frame_active<=1;committed_rows<=0;target_configured<=0;target_retired<=0;last_row_seen<=0;state<=AwaitBatch;end
          AwaitBatch:if(batch_fire)begin
            saved_batch<=batch_context;preflight_token<=0;table_burst<=0;table_words<=0;metadata_words<=0;
            maximum_decrement<=0;scale_word<='0;
            metadata_checked<=0;peak_complete<=0;metadata_acks<=0;expected_group<=0;expected_token<=0;native_packets<=0;
            launch_accepted<=0;native_terminal_seen<=0;native_success<=0;accepted_complete<=0;spool_complete<=0;
            saved_launch.row_enable<=1;saved_launch.correction_enable<=correction_enable_saved;saved_launch.tag<=batch_context.tag;saved_launch.tokens<=batch_context.tokens;
            saved_launch.input_features<=2048;saved_launch.intermediate_features<=5632;saved_launch.output_features<=2048;
            saved_launch.activation_base<=saved_frame.post_code_base+64'(batch_context.start_rank)*2048;saved_launch.activation_stride<=2048;
            saved_launch.gate_base<=saved_frame.gate_base;saved_launch.up_base<=saved_frame.up_base;saved_launch.down_base<=saved_frame.down_base;
            saved_launch.intermediate_base<=saved_frame.intermediate_base;saved_launch.row_units_base<=saved_frame.row_units_base;
            for(integer t=0;t<16;t++)begin
              scalar_policy_t p;
              p=policy(saved_frame,batch_context.rows[t]);
              peaks[t]<=0;scratch_acks[t]<=0;raw_acks[t]<=0;raw_units[t]<=0;raw_epsilons[t]<=0;common_units[t]<=0;
              down_units[t]<=t<int'(batch_context.tokens) ? p.down_unit:12'sd0;
              saved_launch.gate_shifts[t*6+:6]<=t<int'(batch_context.tokens) ? p.gate_shift[5:0]:6'd0;
              saved_launch.up_shifts[t*6+:6]<=t<int'(batch_context.tokens) ? p.up_shift[5:0]:6'd0;
              saved_launch.down_shifts[t*6+:6]<=t<int'(batch_context.tokens) ? p.down_shift[5:0]:6'd0;
            end
            state<=TableSetup;
          end
          TableSetup:begin read_address<=saved_frame.common.down_table_base+64'(table_burst)*64;read_length<=8;read_offer<=1;state<=TableWait;end
          TableWait:if(read_complete)begin if(table_burst==15)state<=MetaSetup;else begin table_burst<=table_burst+1'b1;state<=TableSetup;end end
          MetaSetup:begin source_metadata<=0;metadata_words<=0;read_address<=saved_frame.common.metadata_base+64'(saved_batch.rows[preflight_token].raw_input_rank)*16;read_length<=2;read_offer<=1;state<=MetaWait;end
          MetaWait:if(read_complete)state<=CheckMeta;
          CheckMeta:if(!metadata_bad && table_words==128 && metadata_words==2)begin
            raw_units[preflight_token]<=$signed(source_metadata[71:64]);raw_epsilons[preflight_token]<=source_metadata[63:0];
            common_units[preflight_token]<=int'($signed(source_metadata[71:64]))<int'($signed(down_units[preflight_token]))-int'({1'b0,maximum_decrement}) ?
              9'($signed(source_metadata[71:64])):9'(int'($signed(down_units[preflight_token]))-int'({1'b0,maximum_decrement}));
            metadata_checked[preflight_token]<=1;
            if(preflight_token+1==saved_batch.tokens)begin launch_offer<=1;state<=LaunchHold;end
            else begin preflight_token<=preflight_token+1'b1;state<=MetaSetup;end
          end
          LaunchHold:if(launch_fire)state<=WaitPacket;
          WaitPacket:if(in_valid===1'b1 && in_ready)begin packet_buffer<=in_data;packet_token<=in_token;packet_group<=expected_group;packet_line<=0;line_index<=8'(expected_group)*10;state<=ScratchSetup;end
          ScratchSetup:begin write_buffer<=packet_buffer[int'(packet_line)*512+:512];write_address_saved<=saved_frame.common.down_scratch_base+64'(packet_token)*8192+64'(line_index)*64;write_length_saved<=8;write_offer<=1;state<=ScratchWait;end
          ScratchWait:if(ACK_fire)begin scratch_acks[packet_token]<=scratch_acks[packet_token]+1'b1;state<=OriginalSetup;end
          OriginalSetup:begin read_address<=saved_frame.common.raw_base+(64'(saved_frame.common.image_start)+64'(saved_batch.rows[packet_token].raw_input_rank))*8192+64'(line_index)*64;read_length<=8;read_offer<=1;state<=OriginalWait;end
          OriginalWait:if(read_complete)begin
            if(maximum_decrement==0)begin lane<=0;state<=PeakLane;end
            else state<=PeakScaleSetup;
          end
          PeakScaleSetup:begin read_address<=saved_frame.common.down_table_base+64'(line_index)*8;read_length<=1;read_offer<=1;state<=PeakScaleWait;end
          PeakScaleWait:if(read_complete)begin lane<=0;state<=PeakLane;end
          PeakLane:begin
            if(lane_magnitude>peaks[packet_token])peaks[packet_token]<=lane_magnitude;
            if(lane==15)begin
              if(line_index==127)peak_complete[packet_token]<=1;
              if(packet_line==(packet_group==12 ? 7:9))begin
                if(packet_group==12 && packet_token+1==saved_batch.tokens)begin spool_complete<=1;state<=WaitNative;end
                else state<=WaitPacket;
              end else begin packet_line<=packet_line+1'b1;line_index<=line_index+1'b1;state<=ScratchSetup;end
            end else lane<=lane+1'b1;
          end
          WaitNative:if(native_success && all_spooled && quiet_owned)begin publish_token<=0;unit_scan<=-8'sd32;state<=SelectUnit;end
          SelectUnit:begin
            if(peaks[publish_token]==0)begin selected_unit<=0;selected_epsilon<=physical_epsilon(8'sd0);line_index<=0;state<=ReplayOriginalSetup;end
            else if(calibrated_raw32_recode_math_v1::unit_fits_155(peaks[publish_token],int'($signed(common_units[publish_token])),int'($signed(unit_scan))))begin selected_unit<=unit_scan;selected_epsilon<=physical_epsilon(unit_scan);line_index<=0;state<=ReplayOriginalSetup;end
            else if(unit_scan==8'sd97)begin quarantine_q<=1;state<=Quarantine;end
            else unit_scan<=unit_scan+8'sd1;
          end
          ReplayOriginalSetup:begin read_address<=saved_frame.common.raw_base+(64'(saved_frame.common.image_start)+64'(saved_batch.rows[publish_token].raw_input_rank))*8192+64'(line_index)*64;read_length<=8;read_offer<=1;state<=ReplayOriginalWait;end
          ReplayOriginalWait:if(read_complete)state<=ReplayDownSetup;
          ReplayDownSetup:begin read_address<=saved_frame.common.down_scratch_base+64'(publish_token)*8192+64'(line_index)*64;read_length<=8;read_offer<=1;state<=ReplayDownWait;end
          ReplayDownWait:if(read_complete)begin
            if(maximum_decrement==0)begin lane<=0;state<=RecodeLane;end
            else state<=ReplayScaleSetup;
          end
          ReplayScaleSetup:begin read_address<=saved_frame.common.down_table_base+64'(line_index)*8;read_length<=1;read_offer<=1;state<=ReplayScaleWait;end
          ReplayScaleWait:if(read_complete)begin lane<=0;state<=RecodeLane;end
          RecodeLane:begin packet_buffer[int'(lane)*32+:32]<=recoded.code;if(lane==15)state<=RawSetup;else lane<=lane+1'b1;end
          RawSetup:begin write_buffer<=packet_buffer[511:0];write_address_saved<=saved_frame.common.target_raw_base+(64'(saved_frame.common.image_start)+64'(current_rank))*8192+64'(line_index)*64;write_length_saved<=8;write_offer<=1;state<=RawWait;end
          RawWait:if(ACK_fire)begin raw_acks[publish_token]<=raw_acks[publish_token]+1'b1;if(line_index==127)state<=PublishSetup;else begin line_index<=line_index+1'b1;state<=ReplayOriginalSetup;end end
          PublishSetup:if(scratch_acks[publish_token]==128 && raw_acks[publish_token]==128 && native_success)begin write_buffer<={384'd0,target_metadata};write_address_saved<=saved_frame.common.target_metadata_base+64'(current_rank)*16;write_length_saved<=2;write_offer<=1;state<=PublishWait;end
          PublishWait:if(ACK_fire)begin metadata_acks[publish_token]<=1;if(!target_configured)state<=CConfigure;else state<=CDemand;end
          CConfigure:begin
            if(!c_cfg_offer && c_idle===1'b1 && c_quiet && c_accepted_rows==saved_frame.common.kept_count && c_completed_rows==saved_frame.common.kept_count)c_cfg_offer<=1;
            if(c_cfg_fire)state<=CWaitReset;
          end
          CWaitReset:if(c_idle===1'b0 && c_quiet && c_accepted_rows==0 && c_completed_rows==0)state<=CDemand;
          CDemand:begin
            if(!c_demand_offer && !c_demand_seen && metadata_acks[publish_token] && c_quiet && c_accepted_rows==current_rank && c_completed_rows==current_rank)begin c_demand_offer<=1;c_strips<=0;end
            if(c_demand_fire)state<=CRun;
          end
          CRun:if(c_strips==256 && c_accepted_rows==current_rank+10'd1 && c_completed_rows==current_rank+10'd1 && c_quiet && quiet_owned)begin
            committed_rows<=current_rank+10'd1;last_root<=saved_batch.rows[publish_token].original_root;
            last_upstream_rank<=saved_batch.rows[publish_token].upstream_input_rank;last_row_seen<=1;
            row_done_valid<=1;row_done_error<=0;row_done_rank<=current_rank;row_done_tag<=current_target_tag;state<=RowDoneHold;
          end
          RowDoneHold:if(row_done_valid && row_done_ready===1'b1)begin
            row_done_valid<=0;c_demand_seen<=0;
            if(publish_token+1==saved_batch.tokens)begin batch_done_valid<=1;batch_done_error<=0;state<=BatchDoneHold;end
            else begin publish_token<=publish_token+1'b1;unit_scan<=-8'sd32;state<=SelectUnit;end
          end
          BatchDoneHold:if(batch_done_valid && batch_done_ready===1'b1)begin
            batch_done_valid<=0;state<=committed_rows==saved_frame.common.kept_count ? RetireSetup:AwaitBatch;
          end
          RetireSetup:if(committed_rows==saved_frame.common.kept_count && c_quiet && quiet_owned &&
            c_accepted_rows==saved_frame.common.kept_count && c_completed_rows==saved_frame.common.kept_count)begin c_retire_offer<=1;state<=RetireWait;end
          RetireWait:if(c_retire_fire)state<=RetireQuiet;
          RetireQuiet:if(target_retired && c_idle===1'b1 && c_quiet && quiet_owned && c_accepted_rows==saved_frame.common.kept_count && c_completed_rows==saved_frame.common.kept_count)begin frame_done_valid<=1;frame_done_error<=0;state<=FrameDoneHold;end
          FrameDoneHold:if(frame_done_valid && frame_done_ready===1'b1)begin frame_done_valid<=0;frame_active<=0;state<=Idle;end
          default:begin end
        endcase
      end
      if((poison_q || !fresh_work) && frame_active && state!=Stopped && !quarantine_q && !controls_ambiguous && !response_association_bad)begin
        if(state!=FrameDoneHold && state!=RowDoneHold && state!=BatchDoneHold)state<=FaultDrain;
        if(state!=FrameDoneHold && quiet_owned && !launch_offer && !c_cfg_offer && !c_demand_offer && !c_retire_offer &&
          (!launch_accepted || native_terminal_seen) && c_quiet && !row_done_valid && !batch_done_valid && !frame_done_valid)begin
          frame_done_valid<=1;frame_done_error<=1;state<=FrameDoneHold;
        end
      end
      // No late fault rewrites an exposed row/batch/frame Done tuple. No owner
      // release exists here; only the real full-count C retirement is emitted.
    end
  end
endmodule
