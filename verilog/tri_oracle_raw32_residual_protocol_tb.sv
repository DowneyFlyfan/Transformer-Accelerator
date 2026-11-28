`timescale 1ns/1ps
// Finite consumer protocol controls only. These synthetic peers are deliberately
// distinct from raw32_residual_full_native_tb_v1.sv and grant no native arithmetic
// or C normalization qualification. No simulator has run this source yet.
// SOURCE ONLY v3 preserves v2 cases0..79 and adds completion timing80..87.
// Case80 deliberately pulses producer Done before the last128 scratch drain;
// it must NOT delay Done until native_input_drained or ACK128. No body fix here.
module raw32_residual_protocol_tb;
  import raw32_residual_commit_types_v1::*;
  localparam logic[63:0] OLD_RAW=64'h80000000,OLD_META=64'h81000000,TABLE=64'h75000000;
  localparam logic[63:0] SPOOL=64'h82000000,TARGET_RAW=64'h83000000,TARGET_META=64'h84000000,GAMMA=64'h85003000;
  logic clk=0,rst_n=0,abort_valid,owner_held,cfg_valid,cfg_ready;
  job_t cfg_job,held_job;
  logic launch_allowed,active,epoch_fault,native_input_drained,row_context_valid;
  logic[31:0]row_tag;logic[4:0]row_layer;logic[15:0]row_epoch;
  logic[9:0]row_root,row_input_rank,row_kept_rank;logic[127:0]row_bundle;
  logic signed[11:0]row_down_unit;logic[63:0]row_down_table;
  logic signed[8:0]row_activation_unit,row_gain;logic[5:0]row_gate_shift,row_up_shift,row_down_shift;
  logic in_valid,in_ready;logic[31:0]in_tag;logic[3:0]in_token;logic[15:0]in_start;logic[7:0]in_count;
  logic in_last;logic[5119:0]in_data;
  logic native_done_fire,native_done_error;logic[31:0]native_done_tag;
  logic req_valid,req_ready;logic[63:0]req_address;logic[4:0]req_length;
  logic rsp_valid,rsp_last,rsp_error,rsp_ready;logic[63:0]rsp_data;logic physical_unowned_response;
  logic write_req_valid,write_req_ready;logic[63:0]write_address;logic[4:0]write_length;
  logic write_data_valid,write_data_ready;logic[63:0]write_data;logic[7:0]write_strobe;
  logic write_last,write_rsp_valid,write_rsp_error,write_rsp_ready;
  logic c_read_selected,c_cfg_valid,c_demand_valid,c_retire_valid,c_cfg_ready,c_demand_ready,c_retire_ready;
  logic c_fault,c_producer_idle,c_port_idle,c_idle;logic[9:0]c_accepted_rows,c_completed_rows;
  logic c_output_valid,c_read_request_valid,c_read_response_valid,c_output_fire,c_output_last,c_output_error;
  logic[31:0]c_output_tag;logic[9:0]c_output_index;logic[3:0]c_output_count;
  logic row_done_valid,row_done_error,row_done_ready;logic[31:0]row_done_tag;
  logic[7:0]table_words;logic[1:0]metadata_words;logic packet_captured;logic[5119:0]held_packet;
  logic signed[7:0]selected_raw_unit;logic[63:0]selected_epsilon;logic[8:0]scratch_ack_count,raw_ack_count;
  logic metadata_acknowledged;
  logic read_owned,write_owned,write_all,provider_ack,inject_ack,allow_read_request,allow_write_request,allow_write_data,allow_write_ack;
  logic malformed_last,malformed_sent,drain_block,c_configured,c_busy,force_c_active;
  integer table_corruption_mode,unknown_C_kind;
  logic poison_raw_min,injected_c_fault,poison_rsp_valid,poison_rsp_error,poison_rsp_last,poison_rsp_data,poison_write_error,poison_c_fire,poison_c_tag;
  logic provider_rsp_valid,provider_rsp_last;logic[63:0]provider_rsp_data;
  logic[9:0]stub_c_accepted_rows,stub_c_completed_rows;
  logic[63:0]read_address,write_address_saved;logic[4:0]read_length_saved,write_length_saved;
  integer read_beat,write_beat,ack_delay,cycles,which,wait_cycles;
  integer read_requests,read_beat_fires,write_requests,write_data_fires,metadata_write_requests,write_acks,scratch_acks,raw_acks,meta_acks,c_cfg_count,c_demand_count,c_strip_count;
  integer request_stalls,data_stalls,ack_stalls,metadata_pending_cycles;
  logic held_request,held_data,held_read_request,held_read_rsp;logic[68:0]saved_request,saved_read_request;logic[72:0]saved_data;logic[65:0]saved_read_rsp;
  logic[127:0]original_metadata;
  logic[68:0]unknown_request_snapshot;logic[72:0]unknown_data_snapshot;logic[65:0]unknown_response_snapshot;
  job_t unknown_job_snapshot;logic[32:0]unknown_done_snapshot;
  // Public-interface witnesses only; no hierarchical DUT state is inspected.
  integer timing_packets,timing_final_accepts,timing_done_pulses;
  integer timing_final_cycle,timing_first_done_cycle;
  always @(posedge clk or negedge rst_n)begin
    if(!rst_n)begin
      timing_packets<=0;timing_final_accepts<=0;timing_done_pulses<=0;
      timing_final_cycle<=-1;timing_first_done_cycle<=-1;
    end else if(which>=80 && which<=87)begin
      if(in_valid===1'b1 && in_ready===1'b1)begin
        if(in_start!==16'(160*timing_packets) || in_count!==(timing_packets==12 ? 8'd128:8'd160) ||
           in_last!==(timing_packets==12) || timing_packets>=13)
          $fatal(1,"PROTOCOL_COMPLETION_PACKET_WITNESS_BAD case=%0d",which);
        timing_packets<=timing_packets+1;
        if(in_last===1'b1)begin timing_final_accepts<=timing_final_accepts+1;timing_final_cycle<=cycles;end
      end
      if(native_done_fire===1'b1)begin
        if(timing_done_pulses==0)timing_first_done_cycle<=cycles;
        timing_done_pulses<=timing_done_pulses+1;
      end
      if(write_req_valid===1'b1 &&
         ((write_address>=TARGET_RAW && write_address<TARGET_RAW+2203648) || write_address==TARGET_META))begin
        if(scratch_ack_count!==9'd128 || scratch_acks!=128 || native_input_drained!==1'b1 ||
           timing_packets!=13 || timing_final_accepts!=1 || timing_done_pulses!=1)
          $fatal(1,"PROTOCOL_PUBLICATION_BEFORE_COMPLETE_SCRATCH_OR_PRODUCER case=%0d scratch=%0d pulse=%0d",which,scratch_acks,timing_done_pulses);
      end
    end
  end
  tri_oracle_raw32_residual_commit_v1 dut(.*);
  always #5 clk=~clk;
  assign req_ready=rst_n && allow_read_request && !read_owned && !rsp_valid && cycles%3!=1;
  assign write_req_ready=rst_n && allow_write_request && !write_owned && !provider_ack && cycles%4!=1;
  assign write_data_ready=rst_n && allow_write_data && write_owned && !write_all && cycles%4!=2;
  assign write_rsp_valid=provider_ack || inject_ack;
  assign write_rsp_error=poison_write_error ? 1'bx:1'b0;
  assign rsp_error=poison_rsp_error ? 1'bx:1'b0;
  assign rsp_valid=poison_rsp_valid ? 1'bx:provider_rsp_valid;
  assign rsp_last=poison_rsp_last ? 1'bx:provider_rsp_last;
  assign rsp_data=poison_rsp_data ? 64'bx:provider_rsp_data;
  assign c_accepted_rows=unknown_C_kind==38 ? 10'bx:stub_c_accepted_rows;
  assign c_completed_rows=unknown_C_kind==39 ? 10'bx:stub_c_completed_rows;
  assign c_cfg_ready=unknown_C_kind==60 ? 1'bx:rst_n && !c_configured;
  assign c_demand_ready=unknown_C_kind==61 ? 1'bx:rst_n && c_configured && !c_busy;
  assign c_retire_ready=c_configured && !c_busy;
  assign c_fault=injected_c_fault;assign c_producer_idle=unknown_C_kind==33 ? 1'bx:!c_busy;assign c_port_idle=unknown_C_kind==34 ? 1'bx:!c_busy;
  assign c_idle=unknown_C_kind==32 ? 1'bx:!c_configured && !c_busy && !force_c_active;
  assign c_read_request_valid=unknown_C_kind==36 ? 1'bx:1'b0;assign c_read_response_valid=unknown_C_kind==37 ? 1'bx:drain_block && c_completed_rows==1;
  assign c_output_valid=unknown_C_kind==35 ? 1'bx:c_busy && cycles%4!=1;
  assign c_output_fire=poison_c_fire ? 1'bx:c_output_valid && cycles%3!=2;
  assign c_output_last=c_strip_count==255;assign c_output_error=0;
  assign c_output_tag=poison_c_tag ? 32'bx:held_job.target_tag_base+32'(held_job.target_rank);
  assign c_output_index=10'(c_strip_count);assign c_output_count=8;

  function automatic logic[63:0] response_word(input logic[63:0]address);
    if(address==OLD_META+64'(cfg_job.source_rank)*16)return original_metadata[63:0];
    if(address==OLD_META+64'(cfg_job.source_rank)*16+8)return original_metadata[127:64];
    if(address==TABLE && table_corruption_mode==1)return 64'd1;
    if(address==TABLE && table_corruption_mode==2)return 64'h0100000000000000;
    if(poison_raw_min && address==OLD_RAW+(64'(cfg_job.image_start)+64'(cfg_job.original_root))*8192)return 64'h0000000080000000;
    return 0; // Synthetic zero table/original/DOWN peers, protocol controls only.
  endfunction
  always @(posedge clk or negedge rst_n)begin
    if(!rst_n)begin
      cycles<=0;read_owned<=0;provider_rsp_valid<=0;provider_rsp_last<=0;provider_rsp_data<=0;read_address<=0;read_length_saved<=0;read_beat<=0;malformed_sent<=0;
      write_owned<=0;write_all<=0;provider_ack<=0;write_address_saved<=0;write_length_saved<=0;write_beat<=0;ack_delay<=0;
      read_requests<=0;read_beat_fires<=0;write_requests<=0;write_data_fires<=0;metadata_write_requests<=0;write_acks<=0;scratch_acks<=0;raw_acks<=0;meta_acks<=0;
      request_stalls<=0;data_stalls<=0;ack_stalls<=0;metadata_pending_cycles<=0;held_request<=0;held_data<=0;held_read_request<=0;held_read_rsp<=0;saved_read_request<=0;saved_read_rsp<=0;saved_request<=0;saved_data<=0;
      c_configured<=0;c_busy<=0;stub_c_accepted_rows<=0;stub_c_completed_rows<=0;c_cfg_count<=0;c_demand_count<=0;c_strip_count<=0;
    end else begin
      cycles<=cycles+1;if(cycles>200000)$fatal(1,"PROTOCOL_WATCHDOG case=%0d",which);
      if(c_retire_valid)$fatal(1,"PROTOCOL_PARENT_FRAME_RETIRED");
      if(held_read_request && (!req_valid || {req_address,req_length}!==saved_read_request))$fatal(1,"PROTOCOL_EXPOSED_READ_REQUEST_CHANGED");
      if(held_read_rsp && (!rsp_valid || {rsp_data,rsp_last,rsp_error}!==saved_read_rsp))$fatal(1,"PROTOCOL_PEER_HELD_READ_RESPONSE_CHANGED");
      held_read_request<=req_valid && !req_ready;saved_read_request<={req_address,req_length};
      held_read_rsp<=rsp_valid && !rsp_ready;saved_read_rsp<={rsp_data,rsp_last,rsp_error};
      if(held_request && (!write_req_valid || {write_address,write_length}!==saved_request))$fatal(1,"PROTOCOL_EXPOSED_WRITE_REQUEST_CHANGED");
      if(held_data && (!write_data_valid || {write_data,write_strobe,write_last}!==saved_data))$fatal(1,"PROTOCOL_EXPOSED_WRITE_DATA_CHANGED");
      held_request<=write_req_valid && !write_req_ready;saved_request<={write_address,write_length};
      held_data<=write_data_valid && !write_data_ready;saved_data<={write_data,write_strobe,write_last};
      if(write_req_valid && !write_req_ready)request_stalls<=request_stalls+1;
      if(write_data_valid && !write_data_ready)data_stalls<=data_stalls+1;
      if(write_owned && write_all && !provider_ack)ack_stalls<=ack_stalls+1;
      if(req_valid && req_ready)begin
        if(read_owned || rsp_valid || req_length==0 || req_length>16)$fatal(1,"PROTOCOL_PEER_READ_ASSOCIATION");
        read_owned<=1;read_address<=req_address;read_length_saved<=req_length;read_beat<=0;read_requests<=read_requests+1;
      end
      if(read_owned && !rsp_valid)begin
        provider_rsp_valid<=1;provider_rsp_data<=response_word(read_address+64'(read_beat)*8);
        provider_rsp_last<=malformed_last && !malformed_sent ? 1'b1 : read_beat+1==int'(read_length_saved);
        if(malformed_last && !malformed_sent)malformed_sent<=1;
      end
      if(rsp_valid && rsp_ready)begin
        read_beat_fires<=read_beat_fires+1;provider_rsp_valid<=0;
        if(read_beat+1==int'(read_length_saved))read_owned<=0;else read_beat<=read_beat+1;
      end
      if(write_req_valid && write_req_ready)begin
        if(write_owned || provider_ack || write_length==0 || write_length>8)$fatal(1,"PROTOCOL_PEER_WRITE_ASSOCIATION");
        write_owned<=1;write_all<=0;write_address_saved<=write_address;write_length_saved<=write_length;write_beat<=0;ack_delay<=0;write_requests<=write_requests+1;
        if(write_address==TARGET_META)metadata_write_requests<=metadata_write_requests+1;
      end
      if(write_data_valid && write_data_ready)begin
        write_data_fires<=write_data_fires+1;
        if(!write_owned || write_all || write_strobe!=8'hff || write_last!==(write_beat+1==int'(write_length_saved)))$fatal(1,"PROTOCOL_PEER_WRITE_LAST");
        if(write_last)write_all<=1;else write_beat<=write_beat+1;
      end
      if(write_owned && write_all && !provider_ack)begin
        if(write_address_saved==TARGET_META)metadata_pending_cycles<=metadata_pending_cycles+1;
        if(allow_write_ack && ack_delay>=(write_address_saved==TARGET_META ? 12:3))provider_ack<=1;else ack_delay<=ack_delay+1;
      end
      if(provider_ack && write_rsp_ready)begin
        write_acks<=write_acks+1;provider_ack<=0;write_owned<=0;write_all<=0;
        if(write_address_saved>=SPOOL && write_address_saved<SPOOL+8192)scratch_acks<=scratch_acks+1;
        else if(write_address_saved>=TARGET_RAW+5*8192 && write_address_saved<TARGET_RAW+6*8192)raw_acks<=raw_acks+1;
        else if(write_address_saved==TARGET_META)meta_acks<=meta_acks+1;
        else $fatal(1,"PROTOCOL_UNDECLARED_WRITE_REGION");
      end
      if((c_cfg_valid || c_demand_valid || c_read_selected) && (meta_acks!=1 || write_acks!=257 || !metadata_acknowledged))$fatal(1,"PROTOCOL_C_PUBLISHED_BEFORE_ACK");
      if(c_cfg_valid && c_cfg_ready)begin c_configured<=1;c_cfg_count<=c_cfg_count+1;if(held_job.target_count!=264)$fatal(1,"PROTOCOL_FRAME_COUNT_NOT264");end
      if(c_demand_valid && c_demand_ready)begin c_busy<=1;c_demand_count<=c_demand_count+1;stub_c_accepted_rows<=stub_c_accepted_rows+1;end
      if(c_output_fire)begin
        c_strip_count<=c_strip_count+1;
        if(c_strip_count==255)begin c_busy<=0;stub_c_completed_rows<=stub_c_completed_rows+1;end
      end
      if(row_done_valid && !row_done_error && (c_completed_rows!=1 || c_strip_count!=256 || c_read_response_valid || c_output_valid || c_busy))$fatal(1,"PROTOCOL_DONE_IGNORED_VISIBLE_C_DRAIN");
    end
  end

  task automatic initialize();
    abort_valid=0;owner_held=1;cfg_valid=0;cfg_job='0;row_context_valid=1;in_valid=0;in_tag=32'h504f0000;in_token=0;in_start=0;in_count=160;in_last=0;in_data=0;
    native_done_fire=0;native_done_error=0;native_done_tag=32'h504f0000;row_done_ready=0;physical_unowned_response=0;
    inject_ack=0;force_c_active=0;table_corruption_mode=0;unknown_C_kind=0;poison_raw_min=0;
    injected_c_fault=0;poison_rsp_valid=0;poison_rsp_error=0;poison_rsp_last=0;poison_rsp_data=0;poison_write_error=0;poison_c_fire=0;poison_c_tag=0;allow_read_request=1;allow_write_request=1;allow_write_data=1;allow_write_ack=1;malformed_last=0;drain_block=0;
    cfg_job.source_tag=32'h504f0000;cfg_job.source_layer=0;cfg_job.source_epoch=1;cfg_job.original_root=0;cfg_job.source_rank=0;cfg_job.kept_rank=0;
    cfg_job.image_start=5;cfg_job.input_count=264;cfg_job.kept_count=264;cfg_job.bundle=128'h61a3dfcd3e2764badb04d69a363c734d;cfg_job.phase=1;cfg_job.normalization_role=1;
    cfg_job.raw_unit=-30;cfg_job.epsilon=64'd755578637259143234;cfg_job.down_unit=-17;
    cfg_job.raw_base=OLD_RAW;cfg_job.raw_bytes=2203648;cfg_job.metadata_base=OLD_META;cfg_job.metadata_bytes=4224;cfg_job.down_table_base=TABLE;
    cfg_job.down_scratch_base=SPOOL;cfg_job.down_scratch_bytes=8192;cfg_job.target_raw_base=TARGET_RAW;cfg_job.target_raw_bytes=2203648;
    cfg_job.target_metadata_base=TARGET_META;cfg_job.target_metadata_bytes=4224;cfg_job.target_gamma_base=GAMMA;cfg_job.target_gamma_bytes=6144;cfg_job.target_gamma_exponent=-23;
    cfg_job.target_layer=1;cfg_job.target_epoch=2;cfg_job.target_tag_base=32'h50520000;cfg_job.target_count=264;cfg_job.target_role=0;cfg_job.target_rank=0;
    cfg_job.gamma_table_base=GAMMA-12288;cfg_job.gamma_table_bytes=276480;cfg_job.target_gamma_index=2;
    cfg_job.protected_count=1;cfg_job.protected_base[0]=64'h10000000;cfg_job.protected_bytes[0]=64;
    cfg_job.activation_unit=-6;cfg_job.gate_weight_unit=-8;cfg_job.up_weight_unit=-9;cfg_job.down_weight_unit=-7;
    cfg_job.gain_cap=2;cfg_job.down_offset=-6;cfg_job.gain=2;cfg_job.gate_shift=6;cfg_job.up_shift=5;cfg_job.down_shift=0;
    row_tag=cfg_job.source_tag;row_layer=cfg_job.source_layer;row_epoch=cfg_job.source_epoch;row_root=0;row_input_rank=0;row_kept_rank=0;row_bundle=cfg_job.bundle;
    row_down_unit=cfg_job.down_unit;row_down_table=TABLE;row_activation_unit=cfg_job.activation_unit;row_gain=cfg_job.gain;
    row_gate_shift=cfg_job.gate_shift;row_up_shift=cfg_job.up_shift;row_down_shift=cfg_job.down_shift;
    original_metadata={5'd0,16'd1,5'd0,10'd5,10'd0,10'd0,-8'sd30,64'd755578637259143234};
  endtask
  task automatic reset_pair();rst_n=0;repeat(4)@(negedge clk);rst_n=1;repeat(2)@(negedge clk);endtask
  task automatic admit();
    cfg_valid=1;wait_cycles=0;
    forever begin @(posedge clk);if(cfg_ready)break;wait_cycles++;if(wait_cycles>32)$fatal(1,"PROTOCOL_CFG_TIMEOUT");end
    @(negedge clk);cfg_valid=0;
  endtask
  task automatic await_launch();
    wait_cycles=0;while(!launch_allowed && !epoch_fault && wait_cycles<2000)begin @(negedge clk);wait_cycles++;end
    if(!launch_allowed || table_words!=128 || metadata_words!=2)$fatal(1,"PROTOCOL_PREFLIGHT_TIMEOUT");
  endtask
  task automatic push_packet(input integer packet);
    @(negedge clk);in_valid=1;in_start=16'(160*packet);in_count=packet==12 ? 128:160;in_last=packet==12;
    wait_cycles=0;forever begin @(posedge clk);if(in_ready)break;wait_cycles++;if(wait_cycles>10000)$fatal(1,"PROTOCOL_PACKET_TIMEOUT");end
    @(negedge clk);in_valid=0;
  endtask
  task automatic await_fault_done();
    wait_cycles=0;while(!row_done_valid && wait_cycles<2000)begin @(negedge clk);wait_cycles++;end
    if(!epoch_fault || !row_done_valid || !row_done_error || c_cfg_count!=0 || c_demand_count!=0 || !owner_held)$fatal(1,"PROTOCOL_FAULT_DRAIN_OR_OWNER_FAILED");
  endtask
  task automatic prove_quarantine();
    repeat(12)@(negedge clk);
    if(!epoch_fault || row_done_valid || cfg_ready || in_ready || c_cfg_valid || c_demand_valid || c_retire_valid || !owner_held)
      $fatal(1,"PROTOCOL_UNKNOWN_ASSOCIATION_NOT_QUARANTINED");
    initialize();reset_pair();if(epoch_fault || !cfg_ready)$fatal(1,"PROTOCOL_COUPLED_RESET_DID_NOT_RECOVER");
  endtask
  task automatic require_known_fault(input string reason);
    if(epoch_fault!==1'b1)$fatal(1,"PROTOCOL_UNKNOWN_NOT_KNOWN_FAULT case=%0d reason=%s epoch_fault=%b",which,reason,epoch_fault);
  endtask
  task automatic prove_sticky_failure(input bit held_success_allowed);
    repeat(4)@(negedge clk);
    if(epoch_fault!==1'b1 || c_retire_valid || !owner_held ||
       (!held_success_allowed && row_done_valid && !row_done_error))
      $fatal(1,"PROTOCOL_UNKNOWN_FAULT_RESUMED_HEALTHY case=%0d",which);
  endtask
  task automatic unknown_admission();
    cfg_valid=1;repeat(8)@(negedge clk);
    if(read_requests!=0 || write_requests!=0 || req_valid || write_req_valid || launch_allowed || in_ready || c_cfg_valid || c_demand_valid ||
       (row_done_valid && !row_done_error) || !owner_held || c_retire_valid || !((epoch_fault===1'b1)||(cfg_ready===1'b0)))
      $fatal(1,"PROTOCOL_UNKNOWN_OR_FAULTED_C_ADMISSION_ADVANCED case=%0d",which);
    cfg_valid=0;initialize();reset_pair();if(epoch_fault || !cfg_ready)$fatal(1,"PROTOCOL_UNKNOWN_ADMISSION_RESET_RECOVERY");
  endtask
  task automatic timing_no_publication();
    if(raw_acks!=0 || meta_acks!=0 || metadata_write_requests!=0 || c_cfg_count!=0 || c_demand_count!=0 ||
       c_read_selected || c_retire_valid || !owner_held || row_done_valid)
      $fatal(1,"PROTOCOL_COMPLETION_PREMATURE_PUBLICATION case=%0d",which);
  endtask
  task automatic timing_final_capture();
    for(integer packet=0;packet<13;packet++)push_packet(packet);
    // push_packet returns at the first falling edge after the genuine final
    // ready/valid acceptance. Two more falling edges place the one-cycle Done
    // on the THIRD rising edge after capture, matching the real producer path.
    repeat(2)@(negedge clk);
    if(timing_packets!=13 || timing_final_accepts!=1 || timing_final_cycle<0 ||
       scratch_ack_count!==9'd120 || scratch_acks!=120 || native_input_drained!==1'b0 ||
       row_context_valid!==1'b1 || owner_held!==1'b1 || held_job!==cfg_job || in_valid!==1'b0)
      $fatal(1,"PROTOCOL_COMPLETION_TIMING_PRECONDITION case=%0d packets=%0d final=%0d scratch=%0d drained=%b",which,timing_packets,timing_final_accepts,scratch_acks,native_input_drained);
    timing_no_publication();
  endtask
  task automatic timing_pulse(input integer kind);
    // Caller is on a falling edge. Hold across exactly ONE rising edge; no
    // wait for scratch completion and no completion-ready input is invented.
    native_done_tag=cfg_job.source_tag;native_done_error=0;
    if(kind==83)native_done_tag=cfg_job.source_tag+32'd1;
    if(kind==84)native_done_error=1;
    if(kind==85)native_done_error=1'bx;
    if(kind==86)native_done_tag=32'bx;
    native_done_fire=kind==87 ? 1'bx:1'b1;
    $display("RAW32_RESIDUAL_COMPLETION_PULSE case=%0d cycle=%0d accepted_packets=%0d final_accepts=%0d scratch_ACKs=%0d drained=%b fire=%b error=%b tag=%08h",which,cycles,timing_packets,timing_final_accepts,scratch_acks,native_input_drained,native_done_fire,native_done_error,native_done_tag);$fflush();
    @(negedge clk);native_done_fire=0;native_done_error=0;native_done_tag=cfg_job.source_tag;
    #1ps; // Diagnostic only: sample public epoch_fault after combinational settling.
  endtask
  task automatic timing_finish_positive();
    wait_cycles=0;while(c_completed_rows!=1 && !epoch_fault && wait_cycles<30000)begin @(negedge clk);wait_cycles++;end
    if(epoch_fault!==1'b0)$fatal(1,"PROTOCOL_VALID_DONE_BEFORE_SCRATCH_DRAIN_REJECTED scratch=%0d packets=%0d final=%0d",scratch_acks,timing_packets,timing_final_accepts);
    if(c_completed_rows!=1 || c_strip_count!=256 || row_done_valid || c_read_response_valid!==1'b1)
      $fatal(1,"PROTOCOL_COMPLETION_GREEN_C_VISIBLE_DRAIN_MISSING");
    repeat(8)@(negedge clk);if(row_done_valid)$fatal(1,"PROTOCOL_COMPLETION_DONE_IGNORED_VISIBLE_C_RESPONSE");
    drain_block=0;wait_cycles=0;
    while(!row_done_valid && wait_cycles<100)begin @(negedge clk);wait_cycles++;end
    if(!row_done_valid || row_done_error || row_done_tag!=32'h50520000 || scratch_ack_count!=128 || raw_ack_count!=128 || !metadata_acknowledged ||
       scratch_acks!=128 || raw_acks!=128 || meta_acks!=1 || read_requests!=401 || read_beat_fires!=3202 ||
       write_requests!=257 || write_data_fires!=2050 || write_acks!=257 || c_cfg_count!=1 || c_demand_count!=1 ||
       c_accepted_rows!=1 || c_completed_rows!=1 || !c_demand_ready || c_idle || held_job.target_count!=264 ||
       request_stalls==0 || data_stalls==0 || ack_stalls==0 || metadata_pending_cycles<12 ||
       timing_packets!=13 || timing_final_accepts!=1 || timing_done_pulses!=1 ||
       timing_first_done_cycle-timing_final_cycle!=3 || !owner_held || c_retire_valid)
      $fatal(1,"PROTOCOL_COMPLETION_GREEN_COMPLETE_PRESSURED_TUPLE");
    unknown_done_snapshot={row_done_error,row_done_tag};unknown_job_snapshot=held_job;
    repeat(8)@(negedge clk);
    if(row_done_valid!==1'b1 || {row_done_error,row_done_tag}!==unknown_done_snapshot || held_job!==unknown_job_snapshot ||
       epoch_fault!==1'b0 || !owner_held || c_retire_valid || c_accepted_rows!=1 || c_completed_rows!=1)
      $fatal(1,"PROTOCOL_COMPLETION_GREEN_HELD_DONE_CHANGED");
    $display("RAW32_RESIDUAL_PROTOCOL_COMPLETION_HEALTHY_PASS case=80 read_requests=%0d read_beats=%0d write_requests=%0d write_data_beats=%0d write_ACKs=%0d scratch_ACKs=%0d raw_ACKs=%0d metadata_ACKs=%0d Cstrips=%0d Caccepted=%0d Ccompleted=%0d frame_count=264 accepted_packets=13 final_accepts=1 native_done_pulses=1 final_to_done_cycles=%0d Done_before_scratch_drain=1 AwaitDemand=1 owner_held=1 retire=0 held_done=1 native_or_C_arithmetic_qualified=0",read_requests,read_beat_fires,write_requests,write_data_fires,write_acks,scratch_acks,raw_acks,meta_acks,c_strip_count,c_accepted_rows,c_completed_rows,timing_first_done_cycle-timing_final_cycle);$fflush();
    // The old immutable held-Done/late-abort contract is retained as well.
    abort_valid=1;repeat(8)@(negedge clk);
    if(row_done_valid!==1'b1 || {row_done_error,row_done_tag}!==unknown_done_snapshot || held_job!==unknown_job_snapshot ||
       epoch_fault!==1'b1 || !owner_held || c_retire_valid || write_acks!=257)
      $fatal(1,"PROTOCOL_COMPLETION_GREEN_LATE_ABORT_CHANGED_HELD_DONE");
  endtask
  task automatic completion_timing_case();
    drain_block=1;admit();await_launch();
    if(which==81)begin
      for(integer packet=0;packet<12;packet++)push_packet(packet);
      wait_cycles=0;while(in_ready!==1'b1 && !epoch_fault && wait_cycles<10000)begin @(negedge clk);wait_cycles++;end
      if(in_ready!==1'b1 || timing_packets!=12 || timing_final_accepts!=0 || scratch_ack_count!==9'd120 ||
         scratch_acks!=120 || native_input_drained!==1'b0 || in_valid!==1'b0 || epoch_fault!==1'b0)
        $fatal(1,"PROTOCOL_TRUE_EARLY_DONE_PRECONDITION");
      timing_no_publication();timing_pulse(81);require_known_fault("nativeDone before final packet acceptance");
      await_fault_done();
      if(timing_packets!=12 || timing_final_accepts!=0 || timing_done_pulses!=1 || raw_acks!=0 || meta_acks!=0 || c_cfg_count!=0 || c_demand_count!=0)
        $fatal(1,"PROTOCOL_TRUE_EARLY_DONE_ACCEPTED_OR_PUBLISHED");
    end else begin
      timing_final_capture();timing_pulse(which==82 ? 80:which);
      if(which==80 || which==82)begin
        if(epoch_fault!==1'b0)$fatal(1,"PROTOCOL_VALID_DONE_BEFORE_SCRATCH_DRAIN_REJECTED scratch=%0d packets=%0d final=%0d",scratch_acks,timing_packets,timing_final_accepts);
        if(timing_done_pulses!=1 || timing_first_done_cycle-timing_final_cycle!=3 || scratch_ack_count!==9'd120 ||
           native_input_drained!==1'b0)$fatal(1,"PROTOCOL_COMPLETION_PULSE_WAS_DEFERRED_OR_RESAMPLED");
        if(which==80)timing_finish_positive();
        else begin
          repeat(2)@(negedge clk);timing_no_publication();timing_pulse(82);
          require_known_fault("duplicate nativeDone after valid captured completion");await_fault_done();
          if(timing_done_pulses!=2 || raw_acks!=0 || meta_acks!=0 || metadata_write_requests!=0 || c_cfg_count!=0 || c_demand_count!=0)
            $fatal(1,"PROTOCOL_DUPLICATE_DONE_ACCEPTED_OR_PUBLISHED");
        end
      end else if(which==87)begin
        require_known_fault("nativeDone fire X during final packet spool");prove_quarantine();
      end else begin
        require_known_fault("bad tag/error/unknown completion tuple during final packet spool");await_fault_done();
        if(timing_packets!=13 || timing_final_accepts!=1 || timing_done_pulses!=1 || raw_acks!=0 || meta_acks!=0 ||
           metadata_write_requests!=0 || c_cfg_count!=0 || c_demand_count!=0 || !owner_held)
          $fatal(1,"PROTOCOL_BAD_SPOOL_DONE_ACCEPTED_OR_PUBLISHED case=%0d",which);
      end
    end
    $display("RAW32_RESIDUAL_PROTOCOL_CONTROL_PASS case=%0d completion_timing_contract=1 native_or_C_arithmetic_qualified=0 physical_advancement_allowed=0",which);$fflush();$finish;
  endtask
  initial begin
    which=0;void'($value$plusargs("PROTOCOL_CASE=%d",which));initialize();reset_pair();
    if(which>=80 && which<=87)completion_timing_case();
    if(which==0 || which==16 || which==29 || (which>=54 && which<=68) || which==74 || which==75 || which==79)begin
      if(which==16)begin
        cfg_job.source_rank=1;cfg_job.original_root=2;cfg_job.source_tag=32'h504f0001;
        row_input_rank=1;row_root=2;row_tag=cfg_job.source_tag;in_tag=cfg_job.source_tag;native_done_tag=cfg_job.source_tag;
        original_metadata={5'd0,16'd1,5'd0,10'd7,10'd1,10'd2,-8'sd30,64'd755578637259143234};
      end
      drain_block=1;admit();await_launch();
      for(integer packet=0;packet<13;packet++)push_packet(packet);
      wait_cycles=0;while(!native_input_drained && wait_cycles<10000)begin @(negedge clk);wait_cycles++;end
      if(!native_input_drained || scratch_ack_count!=128)$fatal(1,"PROTOCOL_NATIVE_INPUT_NOT_DRAINED");
      if(which==29)begin
        repeat(32)@(negedge clk);
        if(row_done_valid || c_cfg_count!=0 || c_demand_count!=0 || raw_acks!=0 || meta_acks!=0 || !owner_held || epoch_fault)
          $fatal(1,"PROTOCOL_NATIVE_DONE_BARRIER_MISSING");
        $display("RAW32_RESIDUAL_PROTOCOL_CONTROL_PASS case=29 native_done_missing_barrier=1 native_or_C_arithmetic_qualified=0 physical_advancement_allowed=0");$finish;
      end
      if(which==54)begin
        native_done_fire=1'bx;@(negedge clk);require_known_fault("nativeDone fire X");native_done_fire=0;prove_sticky_failure(0);
        $display("RAW32_RESIDUAL_PROTOCOL_CONTROL_PASS case=54 unknown_completion_fault=1 native_or_C_arithmetic_qualified=0 physical_advancement_allowed=0");$finish;
      end
      if(which==67)native_done_error=1'bx;
      native_done_fire=1;@(negedge clk);native_done_fire=0;
      if(which==67)begin
        require_known_fault("nativeDone error X");native_done_error=0;prove_sticky_failure(0);
        $display("RAW32_RESIDUAL_PROTOCOL_CONTROL_PASS case=67 native_or_C_arithmetic_qualified=0 physical_advancement_allowed=0");$finish;
      end
      if(which==74 || which==75 || which==79)begin
        wait(raw_acks==128);@(negedge clk);
        if(which==79)in_valid=1'bx;else injected_c_fault=which==74 ? 1'b1:1'bx;
        @(negedge clk);require_known_fault("late prepublication C fault or extra packet-valid X");injected_c_fault=0;in_valid=0;prove_sticky_failure(0);
        if(metadata_write_requests!=0 || meta_acks!=0 || c_cfg_count!=0 || c_demand_count!=0)
          $fatal(1,"PROTOCOL_C_FAULT_DID_NOT_BLOCK_METADATA_PUBLICATION case=%0d",which);
        $display("RAW32_RESIDUAL_PROTOCOL_CONTROL_PASS case=%0d native_or_C_arithmetic_qualified=0 physical_advancement_allowed=0",which);$finish;
      end
      if(which==60 || which==61)begin
        if(which==60)wait(c_cfg_valid);else wait(c_demand_valid);
        @(negedge clk);unknown_job_snapshot=held_job;unknown_C_kind=which;
        @(negedge clk);require_known_fault("C ready X during offered transfer");
        if(held_job!==unknown_job_snapshot || (which==60 ? c_cfg_valid!==1'b1:c_demand_valid!==1'b1))
          $fatal(1,"PROTOCOL_HELD_C_OFFER_CHANGED_DURING_UNKNOWN_READY");
        unknown_C_kind=0;prove_quarantine();
        $display("RAW32_RESIDUAL_PROTOCOL_CONTROL_PASS case=%0d native_or_C_arithmetic_qualified=0 physical_advancement_allowed=0",which);$finish;
      end
      if((which>=55 && which<=59) || (which>=63 && which<=66) || which==68)begin
        wait(c_busy);@(negedge clk);
        if(which==55)begin while(c_output_valid!==1'b1)@(negedge clk);poison_c_fire=1;end
        if(which==56)unknown_C_kind=38;
        if(which==57)unknown_C_kind=39;
        if(which==58)unknown_C_kind=33;
        if(which==59)unknown_C_kind=34;
        if(which==63)unknown_C_kind=35;
        if(which==64)unknown_C_kind=36;
        if(which==65)unknown_C_kind=37;
        if(which==66)unknown_C_kind=32;
        if(which==68)begin
          poison_c_tag=1;while(c_output_fire!==1'b1)@(negedge clk);
        end
        @(negedge clk);require_known_fault("active C control/state/payload X");poison_c_fire=0;poison_c_tag=0;unknown_C_kind=0;prove_sticky_failure(0);
        $display("RAW32_RESIDUAL_PROTOCOL_CONTROL_PASS case=%0d native_or_C_arithmetic_qualified=0 physical_advancement_allowed=0",which);$finish;
      end
      wait_cycles=0;while(c_completed_rows!=1 && wait_cycles<30000)begin @(negedge clk);wait_cycles++;end
      if(c_completed_rows!=1 || c_strip_count!=256 || row_done_valid || !c_read_response_valid)$fatal(1,"PROTOCOL_VISIBLE_C_RESPONSE_NOT_HELD");
      repeat(8)@(negedge clk);if(row_done_valid)$fatal(1,"PROTOCOL_DONE_WHILE_VISIBLE_RESPONSE");drain_block=0;
      wait_cycles=0;while(!row_done_valid && wait_cycles<100)begin @(negedge clk);wait_cycles++;end
      if(!row_done_valid || row_done_error || row_done_tag!=32'h50520000 || scratch_ack_count!=128 || raw_ack_count!=128 || !metadata_acknowledged ||
         scratch_acks!=128 || raw_acks!=128 || meta_acks!=1 || read_requests!=401 || read_beat_fires!=3202 || write_requests!=257 || write_data_fires!=2050 || write_acks!=257 || c_cfg_count!=1 || c_demand_count!=1 ||
         c_accepted_rows!=1 || c_completed_rows!=1 || !c_demand_ready || c_idle || held_job.target_count!=264 ||
         request_stalls==0 || data_stalls==0 || ack_stalls==0 || metadata_pending_cycles<12)$fatal(1,"PROTOCOL_COMPLETE_PRESSURED_TUPLE");
      if(which==0 || which==16)begin
        $display("RAW32_RESIDUAL_PROTOCOL_HEALTHY_PASS case=%0d read_requests=%0d read_beats=%0d write_requests=%0d write_data_beats=%0d write_ACKs=%0d scratch_ACKs=%0d raw_ACKs=%0d metadata_ACKs=%0d Cstrips=%0d Caccepted=%0d Ccompleted=%0d frame_count=264 AwaitDemand=1 owner_held=1 retire=0 native_or_C_arithmetic_qualified=0",which,read_requests,read_beat_fires,write_requests,write_data_fires,write_acks,scratch_acks,raw_acks,meta_acks,c_strip_count,c_accepted_rows,c_completed_rows);$fflush();
      end
      if(which==62)begin
        unknown_done_snapshot={row_done_error,row_done_tag};row_done_ready=1'bx;
        @(negedge clk);require_known_fault("held Done ready X");
        if(row_done_valid!==1'b1 || {row_done_error,row_done_tag}!==unknown_done_snapshot)$fatal(1,"PROTOCOL_HELD_DONE_CHANGED_DURING_UNKNOWN_READY");
        row_done_ready=0;prove_sticky_failure(1);
        if(!row_done_valid || row_done_error || row_done_tag!=32'h50520000)$fatal(1,"PROTOCOL_HELD_DONE_REWRITTEN_ON_UNKNOWN_READY");
        $display("RAW32_RESIDUAL_PROTOCOL_CONTROL_PASS case=62 native_or_C_arithmetic_qualified=0 physical_advancement_allowed=0");$finish;
      end
      abort_valid=1;repeat(8)@(negedge clk);
      if(!row_done_valid || row_done_error || row_done_tag!=32'h50520000 || !owner_held || c_retire_valid || write_requests!=257 || c_cfg_count!=1 || c_demand_count!=1 || epoch_fault!==1'b1)
        $fatal(1,"PROTOCOL_HELD_DONE_CHANGED_ON_LATE_ABORT");
    end else if(which==1)begin
      allow_read_request=0;admit();wait(req_valid);repeat(4)@(negedge clk);abort_valid=1;
      repeat(4)@(negedge clk);if(!req_valid)$fatal(1,"PROTOCOL_READ_OFFER_RETRACTED_ON_ABORT");allow_read_request=1;await_fault_done();
    end else if(which==2)begin
      admit();await_launch();allow_write_data=0;push_packet(0);wait(write_data_valid);repeat(4)@(negedge clk);abort_valid=1;
      repeat(4)@(negedge clk);if(!write_data_valid)$fatal(1,"PROTOCOL_WRITE_DATA_RETRACTED_ON_ABORT");allow_write_data=1;await_fault_done();
    end else if(which==3)begin
      admit();await_launch();inject_ack=1;@(negedge clk);inject_ack=0;prove_quarantine();
    end else if(which==4)begin
      malformed_last=1;admit();wait(epoch_fault);prove_quarantine();
    end else if(which==5)begin
      admit();await_launch();row_gain=3;in_valid=1;repeat(2)@(negedge clk);in_valid=0;await_fault_done();
      if(write_requests!=0)$fatal(1,"PROTOCOL_UNOBSERVED_ROW_GAIN_ACCEPTED");
    end else if(which==6)begin
      cfg_job.target_raw_base=OLD_RAW;admit();await_fault_done();if(read_requests!=0 || write_requests!=0)$fatal(1,"PROTOCOL_ALIAS_ADMISSION_SIDE_EFFECT");
    end else if(which==7)begin
      admit();await_launch();in_count=159;in_valid=1;repeat(2)@(negedge clk);in_valid=0;await_fault_done();
      if(write_requests!=0)$fatal(1,"PROTOCOL_MALFORMED_PACKET_ACCEPTED");
    end else if(which==8)begin
      admit();await_launch();physical_unowned_response=1;@(negedge clk);physical_unowned_response=0;prove_quarantine();
    end else if(which==9 || which==20)begin
      table_corruption_mode=which==9 ? 1:2;admit();await_fault_done();
      if(write_requests!=0 || launch_allowed)$fatal(1,"PROTOCOL_NONZERO_OR_RESERVED_TABLE_ACCEPTED");
    end else if(which==10)begin
      poison_raw_min=1;admit();await_launch();push_packet(0);await_fault_done();
      if(raw_acks!=0 || meta_acks!=0)$fatal(1,"PROTOCOL_RAW_NEGATIVE_LIMIT_COMMITTED");
    end else if(which==11 || which==30)begin
      admit();await_launch();in_data[31:0]=which==11 ? 32'd92274689:-32'sd92274689;push_packet(0);await_fault_done();
      if(raw_acks!=0 || meta_acks!=0)$fatal(1,"PROTOCOL_BRANCH_BOUND_COMMITTED");
    end else if(which==12 || which==13 || which==14 || which==15 || which==21 || which==22 || which==23 || which==31)begin
      if(which==12)cfg_job.target_gamma_base=GAMMA+6144;
      if(which==13)cfg_job.target_gamma_exponent=-22;
      if(which==14)cfg_job.gain_cap=3;
      if(which==15)cfg_job.target_raw_base=64'hfffffffffffff000;
      if(which==21)begin cfg_job.source_epoch=16'hffff;cfg_job.target_epoch=0;end
      if(which==22)cfg_job.target_gamma_index=3;
      if(which==23)force_c_active=1;
      if(which==31)begin cfg_job.protected_base[0]=TARGET_RAW;cfg_job.protected_bytes[0]=64;end
      admit();await_fault_done();if(read_requests!=0 || write_requests!=0)$fatal(1,"PROTOCOL_INVALID_BOUND_ENVELOPE_SIDE_EFFECT case=%0d",which);
    end else if(which==17)begin
      admit();await_launch();allow_write_request=0;push_packet(0);wait(write_req_valid);
      @(negedge clk);allow_write_request=1;inject_ack=1;@(negedge clk);inject_ack=0;prove_quarantine();
    end else if(which==18)begin
      admit();await_launch();push_packet(0);wait(write_data_valid && write_last);allow_write_data=0;
      // Arm from a falling edge with the periodic ready gate open. Both the
      // final data beat and injected ACK are sampled on the next rising edge.
      @(negedge clk);while(cycles%4==2)@(negedge clk);
      allow_write_data=1;inject_ack=1;@(negedge clk);inject_ack=0;prove_quarantine();
    end else if(which==19)begin
      admit();await_launch();push_packet(0);wait(scratch_acks==1);@(negedge clk);inject_ack=1;@(negedge clk);inject_ack=0;prove_quarantine();
    end else if(which==24 || which==25 || which==26 || which==27)begin
      admit();await_launch();
      if(which==24)row_activation_unit=-5;
      if(which==25)row_up_shift=4;
      if(which==26)in_tag=in_tag+1;
      if(which==27)in_last=1;
      in_valid=1;repeat(2)@(negedge clk);in_valid=0;await_fault_done();
      if(write_requests!=0)$fatal(1,"PROTOCOL_OBSERVED_ROW_OR_PACKET_IDENTITY_ACCEPTED case=%0d",which);
    end else if(which==28)begin
      admit();await_launch();allow_write_request=0;push_packet(0);wait(write_req_valid);repeat(4)@(negedge clk);abort_valid=1;
      repeat(4)@(negedge clk);if(!write_req_valid)$fatal(1,"PROTOCOL_WRITE_REQUEST_RETRACTED_ON_ABORT");allow_write_request=1;await_fault_done();
    end else if(which>=32 && which<=41)begin
      if(which<=39)unknown_C_kind=which;
      if(which==40)injected_c_fault=1;
      if(which==41)injected_c_fault=1'bx;
      unknown_admission();
    end else if(which==42 || which==43 || which==50 || which==51)begin
      admit();await_launch();
      if(which==42)owner_held=1'bx;
      if(which==43)abort_valid=1'bx;
      if(which==50)injected_c_fault=1'bx;
      if(which==51)injected_c_fault=1;
      @(negedge clk);require_known_fault("active lease/abort/C fault control");
      owner_held=1;abort_valid=0;injected_c_fault=0;prove_sticky_failure(0);
      if(write_requests!=0 || c_cfg_count!=0 || c_demand_count!=0)$fatal(1,"PROTOCOL_PREPUBLICATION_FAULT_IGNORED");
    end else if(which==44)begin
      allow_read_request=0;admit();wait(req_valid);@(negedge clk);while(cycles%3==1)@(negedge clk);
      unknown_request_snapshot={req_address,req_length};allow_read_request=1'bx;
      @(negedge clk);require_known_fault("offered read ready X");
      if(req_valid!==1'b1 || {req_address,req_length}!==unknown_request_snapshot)$fatal(1,"PROTOCOL_READ_OFFER_CHANGED_DURING_UNKNOWN_READY");
      allow_read_request=1;prove_quarantine();
    end else if(which==45)begin
      admit();await_launch();allow_write_request=0;push_packet(0);wait(write_req_valid);@(negedge clk);while(cycles%4==1)@(negedge clk);
      unknown_request_snapshot={write_address,write_length};allow_write_request=1'bx;
      @(negedge clk);require_known_fault("offered write request ready X");
      if(write_req_valid!==1'b1 || {write_address,write_length}!==unknown_request_snapshot)$fatal(1,"PROTOCOL_WRITE_OFFER_CHANGED_DURING_UNKNOWN_READY");
      allow_write_request=1;prove_quarantine();
    end else if(which==46)begin
      admit();await_launch();allow_write_data=0;push_packet(0);wait(write_data_valid);@(negedge clk);while(cycles%4==2)@(negedge clk);
      unknown_data_snapshot={write_data,write_strobe,write_last};allow_write_data=1'bx;
      @(negedge clk);require_known_fault("owned write data ready X");
      if(write_data_valid!==1'b1 || {write_data,write_strobe,write_last}!==unknown_data_snapshot)$fatal(1,"PROTOCOL_WRITE_DATA_CHANGED_DURING_UNKNOWN_READY");
      allow_write_data=1;prove_quarantine();
    end else if(which==47)begin
      admit();wait(provider_rsp_valid);@(negedge clk);unknown_response_snapshot={rsp_data,rsp_last,rsp_error};poison_rsp_valid=1;
      @(negedge clk);require_known_fault("owned response valid X");
      if({rsp_data,rsp_last,rsp_error}!==unknown_response_snapshot)$fatal(1,"PROTOCOL_RESPONSE_DATA_CHANGED_DURING_UNKNOWN_VALID");
      poison_rsp_valid=0;prove_quarantine();
    end else if(which==48)begin
      admit();await_launch();push_packet(0);wait(write_all);@(negedge clk);inject_ack=1'bx;
      @(negedge clk);require_known_fault("owned completed write ACK valid X");
      if(scratch_ack_count!=0 || raw_ack_count!=0 || metadata_acknowledged)$fatal(1,"PROTOCOL_UNKNOWN_ACK_ADVANCED_COUNTER");
      inject_ack=0;prove_quarantine();
    end else if(which==49)begin
      admit();await_launch();physical_unowned_response=1'bx;@(negedge clk);require_known_fault("physical association flag X");physical_unowned_response=0;prove_quarantine();
    end else if(which==52)begin
      cfg_valid=1'bx;@(negedge clk);require_known_fault("config valid X while ready");cfg_valid=0;prove_quarantine();
    end else if(which==53)begin
      admit();await_launch();in_valid=1'bx;@(negedge clk);require_known_fault("packet valid X while ready");in_valid=0;prove_quarantine();
    end else if(which==69 || which==70 || which==72)begin
      if(which==69)poison_rsp_error=1;
      if(which==70)poison_rsp_last=1;
      if(which==72)poison_rsp_data=1;
      admit();wait(provider_rsp_valid);repeat(2)@(negedge clk);require_known_fault("owned response error/LAST/data X");
      poison_rsp_error=0;poison_rsp_last=0;poison_rsp_data=0;
      if(which==70)prove_quarantine();else await_fault_done();
    end else if(which==71)begin
      admit();await_launch();poison_write_error=1;push_packet(0);wait(provider_ack);repeat(2)@(negedge clk);
      require_known_fault("owned write response error X");poison_write_error=0;await_fault_done();
    end else if(which==73)begin
      admit();await_launch();allow_write_data=0;push_packet(0);wait(write_data_valid);@(negedge clk);
      unknown_data_snapshot={write_data,write_strobe,write_last};injected_c_fault=1;
      @(negedge clk);require_known_fault("known C fault during owned scratch data stall");
      if(write_data_valid!==1'b1 || {write_data,write_strobe,write_last}!==unknown_data_snapshot)$fatal(1,"PROTOCOL_C_FAULT_RETRACTED_OWNED_WRITE_DATA");
      injected_c_fault=0;allow_write_data=1;await_fault_done();
      if(meta_acks!=0 || raw_acks!=0 || metadata_write_requests!=0)$fatal(1,"PROTOCOL_C_FAULT_PUBLISHED_AFTER_OWNED_DRAIN");
    end else if(which==76 || which==77)begin
      admit();await_launch();
      if(which==76)poison_rsp_valid=1;else inject_ack=1'bx;
      @(negedge clk);require_known_fault("unowned response or ACK valid X");poison_rsp_valid=0;inject_ack=0;prove_quarantine();
    end else if(which==78)begin
      admit();native_done_fire=1'bx;@(negedge clk);require_known_fault("early preflight native Done fire X");native_done_fire=0;prove_quarantine();
    end else $fatal(1,"PROTOCOL_UNKNOWN_CASE");
    $display("RAW32_RESIDUAL_PROTOCOL_CONTROL_PASS case=%0d native_or_C_arithmetic_qualified=0 physical_advancement_allowed=0",which);$finish;
  end
endmodule
