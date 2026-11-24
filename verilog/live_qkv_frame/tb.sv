`timescale 1ns/1ps
module tri_oracle_shared_attention_projection_tb;
 parameter bit CONNECTED_PREFIX_ONLY=1,CORRUPT_NATIVE_RESIDUAL=0;
 int TARGET_QUERY=1;
`include "verilog/live_qkv_frame/qkv_declarations.svh"
 wire signed [8:0] EXPECTED_CONTEXT_EXPONENT=TARGET_QUERY==1 ? -9'sd8 : -9'sd7;
 string paired_root,units_file;
 logic [511:0] query_units[2];
 logic ff_phase=0,ff_fixture_loaded,ff_done;
 logic final_raw_valid,final_raw_last,final_raw_ready,final_sink_ready;
 logic final_complete,final_idle;
 logic [31:0] final_raw_tag;
 logic [3:0] final_raw_token;
 logic [15:0] final_raw_start;
 logic [7:0] final_raw_count;
 logic [5119:0] final_raw_data;
 int metadata_rebuilds=0;
 logic [533:0] ff_strip_request;
 logic [111:0] ff_strip_response;
 logic [511:0] native_residual_valid='0,native_bypass_valid='0;
 string fixed_root;
 function automatic string fixed_path(input string name);
  string path;int handle;
  path={fixed_root,"/",name};handle=$fopen(path,"r");
  if(handle==0)$fatal(1,"FIXED_QUERY_FIXTURE_MISSING file=%s",path);
  $fclose(handle);return path;
 endfunction
 logic clk=1'bx,rst_n=0,cfg_valid=0,cfg_ready,cancel=0;
 initial begin #1;clk=0;end
 initial begin
   #3;
   if(clk!==1'b0 || rst_n!==1'b0)$fatal(1,"CONNECTED_MEMORY_CLOCK_STARTED");
   $display("COMPLETE_MEMORY_CENSUS_PASS clocks=0");
 end
 logic [31:0] cfg_heads=0,cfg_streaming=0;
 logic [10:0] cfg_total_keys=0,cfg_visible_keys=0;
 logic [223:0] cfg_score_shifts=0;
 logic [255:0] cfg_value_exponents=0;
 logic [15:0] cfg_query=1,cfg_epoch=16'h9ab3;
 logic [31:0] cfg_tag=32'h5317b92d;
 logic tensor_req_valid,tensor_req_ready,tensor_rsp_valid=0,tensor_rsp_ready,tensor_rsp_error=0;
 logic [1:0] tensor_req_kind,tensor_rsp_kind=0;
 logic [4:0] tensor_req_head,tensor_rsp_head=0;
 logic [9:0] tensor_req_key,tensor_rsp_key=0,tensor_rsp_size=0;
 logic [15:0] tensor_req_query,tensor_req_epoch,tensor_rsp_query=0,tensor_rsp_epoch=0;
 logic [31:0] tensor_req_tag,tensor_rsp_tag=0;
 logic signed [7:0] tensor_rsp_value_exponent=0;
 logic [511:0] tensor_rsp_data=0;
 logic context_valid,context_ready;
 logic [4:0] context_head;
 logic [15:0] context_query,context_epoch;
 logic [31:0] context_tag;
 logic signed [7:0] context_value_exponent;
 logic [2047:0] context_data;
 logic all_contexts_collected,done_valid,done_ready,done_error,reset_required,busy;
 logic [7:0] error_code;
 logic fabric_load_valid,fabric_load_error,raw_fabric_load_error,inject_load_error=0,fabric_cmd_valid,fabric_cmd_ready,fabric_cmd_accumulate;
 logic [4:0] fabric_load_core,fabric_cmd_clusters,fabric_cmd_weight,fabric_cmd_mask,fabric_activation_reloaded;
 logic [1:0] fabric_load_kind,fabric_cmd_reduce;
 logic [9:0] fabric_load_addr,fabric_cmd_activation;
 logic [2047:0] fabric_load_data;
 logic [31:0] fabric_load_rows;
 logic [3:0] fabric_cmd_output;
 logic [2:0] fabric_core_select;
 logic [4:0] fabric_out_valid,fabric_out_ready;
 logic [19:0] fabric_out_slot;
 logic [5119:0] fabric_out_data;
 tri_oracle_wac_softmax_types::request_t softmax_request;
 tri_oracle_wac_softmax_types::response_t softmax_response;
 logic [511:0] qk[6],values[4];
 logic [2047:0] golden[2];
 logic [511:0] trained_q[32],trained_k[1124],trained_v[1124];
 logic [9:0] trained_sizes[281];
 logic [2047:0] trained_gold[32];
 localparam logic[31:0] TRAIN_STREAMING=32'hfd6c64bf;
 localparam logic[223:0] TRAIN_SHIFTS=224'h0000000000007ffe0007f000007f000007ffe03f8000000000000000;
 localparam logic[255:0] TRAIN_EXPONENTS=256'hfbfbfbfbfbfbfbfbfbfbfbfbfbfbfbfbfbfbfbfbfbfbfbfbfbfbfbfbfbfbfbfb;
 logic [31:0] expected_heads=0,received_heads=0;
 logic [15:0] expected_epoch=16'h9ab3,expected_query=1;
 logic [31:0] expected_tag=32'h5317b92d;
 logic [19:0] configured_owners=0,first_value_configured=0;
 logic first_value_seen=0,auto_accept=0,check_contexts=1;
 logic held=0;
 logic [2047:0] held_data;
 logic [68:0] held_metadata;
 int case_id=0,frame=-1,cycle=0,received=0,requests=0,delay_count=0;
 bit serving=0;
 string qk_file,value_file,gold_file,fixture_root=".";
 function automatic string fixture_path(input string relative_path);
  string path;int handle;
  path={fixture_root,"/",relative_path};
  handle=$fopen(path,"r");
  if(handle==0)$fatal(1,"SHARED_FIXTURE_MISSING file=%s",path);
  $fclose(handle);
  return path;
 endfunction

 logic c_cfg_valid,c_cfg_ready,c_row_ready,c_metadata_idle,c_actual_metadata_idle,c_metadata_rebuilt;
 logic metadata_release_gate=0;
 logic [1:0] c_metadata_ce_n,c_metadata_we_n;
 logic [17:0] c_metadata_address;
 logic [127:0] c_metadata_write_data;
 assign c_metadata_idle=c_actual_metadata_idle && metadata_release_gate;
 logic c_lease_block,c_needs_rebuild,c_lease,c_valid,c_done,c_done_ready,c_error;
 logic [31:0] c_tag;
 logic [10:0] c_query;
 logic signed [8:0] c_unit;
 logic [127:0] c_metadata_read;
 logic broker_cfg_valid_i,broker_cfg_ready_i,broker_cancel_i,broker_busy_i;
 logic co_row_valid,co_frame_valid,co_route,co_collector_rst_n;
 logic co_done_valid,co_done_ready=0,co_done_error,co_reset_required;
 logic co_finish_valid,co_finish_ready;
 logic [7:0] co_error_code;
 bit commit_reported=0;
 logic p_valid,p_ready,p_rsp_valid,p_rsp_ready,p_rsp_last,p_rsp_error;
 logic [63:0] p_address;
 logic [5:0] p_length;
 logic [511:0] p_rsp_data;
 logic w_valid,w_ready,w_rsp_valid,w_rsp_ready,w_rsp_error;
 logic [9:0] w_word;
 logic [63:0] w_data,converted_words[256];
 logic c_finish=0,c_finish_ready,m_finish,m_finish_ready,p_idle;
  tri_oracle_fabric_owner_types::request_t attention_bus,projection_bus,physical_bus;
  tri_oracle_fabric_owner_types::response_t attention_return,projection_return,physical_return;
  tri_oracle_wac_softmax_types::request_t physical_softmax_request;
  tri_oracle_wac_softmax_types::response_t physical_softmax_response;
  logic projection_command_idle,projection_complete_idle,projection_window_idle;
  logic projection_admitted_valid,frame_cancel;
  logic projection_cfg_valid=0,projection_cfg_ready;
  logic [31:0] projection_cfg_tag=0;
  logic [7:0] projection_cfg_count=0;
  logic [2559:0] projection_cfg_channels=0,projection_cfg_keep=0;
  logic projection_out_valid,projection_out_last;
`ifdef QUANTIZED_PROJECTION
  logic projection_out_ready;
`else
  logic projection_out_ready=0;
`endif
  logic [31:0] projection_out_tag,projection_done_tag;
  logic [3:0] projection_out_token;
  logic [7:0] projection_out_count;
  logic [2559:0] projection_out_channels;
  logic [5119:0] projection_out_data;
  logic projection_done_valid,projection_done_ready=0,projection_done_error;
  logic projection_req_valid,projection_req_ready,projection_rsp_valid,projection_rsp_ready,projection_rsp_last,projection_rsp_error;
  logic [63:0] projection_req_address;
  logic [4:0] projection_req_length;
  logic [511:0] projection_rsp_data;
  logic external_req_valid,external_req_ready,external_req_wide;
  logic [63:0] external_req_address;
  logic [5:0] external_req_length;
  logic external_rsp_valid=0,external_rsp_ready,external_rsp_last,external_rsp_error;
  logic [511:0] external_rsp_data;
  logic external_serving=0;
  logic [19:0] external_word=0;
  logic [5:0] external_remaining=0;
  logic [63:0] output_weights[524288];
  logic signed [31:0] output_accumulators[2048];
  int projection_group=0,projection_values=0,projection_context_words=0,projection_weight_words=0;
  int context_word_inflight=0;
  logic finish_seen=0;
  bit projection_fault_case=$test$plusargs("PROJECTION_ERROR");

`ifdef QUANTIZED_PROJECTION
  logic quant_out_valid,quant_out_ready,quant_accept_enable=0,quant_last,quant_packet_last,quant_idle,quant_fault;
  logic [31:0] quant_tag;
  logic [3:0] quant_token,quant_count;
  logic [127:0] quant_channels;
  logic [63:0] quant_data,quant_expected[256];
  logic [255:0] quant_weight_units,quant_output_units;
  int quant_values=0,quant_words=0;
  string quant_expected_file;

  // Native requantizer -> existing precision-preserving addition and dual
  // output store. PRE residuals and shifts are authentic input metadata.
  // Neither expected bypass nor expected normalization drives this path.
  logic residual_in_ready,residual_write_valid,residual_norm_valid;
  logic [8:0] residual_write_row,residual_norm_row;
  logic [231:0] residual_write_data,expected_bypass[256];
  logic [127:0] residual_norm_data,expected_normal[256];
  logic [279:0] pre_residual[256],actual_pre_residual;
  logic [4:0] residual_shifts[32];
  int residual_writes=0,residual_norms=0,norm_file,bypass_file;
  logic residual_write_ready;
  logic residual_norm_ready;
  wire [7:0] residual_word=quant_channels[10:3];
  assign quant_out_ready=quant_accept_enable && residual_in_ready;
  always_comb begin
    actual_pre_residual=pre_residual[residual_word];
    if($test$plusargs("CORRUPT_PRE_RESIDUAL") && residual_word==0)actual_pre_residual[19]=!actual_pre_residual[19];
  end
  tri_oracle_attention_residual_store residual_path(
    .clk,.rst_n,.in_valid(quant_out_valid && quant_accept_enable),.in_ready(residual_in_ready),
    .in_row({1'(TARGET_QUERY-1),residual_word}),.residual_q32(actual_pre_residual),.projection_codes(quant_data),
    .projection_shift(residual_shifts[quant_channels[10:6]]),
    .write_valid(residual_write_valid),.write_ready(residual_write_ready),.write_row(residual_write_row),.write_data(residual_write_data),
    .norm_valid(residual_norm_valid),.norm_ready(residual_norm_ready),.norm_row(residual_norm_row),.norm_data(residual_norm_data)
  );
  always @(posedge clk)if(rst_n)begin
    if(residual_write_valid)begin
      if(residual_write_row!=={1'(TARGET_QUERY-1),8'(residual_writes)} || residual_write_data!==expected_bypass[residual_writes])
        $fatal(1,"FIXED_RESIDUAL_BYPASS_WRONG word=%0d",residual_writes);
      if(residual_write_ready)begin
        if(native_bypass_valid[residual_write_row] || $isunknown(residual_write_data))$fatal(1,"CONNECTED_BYPASS_ROW_REUSED");
        native_bypass_valid[residual_write_row]<=1;
        $display("FIXED_RESIDUAL_BYPASS word=%0d data=%058h",residual_writes,residual_write_data);
        $fdisplay(bypass_file,"%058h",residual_write_data);residual_writes++;
      end
    end
    if(residual_norm_valid)begin
      if(residual_norm_row!=={1'(TARGET_QUERY-1),8'(residual_norms)} || residual_norm_data!==expected_normal[residual_norms])
        $fatal(1,"FIXED_RESIDUAL_NORM_WRONG word=%0d",residual_norms);
      if(residual_norm_ready)begin
        if(native_residual_valid[residual_norm_row] || $isunknown(residual_norm_data))$fatal(1,"CONNECTED_RESIDUAL_ROW_REUSED");
        native_residual_valid[residual_norm_row]<=1;
        $display("FIXED_RESIDUAL_NORM word=%0d data=%032h",residual_norms,residual_norm_data);
        $fdisplay(norm_file,"%032h",residual_norm_data);residual_norms++;
      end
    end
  end

  tri_oracle_projection_requantizer quantizer (
    .clk,.rst_n,.cancel,.in_valid(projection_out_valid),.in_ready(projection_out_ready),
    .in_tag(projection_out_tag),.in_token(projection_out_token),.in_last(projection_out_last),
    .in_count(projection_out_count),.in_channels(projection_out_channels),.in_data(projection_out_data),
    .context_exponent(c_unit),.weight_exponents(quant_weight_units),.output_exponents(quant_output_units),
    .out_valid(quant_out_valid),.out_ready(quant_out_ready),.out_tag(quant_tag),.out_token(quant_token),
    .out_last(quant_last),.out_packet_last(quant_packet_last),.out_count(quant_count),
    .out_channels(quant_channels),.out_data(quant_data),.idle(quant_idle),.fault(quant_fault)
  );
  always @(posedge clk)if(rst_n)begin
    if(quant_fault)$fatal(1,"SHARED_QUANTIZER_UNEXPECTED_FAULT");
    if(quant_out_valid && quant_out_ready)begin
      if(quant_count!=8 || quant_token!=0 || !quant_last ||
         quant_tag!==32'h80000000+32'(quant_values/160) ||
         quant_packet_last!==(quant_values%160==152 || quant_values==2040) ||
         quant_data!==quant_expected[quant_values/8] || !c_lease || !co_route || finish_seen)
        $fatal(1,"SHARED_QUANTIZED_WORD_WRONG index=%0d",quant_words);
      for(int lane=0;lane<8;lane++)
        if(quant_channels[lane*16+:16]!==16'(quant_values+lane))
          $fatal(1,"SHARED_QUANTIZED_CHANNEL_WRONG");
      $display("SHARED_QUANTIZED_WORD index=%0d tag=%08h token=%0d source_last=%0d packet_last=%0d count=%0d channels=%032h data=%016h",
        quant_words,quant_tag,quant_token,quant_last,quant_packet_last,quant_count,quant_channels,quant_data);
      quant_values+=8;quant_words++;
    end
    if(co_finish_valid && co_finish_ready && (quant_values!=2048 || !quant_idle))
      $fatal(1,"SHARED_QUANTIZED_EARLY_FINISH");
  end
`endif

  always_comb begin
    attention_bus='0;
    attention_bus.rst_n=rst_n;
    attention_bus.load_valid=fabric_load_valid;attention_bus.load_core=fabric_load_core;
    attention_bus.load_kind=fabric_load_kind;attention_bus.load_addr=fabric_load_addr;
    attention_bus.load_data=fabric_load_data;attention_bus.load_rows=fabric_load_rows;
    attention_bus.cmd_valid=fabric_cmd_valid;attention_bus.cmd_clusters=fabric_cmd_clusters;
    attention_bus.cmd_weight=fabric_cmd_weight;attention_bus.cmd_mask=fabric_cmd_mask;
    attention_bus.cmd_activation=fabric_cmd_activation;attention_bus.cmd_output=fabric_cmd_output;
    attention_bus.cmd_accumulate=fabric_cmd_accumulate;attention_bus.cmd_reduce=fabric_cmd_reduce;
    attention_bus.core_select=fabric_core_select;attention_bus.activation_reloaded=fabric_activation_reloaded;
    attention_bus.out_ready=fabric_out_ready;
    raw_fabric_load_error=attention_return.load_error;
    fabric_cmd_ready=attention_return.cmd_ready;fabric_out_valid=attention_return.out_valid;
    fabric_out_slot=attention_return.out_output;fabric_out_data=attention_return.out_data;
    physical_softmax_request=(co_route || ff_phase || qkv_phase) ? '0 : softmax_request;
    softmax_response=(co_route || ff_phase || qkv_phase) ? '0 : physical_softmax_response;
    projection_req_ready=qkv_phase ? qkv_read_req_ready:p_ready;
    projection_rsp_valid=qkv_phase ? qkv_read_rsp_valid:p_rsp_valid;
    projection_rsp_last=qkv_phase ? qkv_read_rsp_last:p_rsp_last;
    projection_rsp_error=qkv_phase ? 1'b0:p_rsp_error;
    projection_rsp_data=qkv_phase ? {448'd0,qkv_read_rsp_data}:p_rsp_data;
    p_valid=!qkv_phase && projection_req_valid;p_address=projection_req_address;p_length={1'b0,projection_req_length};
    p_rsp_ready=!qkv_phase && projection_rsp_ready;
    external_req_ready=rst_n && !external_serving && !external_rsp_valid && cycle%5!=0;
    external_rsp_last=external_remaining==1;
    external_rsp_error=projection_fault_case && projection_weight_words==0;
    external_rsp_data={448'b0,output_weights[external_word]};
  end
  tri_oracle_projection_frame_guard frame_guard (
    .frame_valid(co_frame_valid),.cfg_valid(projection_cfg_valid),.cfg_ready(projection_cfg_ready),
    .window_idle(projection_window_idle
`ifdef QUANTIZED_PROJECTION
      && quant_idle && !residual_write_valid && !residual_norm_valid
`endif
    ),.outer_cancel(cancel
`ifdef QUANTIZED_PROJECTION
      || quant_fault
`endif
    ),.done_valid(projection_done_valid),.done_error(projection_done_error),
    .admitted_valid(projection_admitted_valid),.command_idle(projection_command_idle),
    .projection_idle(projection_complete_idle),.frame_cancel
  );
  tri_oracle_fabric_owner_mux shared_owner (
    .rst_n,.projection_owned(co_route || ff_phase || qkv_phase),.attention_request(attention_bus),.projection_request(projection_bus),
    .fabric_request(physical_bus),.fabric_response(physical_return),
    .attention_response(attention_return),.projection_response(projection_return)
  );
 // Verification-only external memory endpoints behind the actual shared bus.
 // Residual storage is populated by accepted bus beats, committed at ack.
 localparam logic[63:0] ResidualBase=64'h00000013ffff0000;
 localparam logic[63:0] FinalScaleBase=64'h4000;
 logic h_cfg_valid=0,h_cfg_ready,h_source_done_valid=0,h_source_done_ready;
 logic h_captured_valid,h_captured_error,h_start_ready,h_norm_done,h_fault;
 logic[31:0] h_captured_tag;
 logic[7:0] h_captured_code,h_fault_code;
 logic[3:0] h_token,fc_consumer_token;
 logic[8:0] h_strip;
 logic h_stats_valid,h_stats_last,h_replay_valid,h_replay_last,fc_stats_ready,fc_replay_ready,fc_cfg_accepted;
 logic[127:0] h_stats_data,h_replay_data;
 logic h_release_valid=0,h_release_ready;
 logic[1:0] h_scalar_req_valid,h_scalar_req_ready,h_scalar_rsp_valid,h_scalar_rsp_ready,h_scalar_rsp_last,h_scalar_rsp_error;
 logic[127:0] h_scalar_req_address,h_scalar_rsp_data;
 logic[9:0] h_scalar_req_length;
 logic fc_r_req_valid,fc_r_req_ready,fc_r_rsp_valid,fc_r_rsp_ready,fc_r_rsp_last,fc_r_rsp_error;
 logic[63:0] fc_r_req_address,fc_r_rsp_data;
 logic[4:0] fc_r_req_length;
 logic fs_r_req_valid,fs_r_req_ready,fs_r_rsp_valid,fs_r_rsp_ready,fs_r_rsp_last,fs_r_rsp_error;
 logic[63:0] fs_r_req_address,fs_r_rsp_data;
 logic[4:0] fs_r_req_length;
 logic fc_w_req_valid,fc_w_req_ready,fc_w_data_valid,fc_w_data_ready,fc_w_data_last,fc_w_rsp_valid,fc_w_rsp_ready,fc_w_rsp_error;
 logic[63:0] fc_w_address,fc_w_data;
 logic[4:0] fc_w_length;
 logic[7:0] fc_w_strobe;
 logic fs_w_req_valid,fs_w_req_ready,fs_w_data_valid,fs_w_data_ready,fs_w_data_last,fs_w_rsp_valid,fs_w_rsp_ready,fs_w_rsp_error;
 logic[63:0] fs_w_address,fs_w_data;
 logic[4:0] fs_w_length;
 logic[7:0] fs_w_strobe;
 logic wb_bank_read_valid,wb_bank_read_ready,wb_bank_response_valid,wb_bank_response_ready,wb_bank_response_error;
 logic[8:0] wb_bank_read_row;
 logic[231:0] wb_bank_response_data;
 logic wb_scale_req_valid,wb_scale_req_ready,wb_scale_rsp_valid,wb_scale_rsp_ready,wb_scale_rsp_last,wb_scale_rsp_error;
 logic[63:0] wb_scale_req_address,wb_scale_rsp_data,wb_scale_server_address,wb_scale_server_data;
 logic[4:0] wb_scale_req_length;
 logic h_mr_req_valid,h_mr_req_ready,h_mr_rsp_valid,h_mr_rsp_ready,h_mr_last,h_mr_error;
 logic[63:0] h_mr_address,h_mr_data;
 logic[4:0] h_mr_length;
 logic h_mw_req_valid,h_mw_req_ready,h_mw_data_valid,h_mw_data_ready,h_mw_last,h_mw_rsp_valid,h_mw_rsp_ready,h_mw_error;
 logic[63:0] h_mw_address,h_mw_data;
 logic[4:0] h_mw_length;
 logic[7:0] h_mw_strobe;
 typedef enum logic[1:0] {ReadIdle,ReadFeedforward,ReadResidual,ReadScale} read_owner_t;
 typedef enum logic[1:0] {WriteIdle,WriteFeedforward,WriteResidual} write_owner_t;
 read_owner_t memory_read_owner=ReadIdle;
 write_owner_t memory_write_owner=WriteIdle;
 logic[63:0] residual_memory[2048];
 bit residual_written[2048],residual_committed[2048];
 int residual_write_word=0,residual_write_beat=0,residual_ack_delay=0;
 bit residual_ack_pending=0;
 int residual_read_word=0,residual_read_beat=0,residual_read_delay=0,scale_read_delay=0;
 logic[63:0] scale_read_address=0;
 int shared_residual_write_beats=0,shared_residual_write_acks=0,shared_residual_read_packets=0,shared_residual_read_beats=0;
 int shared_ff_read_requests=0,shared_ff_write_requests=0,shared_scale_requests=0;
 int shared_stats_rows=0,shared_replay_rows=0,shared_bypass_rows=0,shared_read_contention=0;
 bit residual_fault_injected=0;

 always_comb begin
  h_scalar_req_valid={wb_scale_req_valid,fc_r_req_valid};
  h_scalar_req_address={wb_scale_req_address,fc_r_req_address};
  h_scalar_req_length={wb_scale_req_length,fc_r_req_length};
  h_scalar_rsp_ready={wb_scale_rsp_ready,fc_r_rsp_ready};
  fc_r_req_ready=h_scalar_req_ready[0];wb_scale_req_ready=h_scalar_req_ready[1];
  fc_r_rsp_valid=h_scalar_rsp_valid[0];fc_r_rsp_last=h_scalar_rsp_last[0];fc_r_rsp_error=h_scalar_rsp_error[0];
  fc_r_rsp_data=h_scalar_rsp_data[63:0];
  wb_scale_rsp_valid=h_scalar_rsp_valid[1];wb_scale_rsp_last=h_scalar_rsp_last[1];wb_scale_rsp_error=h_scalar_rsp_error[1];
  wb_scale_rsp_data=h_scalar_rsp_data[127:64];
 end
 tri_oracle_external_residual_frame residual_frame(
  .clk,.rst_n,.cfg_valid(h_cfg_valid),.cfg_ready(h_cfg_ready),.cfg_tag(32'h39300001),
  .cfg_base(ResidualBase),.cfg_rows(10'd512),.cfg_tokens(5'd2),.cfg_strips(9'd256),.abort_frame(1'b0),
  .bypass_valid(residual_write_valid),.bypass_ready(residual_write_ready),.bypass_tag(32'h39300001),
  .bypass_row(residual_write_row),.bypass_data(residual_write_data),
  .normalization_valid(residual_norm_valid),.normalization_ready(residual_norm_ready),.normalization_tag(32'h39300001),
  .normalization_row(residual_norm_row),.normalization_data(residual_norm_data),
  .source_done_valid(h_source_done_valid),.source_done_ready(h_source_done_ready),.source_done_error(1'b0),.source_done_tag(32'h39300001),
  .captured_valid(h_captured_valid),.captured_error(h_captured_error),.captured_tag(h_captured_tag),.captured_code(h_captured_code),
  .normalization_start_valid(fc_cfg_accepted),.normalization_start_ready(h_start_ready),.normalization_done(h_norm_done),
  .frame_fault(h_fault),.fault_code(h_fault_code),.normalization_token(h_token),.normalization_strip(h_strip),.consumer_token(fc_consumer_token),
  .stats_valid(h_stats_valid),.stats_last(h_stats_last),.stats_ready(fc_stats_ready),.stats_data(h_stats_data),
  .replay_valid(h_replay_valid),.replay_last(h_replay_last),.replay_ready(fc_replay_ready),.replay_data(h_replay_data),
  .bank_read_valid(wb_bank_read_valid),.bank_read_ready(wb_bank_read_ready),.bank_read_row(wb_bank_read_row),
  .bank_response_valid(wb_bank_response_valid),.bank_response_ready(wb_bank_response_ready),
  .bank_response_error(wb_bank_response_error),.bank_response_data(wb_bank_response_data),
  .release_valid(h_release_valid),.release_ready(h_release_ready),
  .scalar_req_valid(h_scalar_req_valid),.scalar_req_ready(h_scalar_req_ready),.scalar_req_address(h_scalar_req_address),.scalar_req_length(h_scalar_req_length),
  .scalar_rsp_valid(h_scalar_rsp_valid),.scalar_rsp_ready(h_scalar_rsp_ready),.scalar_rsp_data(h_scalar_rsp_data),
  .scalar_rsp_last(h_scalar_rsp_last),.scalar_rsp_error(h_scalar_rsp_error),
  .scalar_write_req_valid(fc_w_req_valid),.scalar_write_req_ready(fc_w_req_ready),.scalar_write_address(fc_w_address),.scalar_write_length(fc_w_length),
  .scalar_write_data_valid(fc_w_data_valid),.scalar_write_data_ready(fc_w_data_ready),.scalar_write_data_last(fc_w_data_last),
  .scalar_write_data(fc_w_data),.scalar_write_strobe(fc_w_strobe),.scalar_write_rsp_valid(fc_w_rsp_valid),
  .scalar_write_rsp_ready(fc_w_rsp_ready),.scalar_write_rsp_error(fc_w_rsp_error),
  .mr_req_valid(h_mr_req_valid),.mr_req_ready(h_mr_req_ready),.mr_address(h_mr_address),.mr_length(h_mr_length),
  .mr_rsp_valid(h_mr_rsp_valid),.mr_rsp_ready(h_mr_rsp_ready),.mr_last(h_mr_last),.mr_error(h_mr_error),.mr_data(h_mr_data),
  .mw_req_valid(h_mw_req_valid),.mw_req_ready(h_mw_req_ready),.mw_address(h_mw_address),.mw_length(h_mw_length),
  .mw_data_valid(h_mw_data_valid),.mw_data_ready(h_mw_data_ready),.mw_last(h_mw_last),.mw_data(h_mw_data),.mw_strobe(h_mw_strobe),
  .mw_rsp_valid(h_mw_rsp_valid),.mw_rsp_ready(h_mw_rsp_ready),.mw_error(h_mw_error)
 );
 always_comb begin
  fs_r_req_valid=0;fs_r_req_address=h_mr_address;fs_r_req_length=h_mr_length;fs_r_rsp_ready=0;
  h_mr_req_ready=0;h_mr_rsp_valid=0;h_mr_last=0;h_mr_error=0;h_mr_data=0;
  wb_scale_server_address=scale_read_address;
  case(memory_read_owner)
   ReadIdle:begin
    if(h_mr_address>=ResidualBase && h_mr_address<ResidualBase+16384)
     h_mr_req_ready=cycle%4!=0;
    else if(h_mr_address>=FinalScaleBase && h_mr_address<FinalScaleBase+1024)
     h_mr_req_ready=cycle%5!=0;
    else begin fs_r_req_valid=h_mr_req_valid;h_mr_req_ready=fs_r_req_ready;end
   end
   ReadFeedforward:begin
    h_mr_rsp_valid=fs_r_rsp_valid;h_mr_last=fs_r_rsp_last;h_mr_error=fs_r_rsp_error;h_mr_data=fs_r_rsp_data;
    fs_r_rsp_ready=h_mr_rsp_ready;
   end
   ReadResidual:begin
    h_mr_rsp_valid=residual_read_delay==0;h_mr_last=residual_read_beat==7;
    h_mr_data=residual_memory[11'($unsigned(residual_read_word+residual_read_beat))];
   end
   ReadScale:begin h_mr_rsp_valid=scale_read_delay==0;h_mr_last=1;h_mr_data=wb_scale_server_data;end
  endcase
  fs_w_req_valid=0;fs_w_address=h_mw_address;fs_w_length=h_mw_length;
  fs_w_data_valid=0;fs_w_data_last=h_mw_last;fs_w_data=h_mw_data;fs_w_strobe=h_mw_strobe;fs_w_rsp_ready=0;
  h_mw_req_ready=0;h_mw_data_ready=0;h_mw_rsp_valid=0;h_mw_error=0;
  case(memory_write_owner)
   WriteIdle:begin
    if(h_mw_address>=ResidualBase && h_mw_address<ResidualBase+16384)
     h_mw_req_ready=cycle%5!=0;
    else begin fs_w_req_valid=h_mw_req_valid;h_mw_req_ready=fs_w_req_ready;end
   end
   WriteFeedforward:begin
    fs_w_data_valid=h_mw_data_valid;h_mw_data_ready=fs_w_data_ready;
    h_mw_rsp_valid=fs_w_rsp_valid;h_mw_error=fs_w_rsp_error;fs_w_rsp_ready=h_mw_rsp_ready;
   end
   WriteResidual:begin
    h_mw_data_ready=!residual_ack_pending && cycle%3!=0;
    h_mw_rsp_valid=residual_ack_pending && residual_ack_delay==0;
   end
  endcase
  if(!rst_n)begin
   fs_r_req_valid=0;fs_r_rsp_ready=0;h_mr_req_ready=0;h_mr_rsp_valid=0;
   fs_w_req_valid=0;fs_w_data_valid=0;fs_w_rsp_ready=0;h_mw_req_ready=0;h_mw_data_ready=0;h_mw_rsp_valid=0;
  end
 end
 always @(posedge clk)begin : shared_external_memory
  if(!rst_n)begin
   memory_read_owner<=ReadIdle;memory_write_owner<=WriteIdle;
   residual_ack_pending<=0;residual_ack_delay<=0;residual_write_beat<=0;
   residual_read_delay<=0;residual_read_beat<=0;scale_read_delay<=0;
   for(int word=0;word<2048;word++)begin residual_written[word]<=0;residual_committed[word]<=0;end
  end else begin
   if(h_fault)$fatal(1,"FULL_MEMORY_FRAME_FAULT code=%0d",h_fault_code);
   if(fc_cfg_accepted && !h_start_ready)$fatal(1,"FULL_MEMORY_FF_DESCRIPTOR_WITHOUT_LEASE");
   if(h_scalar_req_valid==2'b11)shared_read_contention++;
   if(h_stats_valid && fc_stats_ready)shared_stats_rows++;
   if(h_replay_valid && fc_replay_ready)shared_replay_rows++;
   if(wb_bank_response_valid && wb_bank_response_ready)shared_bypass_rows++;
   if(h_mw_req_valid && h_mw_req_ready)begin
    if(memory_write_owner!=WriteIdle)$fatal(1,"FULL_MEMORY_WRITE_OWNER_BUSY");
    if(h_mw_address>=ResidualBase && h_mw_address<ResidualBase+16384)begin
     if(h_mw_length!==5'd8 || h_mw_address[5:0]!=0 || h_mw_address+64>ResidualBase+16384)
      $fatal(1,"FULL_MEMORY_RESIDUAL_WRITE_DESCRIPTOR");
     residual_write_word<=int'((h_mw_address-ResidualBase)>>3);residual_write_beat<=0;
     memory_write_owner<=WriteResidual;
     $display("FULL_MEMORY_WRITE_REQUEST address=%016h length=8",h_mw_address);
    end else begin
     if(!ff_phase)$fatal(1,"FULL_MEMORY_FF_WRITE_BEFORE_PHASE");
     memory_write_owner<=WriteFeedforward;shared_ff_write_requests++;
    end
   end
   if(h_mw_data_valid && h_mw_data_ready && memory_write_owner==WriteResidual)begin
    if(h_mw_strobe!==8'hff || h_mw_last!==(residual_write_beat==7) ||
       residual_written[11'($unsigned(residual_write_word+residual_write_beat))])$fatal(1,"FULL_MEMORY_RESIDUAL_WRITE_DATA");
    residual_memory[11'($unsigned(residual_write_word+residual_write_beat))]<=h_mw_data;
    residual_written[11'($unsigned(residual_write_word+residual_write_beat))]<=1;
    shared_residual_write_beats++;
    $display("FULL_MEMORY_WRITE_BEAT word=%0d data=%016h",residual_write_word+residual_write_beat,h_mw_data);
    if(h_mw_last)begin residual_ack_pending<=1;residual_ack_delay<=3;end
    else residual_write_beat<=residual_write_beat+1;
   end
   if(residual_ack_delay>0)residual_ack_delay<=residual_ack_delay-1;
   if(h_mw_rsp_valid && h_mw_rsp_ready)begin
    if(memory_write_owner==WriteResidual)begin
     for(int word=0;word<8;word++)residual_committed[11'($unsigned(residual_write_word+word))]<=1;
     residual_ack_pending<=0;shared_residual_write_acks++;
     $display("FULL_MEMORY_WRITE_ACK index=%0d",shared_residual_write_acks);
    end
    memory_write_owner<=WriteIdle;
   end
   if(h_mr_req_valid && h_mr_req_ready)begin
    if(memory_read_owner!=ReadIdle)$fatal(1,"FULL_MEMORY_READ_OWNER_BUSY");
    if(h_mr_address>=ResidualBase && h_mr_address<ResidualBase+16384)begin
     if(h_mr_length!==5'd8 || h_mr_address[5:0]!=0 || h_mr_address+64>ResidualBase+16384)
      $fatal(1,"FULL_MEMORY_RESIDUAL_READ_DESCRIPTOR");
     residual_read_word<=int'((h_mr_address-ResidualBase)>>3);residual_read_beat<=0;residual_read_delay<=3;
     memory_read_owner<=ReadResidual;shared_residual_read_packets++;
     $display("FULL_MEMORY_READ_REQUEST address=%016h length=8",h_mr_address);
    end else if(h_mr_address>=FinalScaleBase && h_mr_address<FinalScaleBase+1024)begin
     if(h_mr_length!==5'd1 || h_mr_address[2:0]!=0)$fatal(1,"FULL_MEMORY_SCALE_DESCRIPTOR");
     scale_read_address<=h_mr_address;scale_read_delay<=4;memory_read_owner<=ReadScale;shared_scale_requests++;
    end else begin
     if(!ff_phase)$fatal(1,"FULL_MEMORY_FF_READ_BEFORE_PHASE");
     memory_read_owner<=ReadFeedforward;shared_ff_read_requests++;
    end
   end
   if(residual_read_delay>0)residual_read_delay<=residual_read_delay-1;
   if(scale_read_delay>0)scale_read_delay<=scale_read_delay-1;
   if(h_mr_rsp_valid && h_mr_rsp_ready)begin
    if(memory_read_owner==ReadResidual)begin
     if(!residual_committed[11'($unsigned(residual_read_word+residual_read_beat))])$fatal(1,"FULL_MEMORY_UNACKNOWLEDGED_READ");
     shared_residual_read_beats++;
     $display("FULL_MEMORY_READ_BEAT word=%0d data=%016h last=%0d",residual_read_word+residual_read_beat,h_mr_data,h_mr_last);
     if(!h_mr_last)begin residual_read_beat<=residual_read_beat+1;residual_read_delay<=cycle%3;end
    end
    if(h_mr_last)memory_read_owner<=ReadIdle;
   end
  end
 end

  tri_oracle_connected_ff_agent #(.PREFIX_ONLY(CONNECTED_PREFIX_ONLY),.CORRUPT_NATIVE_RESIDUAL(1'b0)) projection (
    .ff_result_ready(final_raw_ready),.ff_down_valid(final_raw_valid),
    .ff_result_last(final_raw_last),.ff_sink_ready(final_sink_ready),
    .ff_result_tag(final_raw_tag),.ff_result_token(final_raw_token),
    .ff_result_start(final_raw_start),.ff_result_count(final_raw_count),.ff_result_data(final_raw_data),
    .start_ff(ff_phase),.external_frame_available(h_captured_valid && !h_captured_error),
    .external_stats_valid(h_stats_valid),.external_stats_last(h_stats_last),.external_stats_data(h_stats_data),
    .external_replay_valid(h_replay_valid),.external_replay_last(h_replay_last),.external_replay_data(h_replay_data),
    .external_strip(h_strip),.external_stats_ready(fc_stats_ready),.external_replay_ready(fc_replay_ready),
    .external_consumer_token(fc_consumer_token),.external_cfg_accepted(fc_cfg_accepted),
    .fixture_loaded(ff_fixture_loaded),.ff_done,
    .client_r_req_valid(fc_r_req_valid),
    .client_r_req_ready(fc_r_req_ready),
    .client_r_req_address(fc_r_req_address),
    .client_r_req_length(fc_r_req_length),
    .client_r_rsp_valid(fc_r_rsp_valid),
    .client_r_rsp_ready(fc_r_rsp_ready),
    .client_r_rsp_last(fc_r_rsp_last),
    .client_r_rsp_error(fc_r_rsp_error),
    .client_r_rsp_data(fc_r_rsp_data),
    .server_r_req_valid(fs_r_req_valid),
    .server_r_req_ready(fs_r_req_ready),
    .server_r_req_address(fs_r_req_address),
    .server_r_req_length(fs_r_req_length),
    .server_r_rsp_valid(fs_r_rsp_valid),
    .server_r_rsp_ready(fs_r_rsp_ready),
    .server_r_rsp_last(fs_r_rsp_last),
    .server_r_rsp_error(fs_r_rsp_error),
    .server_r_rsp_data(fs_r_rsp_data),
    .client_w_req_valid(fc_w_req_valid),
    .client_w_req_ready(fc_w_req_ready),
    .client_w_address(fc_w_address),
    .client_w_length(fc_w_length),
    .client_w_data_valid(fc_w_data_valid),
    .client_w_data_ready(fc_w_data_ready),
    .client_w_data_last(fc_w_data_last),
    .client_w_data(fc_w_data),
    .client_w_strobe(fc_w_strobe),
    .client_w_rsp_valid(fc_w_rsp_valid),
    .client_w_rsp_ready(fc_w_rsp_ready),
    .client_w_rsp_error(fc_w_rsp_error),
    .server_w_req_valid(fs_w_req_valid),
    .server_w_req_ready(fs_w_req_ready),
    .server_w_address(fs_w_address),
    .server_w_length(fs_w_length),
    .server_w_data_valid(fs_w_data_valid),
    .server_w_data_ready(fs_w_data_ready),
    .server_w_data_last(fs_w_data_last),
    .server_w_data(fs_w_data),
    .server_w_strobe(fs_w_strobe),
    .server_w_rsp_valid(fs_w_rsp_valid),
    .server_w_rsp_ready(fs_w_rsp_ready),
    .server_w_rsp_error(fs_w_rsp_error),
    .metadata_block(c_lease_block),.metadata_idle(c_actual_metadata_idle),.metadata_rebuilt(c_metadata_rebuilt),
    .metadata_ce_n(c_metadata_ce_n),.metadata_we_n(c_metadata_we_n),.shared_metadata_address(c_metadata_address),
    .metadata_write_data(c_metadata_write_data),.metadata_read_data(c_metadata_read),
    .clk,.rst_n,.raw_cfg_valid(shared_raw_cfg_valid),.raw_cfg_ready(shared_raw_cfg_ready),
    .raw_cfg_tag(shared_raw_cfg_tag),.raw_cfg_tokens(shared_raw_cfg_tokens),.raw_cfg_feature_words(10'd256),
    .raw_cfg_dense_rows(shared_raw_cfg_dense_rows),.raw_cfg_count(shared_raw_cfg_count),
    .raw_cfg_channels(shared_raw_cfg_channels),.raw_cfg_keep(shared_raw_cfg_keep),
    .raw_cfg_activation_base(shared_raw_activation_base),.raw_cfg_weight_base(shared_raw_weight_base),.raw_cfg_activation_stride(32'd2048),
    .raw_out_valid(shared_raw_out_valid),.raw_out_ready(shared_raw_out_ready),.raw_out_tag(shared_raw_out_tag),
    .raw_out_token(shared_raw_out_token),.raw_out_last(shared_raw_out_last),.raw_out_count(shared_raw_out_count),
    .raw_out_channels(shared_raw_out_channels),.raw_out_data(shared_raw_out_data),
    .raw_done_valid(shared_raw_done_valid),.raw_done_ready(shared_raw_done_ready),.raw_done_error(shared_raw_done_error),.raw_done_tag(shared_raw_done_tag),
    .raw_req_valid(projection_req_valid),.raw_req_ready(projection_req_ready),.raw_req_address(projection_req_address),.raw_req_length(projection_req_length),
    .raw_rsp_valid(projection_rsp_valid),.raw_rsp_ready(projection_rsp_ready),.raw_rsp_last(projection_rsp_last),.raw_rsp_error(projection_rsp_error),.raw_rsp_data(projection_rsp_data[63:0]),
    .backend_request(projection_bus),.backend_response(projection_return),
    .strip_request(ff_strip_request),.strip_response(ff_strip_response)
  );
  tri_oracle_connected_writeback_checker #(.PREFIX_ONLY(CONNECTED_PREFIX_ONLY)) final_writeback (
    .clk,.rst_n,.enable(ff_phase),.raw_valid(final_raw_valid),.raw_ready(final_raw_ready),
    .raw_last(final_raw_last),.sink_ready(final_sink_ready),.raw_tag(final_raw_tag),
    .raw_token(final_raw_token),.raw_start(final_raw_start),.raw_count(final_raw_count),
    .raw_data(final_raw_data),.frame_fault(h_fault),
    .external_bank_read_valid(wb_bank_read_valid),.external_bank_read_ready(wb_bank_read_ready),.external_bank_read_row(wb_bank_read_row),
    .external_bank_response_valid(wb_bank_response_valid),.external_bank_response_ready(wb_bank_response_ready),
    .external_bank_response_error(wb_bank_response_error),.external_bank_response_data(wb_bank_response_data),
    .external_scale_req_valid(wb_scale_req_valid),.external_scale_req_ready(wb_scale_req_ready),
    .external_scale_req_address(wb_scale_req_address),.external_scale_req_length(wb_scale_req_length),
    .external_scale_rsp_valid(wb_scale_rsp_valid),.external_scale_rsp_ready(wb_scale_rsp_ready),
    .external_scale_rsp_last(wb_scale_rsp_last),.external_scale_rsp_error(wb_scale_rsp_error),.external_scale_rsp_data(wb_scale_rsp_data),
    .scale_server_address(wb_scale_server_address),.scale_server_data(wb_scale_server_data),
    .complete(final_complete),.idle(final_idle)
  );
  always @(posedge clk)if(rst_n)begin
    if(external_req_valid && external_req_ready)begin
      if(external_req_wide || external_req_address<64'h200000 || external_req_address[2:0]!=0 ||
         external_req_length==0 || external_req_length>16 ||
         (external_req_address-64'h200000)/8+64'(external_req_length)>524288)
        $fatal(1,"SHARED_NON_WEIGHT_EXTERNAL_READ address=%016h",external_req_address);
      external_word<=20'((external_req_address-64'h200000)/8);
      external_remaining<=external_req_length;external_serving<=1;
      $display("SHARED_WEIGHT_REQUEST group=%0d address=%016h length=%0d",projection_group,external_req_address,external_req_length);
    end
    if(external_serving && !external_rsp_valid && cycle%3==0)external_rsp_valid<=1;
    if(external_rsp_valid && external_rsp_ready)begin
      projection_weight_words++;
      if(external_remaining==1)begin external_rsp_valid<=0;external_serving<=0;external_remaining<=0;end
      else begin external_word<=external_word+20'd1;external_remaining<=external_remaining-6'd1;end
    end
    if(w_valid && w_ready)context_word_inflight=int'(w_word);
    if(w_rsp_valid && w_rsp_ready)begin
      if(!c_lease || !co_route || w_rsp_error || w_data!==converted_words[context_word_inflight])
        $fatal(1,"SHARED_CONTEXT_SOURCE_WRONG word=%0d",context_word_inflight);
      projection_context_words++;
      $display("SHARED_CONTEXT_READ group=%0d word=%0d data=%016h",projection_group,context_word_inflight,w_data);
    end
    if(co_finish_valid && co_finish_ready)begin
      if(projection_values!=2048 || !projection_complete_idle || external_serving || external_rsp_valid || residual_writes!=256 || residual_norms!=256)
        $fatal(1,"SHARED_EARLY_FINISH");
      finish_seen=1;
    end
    if((co_route || ff_phase || qkv_phase) && (attention_return.cmd_ready || attention_return.out_valid!=0 || attention_return.load_error))
      $fatal(1,"SHARED_INACTIVE_ATTENTION_HANDSHAKE");
    if(!(co_route || ff_phase || qkv_phase) && (projection_return.cmd_ready || projection_return.out_valid!=0 || projection_return.load_error))
      $fatal(1,"SHARED_INACTIVE_PROJECTION_HANDSHAKE");
  end
  int row_controller_commands=0;
  always @(posedge clk)if(rst_n)begin
    if(ff_phase && c_metadata_rebuilt)metadata_rebuilds++;
    if(projection_admitted_valid && projection_cfg_ready)row_controller_commands++;
    if(c_lease_block && projection.ff_cfg_ready)$fatal(1,"SHARED_METADATA_BLOCKED_FF_DESCRIPTOR_READY");
    if(!ff_phase && (projection.ff_write_request || projection.ff_write_data || projection.ff_result_valid || projection.ff_terminal_valid))
      $fatal(1,"ROW_CONTROLLER_UNSOLICITED_FEEDFORWARD_TRAFFIC");
    if(co_finish_valid && co_finish_ready && !projection_fault_case)begin
      if(row_controller_commands!=13)$fatal(1,"ROW_CONTROLLER_PROJECTION_GROUP_COUNT got=%0d",row_controller_commands);
      $display("ROW_CONTROLLER_ATTENTION_PROJECTION_PORT_PASS commands=%0d",row_controller_commands);
    end
  end
  task automatic project_group(input int group_index);
    int group_count;logic [5119:0] saved_projection;
    group_count=group_index==12?128:160;projection_group=group_index;
    @(negedge clk);projection_cfg_tag=32'h80000000+32'(group_index);
    projection_cfg_count=8'(group_count);projection_cfg_channels=0;projection_cfg_keep=0;
    for(int row=0;row<group_count;row++)begin
      projection_cfg_channels[row*16+:16]=16'(group_index*160+row);
      projection_cfg_keep[row]=1;
    end
    projection_cfg_valid=1;
    do @(posedge clk);while(!(projection_cfg_ready && co_frame_valid));
    @(negedge clk);projection_cfg_valid=0;projection_cfg_tag='1;projection_cfg_count=0;
    projection_cfg_channels='1;projection_cfg_keep=0;
    if(group_index==12)begin c_finish=1;projection_cfg_valid=1;end
    while(!projection_out_valid && !projection_done_valid)@(negedge clk);
    if(projection_fault_case)begin
      if(!projection_done_valid || !projection_done_error || projection_values!=0 ||
         projection_weight_words!=16 || external_serving || external_rsp_valid || !c_lease || !co_route || co_done_valid)
        $fatal(1,"SHARED_ERROR_BURST_NOT_DRAINED");
      repeat(4)begin
        @(negedge clk);
        if(!c_lease || !co_route || co_done_valid || !projection_done_valid)
          $fatal(1,"SHARED_ERROR_EARLY_RELEASE");
      end
      projection_cfg_valid=1;c_finish=1;projection_done_ready=1;
      @(negedge clk);projection_done_ready=0;
      repeat(64)@(negedge clk);
      if(!co_done_valid || !co_done_error || !co_reset_required || co_error_code!=8'h02 ||
         c_lease || co_route || co_frame_valid || cfg_ready || projection_values!=0)
        $fatal(1,"SHARED_FRAME_ERROR_NOT_FORWARDED");
      $display("SHARED_PROJECTION_ERROR_DRAIN_PASS accepted_weight_beats=16 output_values=0 reset_required=1 held_offer=1");
      $finish;
    end
    if(projection_done_valid)$fatal(1,"SHARED_PROJECTION_FAILED group=%0d",group_index);
    saved_projection=projection_out_data;
    repeat(4)begin
      if(!projection_out_valid || projection_out_data!==saved_projection || !c_lease || !co_route || finish_seen)
        $fatal(1,"SHARED_OUTPUT_NOT_RETAINED");
      @(negedge clk);
    end
    if(projection_out_tag!==32'h80000000+32'(group_index) || projection_out_token!=0 ||
       !projection_out_last || projection_out_count!=group_count)
      $fatal(1,"SHARED_PROJECTION_OUTPUT_METADATA");
    for(int row=0;row<group_count;row++)begin
      if(projection_out_channels[row*16+:16]!==16'(group_index*160+row) ||
         $signed(projection_out_data[row*32+:32])!==output_accumulators[group_index*160+row])
        $fatal(1,"SHARED_PROJECTION_DOT_WRONG channel=%0d got=%0d expected=%0d",group_index*160+row,$signed(projection_out_data[row*32+:32]),output_accumulators[group_index*160+row]);
      $display("SHARED_PROJECTION_DOT channel=%0d raw=%0d",group_index*160+row,$signed(projection_out_data[row*32+:32]));
      projection_values++;
    end
`ifdef QUANTIZED_PROJECTION
    for(int word_index=0;word_index<group_count/8;word_index++)begin
      repeat(word_index%3+1)@(negedge clk);
      if(!quant_out_valid || !c_lease || !co_route || finish_seen)
        $fatal(1,"SHARED_QUANTIZED_OUTPUT_NOT_HELD");
      quant_accept_enable=1;
      do @(posedge clk);while(!quant_out_ready);
      @(negedge clk);quant_accept_enable=0;
    end
`else
    projection_out_ready=1;@(negedge clk);projection_out_ready=0;
`endif
    while(!projection_done_valid)@(negedge clk);
    if(projection_done_error || projection_done_tag!==32'h80000000+32'(group_index))
      $fatal(1,"SHARED_PROJECTION_DONE_ERROR");
    repeat(3)begin @(negedge clk);if(!projection_done_valid || !c_lease || finish_seen)$fatal(1,"SHARED_COMMAND_NOT_HELD");end
    projection_done_ready=1;@(negedge clk);projection_done_ready=0;
    $display("SHARED_PROJECTION_GROUP_PASS group=%0d values=%0d",group_index,group_count);
  endtask

 tri_oracle_metadata_context_handoff collector (
  .clk,.rst_n(co_collector_rst_n),.cfg_valid(c_cfg_valid),.cfg_ready(c_cfg_ready),.cfg_tag(cfg_tag),.cfg_query(cfg_query[10:0]),.cfg_zero_exponent(9'sd0),
  .row_valid(co_row_valid),.row_ready(c_row_ready),.row_error(context_query!=16'(TARGET_QUERY) || context_epoch!=16'h44a1 || context_tag!=32'h90100004),
  .row_query(context_query[10:0]),.row_head(context_head),.row_data(context_data),.row_value_exponent(context_value_exponent),
  .metadata_idle(c_metadata_idle),.metadata_block(c_lease_block),.metadata_needs_rebuild(c_needs_rebuild),.metadata_rebuilt(c_metadata_rebuilt),.lease_active(c_lease),
  .metadata_ce_n(c_metadata_ce_n),.metadata_we_n(c_metadata_we_n),.metadata_address(c_metadata_address),
  .metadata_write_data(c_metadata_write_data),.metadata_read_data(c_metadata_read),
  .context_valid(c_valid),.context_tag(c_tag),.context_query(c_query),.context_exponent(c_unit),
  .read_req_valid(w_valid),.read_req_ready(w_ready),.read_req_word(w_word),
  .read_rsp_valid(w_rsp_valid),.read_rsp_ready(w_rsp_ready),.read_rsp_error(w_rsp_error),.read_rsp_data(w_data),
  .finish_valid(m_finish),.finish_ready(m_finish_ready),.done_valid(c_done),.done_ready(c_done_ready),.done_error(c_error)
 );
 tri_oracle_context_projection_window window (
  .clk,.rst_n(co_collector_rst_n),.projection_enabled(co_route),.client_idle(projection_command_idle),
  .req_valid(p_valid),.req_ready(p_ready),.req_wide(1'b0),.req_address(p_address),.req_length(p_length),
  .rsp_valid(p_rsp_valid),.rsp_ready(p_rsp_ready),.rsp_last(p_rsp_last),.rsp_error(p_rsp_error),.rsp_data(p_rsp_data),
  .external_req_valid,.external_req_ready,.external_req_wide,.external_req_address,.external_req_length,
  .external_rsp_valid,.external_rsp_last,.external_rsp_error,.external_rsp_ready,.external_rsp_data,
  .word_req_valid(w_valid),.word_req_ready(w_ready),.word_req_word(w_word),.word_rsp_valid(w_rsp_valid),.word_rsp_ready(w_rsp_ready),.word_rsp_error(w_rsp_error),.word_rsp_data(w_data),
  .finish_valid(co_finish_valid),.finish_ready(co_finish_ready),.memory_finish_valid(m_finish),.memory_finish_ready(m_finish_ready),.idle(projection_window_idle)
 );

 always #5 clk=~clk;
 always_comb fabric_load_error=raw_fabric_load_error || inject_load_error;
 tri_oracle_complete_head_broker dut(
  .cfg_valid(broker_cfg_valid_i),.cfg_ready(broker_cfg_ready_i),.cancel(broker_cancel_i),.busy(broker_busy_i),.*);
 tri_oracle_attention_context_commit commit_control (
  .clk,.rst_n,.cfg_valid,.cfg_ready,.cfg_heads,.cfg_tag,.cfg_query,.cfg_epoch,.cancel(frame_cancel),
  .broker_cfg_valid(broker_cfg_valid_i),.broker_cfg_ready(broker_cfg_ready_i),
  .collector_cfg_valid(c_cfg_valid),.collector_cfg_ready(c_cfg_ready),
  .broker_row_valid(context_valid),.broker_row_ready(context_ready),.broker_all_collected(all_contexts_collected),
  .broker_row_head(context_head),.broker_row_query(context_query),.broker_row_epoch(context_epoch),.broker_row_tag(context_tag),
  .collector_row_valid(co_row_valid),.collector_row_ready(c_row_ready),
  .broker_done_valid(done_valid),.broker_done_ready(done_ready),.broker_done_error(done_error),.broker_reset_required(reset_required),.broker_cancel(broker_cancel_i),
  .collector_context_valid(c_valid),.collector_done_valid(c_done),.collector_done_ready(c_done_ready),.collector_done_error(c_error),.collector_rst_n(co_collector_rst_n),
  .projection_idle(projection_complete_idle),.frame_valid(co_frame_valid),.context_route_enable(co_route),
  .finish_valid(c_finish),.finish_ready(c_finish_ready),.collector_finish_valid(co_finish_valid),.collector_finish_ready(co_finish_ready),
  .done_valid(co_done_valid),.done_ready(co_done_ready),.done_error(co_done_error),.reset_required(co_reset_required),.busy,.error_code(co_error_code)
 );
 always @(posedge clk)if(rst_n)begin
  if(broker_cfg_valid_i && broker_cfg_ready_i)
   $display("COMMIT_CONFIG query=%0d epoch=%04h tag=%08h",cfg_query,cfg_epoch,cfg_tag);
  if(done_valid && done_ready)
   $display("COMMIT_BROKER_TERMINAL error=%0d seen=%08h",done_error,commit_control.seen);
  if(co_frame_valid && !commit_reported)begin
   commit_reported=1;
   $display("COMMIT_FRAME_READY query=%0d tag=%08h exponent=%0d",c_query,c_tag,$signed(c_unit));
`ifdef QUANTIZED_PROJECTION
   $display("SHARED_PROJECTION_UNITS context=%0d weights=%064h outputs=%064h",$signed(c_unit),quant_weight_units,quant_output_units);
`endif
  end
  if(co_finish_valid && co_finish_ready)$display("COMMIT_FINISH_ACCEPTED");
  if(c_done && c_done_ready)$display("COMMIT_COLLECTOR_TERMINAL error=%0d",c_error);
 end
 tri_oracle_compute_fabric #(
  .AGGREGATOR_SIGN_BANK(1),.AGGREGATOR_MERGE_TABLE(1),.LOCAL_TOKEN_SIZES(1),
  .LOCAL_TOKEN_MERGE(1),.CORE_STRIP_PREDICTOR(1),.CORE_HEAD_PREDICTOR(1)
 ) fabric (
  .clk,.rst_n(physical_bus.rst_n),.load_valid(physical_bus.load_valid),.load_core(physical_bus.load_core),.load_kind(physical_bus.load_kind),
  .load_addr(physical_bus.load_addr),.load_data(physical_bus.load_data),.load_row_enable(physical_bus.load_rows),.load_error(physical_return.load_error),
  .cmd_valid(physical_bus.cmd_valid),.cmd_ready(physical_return.cmd_ready),.cmd_clusters(physical_bus.cmd_clusters),.cmd_weight(physical_bus.cmd_weight),
  .cmd_mask(physical_bus.cmd_mask),.cmd_activation(physical_bus.cmd_activation),.cmd_output(physical_bus.cmd_output),
  .cmd_accumulate(physical_bus.cmd_accumulate),.cmd_reduce(physical_bus.cmd_reduce),.core_score_select(physical_bus.core_select),
  .out_valid(physical_return.out_valid),.out_ready(physical_bus.out_ready),.out_output(physical_return.out_output),.out_data(physical_return.out_data),
  .activation_reloaded(physical_bus.activation_reloaded),.softmax_request(physical_softmax_request),.softmax_response(physical_softmax_response),
  .merge_sign_data('0),.merge_sign_control('0),.merge_sign_counts(),.merge_table_request('0),.merge_table_word(),
  .token_sizes_request('0),.token_sizes_response(),.merge_request('0),.merge_response(),
  .strip_rst_n(rst_n),.strip_request(ff_strip_request),.strip_response(ff_strip_response),.head_request('0),.head_response()
 );
 function automatic int q(input int head,feature);
  return ((head*3+(feature%32)*5)%17)-8;
 endfunction
 function automatic int v(input int head,key,feature);
  return ((head*13+key*7+feature*3)%23)-11;
 endfunction
 function automatic int source_key(input int head,index);
  if(case_id==4 && TRAIN_STREAMING[head] && index>=32)return TARGET_QUERY-63+index;
  if(case_id==3 && head!=31 && index>=32)return 960+index;
  return index;
 endfunction
 function automatic logic signed[7:0] exponent(input int head);
  if(case_id==4)return $signed(TRAIN_EXPONENTS[head*8+:8]);
  if(case_id==0)return head==19?-8'sd7:-8'sd6;
  if(head==0)return 8'sh80;
  if(head==31)return 8'sd127;
  return 8'(head%7-9);
 endfunction
 function automatic logic[511:0] gold_vector_data(input int kind,head,key);
  logic[511:0] data;int code,index;
  if(case_id==4)begin
   if(kind==0)return trained_q[head];
   if(kind==1)return trained_k[(head/8)*281+key];
   return trained_v[(head/8)*281+key];
  end
  if(case_id==0)begin
   if(head!=19 && head!=20)$fatal(1,"BROKER_FOREIGN_TRAINED_HEAD");
   index=head==19?0:3;
   if(kind==0)return qk[index];
   if(kind==1)return qk[index+1+key];
   return values[(head==19?0:2)+key];
  end
  for(int feature=0;feature<64;feature++)begin
   case(kind)
    0:code=q(head,feature);
    1:code=(feature<32?1:-1)*q(head,feature)*(1+key%3);
    2:code=v(head,key,feature);
    default:$fatal(1,"BROKER_INVALID_TENSOR_KIND");
   endcase
   data[feature*8+:8]=8'(code);
  end
  return data;
 endfunction
 function automatic logic[511:0] vector_data(input int kind,head,key);
  int cache_head,cache_token;
  cache_head=kind==0 ? head:32+(kind-1)*4+head/8;
  cache_token=kind==0 ? TARGET_QUERY:key;
  if(case_id!=4 || kind<0 || kind>2 || head<0 || head>=32 || cache_token<0 || cache_token>=3 ||
     qkv_phase || !qkv_cache_committed || !qkv_acknowledged[cache_head][cache_token])
   $fatal(1,"FRESH_QKV_UNAVAILABLE_CACHE_READ");
  return qkv_cache[cache_head][cache_token];
 endfunction
 function automatic int expected_value(input int head,feature);
  longint total;int n,p;
  if(case_id==4)return $signed(trained_gold[head][feature*32+:32]);
  if(case_id==0)return $signed(golden[head==19?0:1][feature*32+:32]);
  if(case_id==1)return 16384*v(head,0,feature)+49151*v(head,1,feature);
  n=case_id==2?128:(head==31?1024:64);p=65536/n;total=0;
  for(int key=0;key<n;key++)total+=longint'(p)*v(head,source_key(head,key),feature);
  return 32'(total);
 endfunction
 always_comb tensor_req_ready=rst_n && !serving && !tensor_rsp_valid && cycle%5!=0;
 // Hardware commit_control owns the broker/collector row handshake.
 always @(posedge clk)begin
  cycle<=cycle+1;
  if(!rst_n)begin serving<=0;tensor_rsp_valid<=0;end
  else begin
   if(tensor_req_valid && tensor_req_ready)begin
    serving<=1;delay_count<=3+cycle%3;tensor_rsp_kind<=tensor_req_kind;
    tensor_rsp_head<=tensor_req_head;tensor_rsp_key<=tensor_req_key;
    tensor_rsp_query<=tensor_req_query;tensor_rsp_epoch<=tensor_req_epoch;tensor_rsp_tag<=tensor_req_tag;
    tensor_rsp_data<=vector_data(tensor_req_kind,tensor_req_head,tensor_req_key);
    tensor_rsp_value_exponent<=exponent(tensor_req_head);
    tensor_rsp_size<=case_id==4 && tensor_req_kind==1 ? trained_sizes[tensor_req_key] : case_id==1 && tensor_req_kind==1 ? 10'(1+2*int'(tensor_req_key)):10'd1;
    requests++;
    $display("BROKER_TENSOR_REQUEST frame=%0d kind=%0d head=%0d key=%0d query=%0d epoch=%04h tag=%08h data=%0128h size=%0d",frame,
     tensor_req_kind,tensor_req_head,tensor_req_key,tensor_req_query,tensor_req_epoch,tensor_req_tag,
     vector_data(tensor_req_kind,tensor_req_head,tensor_req_key),case_id==4 && tensor_req_kind==1 ? int'(trained_sizes[tensor_req_key]) : case_id==1 && tensor_req_kind==1?1+2*int'(tensor_req_key):1);
   end
   if(serving)begin
    if(delay_count==0)begin serving<=0;tensor_rsp_valid<=1;end else delay_count<=delay_count-1;
   end
   if(tensor_rsp_valid && tensor_rsp_ready)tensor_rsp_valid<=0;
   if(softmax_request.cfg_valid && softmax_response.cfg_ready)begin
    configured_owners[softmax_request.owner]=1;
    $display("BROKER_NORMALIZER_CONFIG frame=%0d owner=%0d length=%0d",frame,softmax_request.owner,softmax_request.cfg_length);
   end
   if(softmax_request.in_valid && softmax_response.in_ready)
    $display("BROKER_NORMALIZER_INPUT frame=%0d owner=%0d score=%0d size=%0d",frame,softmax_request.owner,$signed(softmax_request.score),softmax_request.size);
   if(softmax_request.out_ready && softmax_response.out_valid)
    $display("BROKER_PROBABILITY frame=%0d owner=%0d probability=%0d last=%0d",frame,softmax_request.owner,softmax_response.probability,softmax_response.out_last);
   if(dut.u_req_valid && dut.u_req_ready && dut.u_operation==0 && !first_value_seen)begin
    first_value_seen=1;first_value_configured=configured_owners;
   end
   if(context_valid && check_contexts)begin
    if(held && (context_data!==held_data || {context_head,context_query,context_epoch,context_tag}!==held_metadata))
     $fatal(1,"BROKER_HELD_CONTEXT_CHANGED");
    if(context_ready)begin
     if(!expected_heads[context_head] || received_heads[context_head] || context_query!==expected_query ||
        context_epoch!==expected_epoch || context_tag!==expected_tag || context_value_exponent!==exponent(context_head))
      $fatal(1,"BROKER_CONTEXT_METADATA_MISMATCH head=%0d epoch=%04h tag=%08h",context_head,context_epoch,context_tag);
     for(int feature=0;feature<64;feature++)if($signed(context_data[feature*32+:32])!==expected_value(context_head,feature))
      $fatal(1,"BROKER_CONTEXT_VALUE_MISMATCH frame=%0d head=%0d feature=%0d got=%0d expected=%0d",frame,context_head,feature,$signed(context_data[feature*32+:32]),expected_value(context_head,feature));
     received_heads[context_head]=1;received+=64;
     $display("BROKER_CONTEXT frame=%0d head=%0d query=%0d epoch=%04h tag=%08h exponent=%0d values=%0512h",frame,
      context_head,context_query,context_epoch,context_tag,$signed(context_value_exponent),context_data);
    end
    held=context_valid && !context_ready;
    if(held)begin held_data=context_data;held_metadata={context_head,context_query,context_epoch,context_tag};end
   end else held=0;
  end
 end
 function automatic int expected_weight_word_reads;
  int active;active=0;
  for(int word_index=0;word_index<256;word_index++)if(converted_words[word_index]!=64'b0)active++;
  return active*2048;
 endfunction
 task automatic configure(input int test_case,input bit cluster_mode,input logic[31:0] heads);
  frame++;case_id=test_case;expected_heads=heads;received_heads=0;received=0;configured_owners=0;first_value_seen=0;
  first_value_configured=0;held=0;requests=0;check_contexts=1;auto_accept=0;
  expected_query=test_case==4?16'(TARGET_QUERY):test_case==2?16'd127:test_case==3?16'd1023:16'd1;
  expected_epoch=test_case==0?16'h9ab3:16'h44a1;expected_tag=test_case==0?32'h5317b92d:32'h90100000+32'(test_case);
  @(negedge clk);cfg_heads=heads;cfg_streaming=test_case==3?32'h7fffffff:test_case==0?32'h00080000:32'd0;
  cfg_total_keys=cluster_mode?11'd281:11'd128;cfg_visible_keys=test_case==2?11'd128:11'd2;
  if(test_case==3)begin cfg_total_keys=1024;cfg_visible_keys=1024;end
  cfg_score_shifts=0;if(test_case==0)cfg_score_shifts[20*7+:7]=-7'sd1;
  if(test_case==4)begin cfg_score_shifts=TRAIN_SHIFTS;cfg_streaming=TRAIN_STREAMING;cfg_visible_keys=11'(TARGET_QUERY+1);end
  for(int head=0;head<32;head++)cfg_value_exponents[head*8+:8]=exponent(head);
  cfg_query=expected_query;cfg_epoch=expected_epoch;cfg_tag=expected_tag;cfg_valid=1;
  do @(posedge clk);while(!cfg_ready);
  @(negedge clk);cfg_valid=0;
  // Every outer field is poisoned after acceptance, including later-wave data.
  cfg_heads=0;cfg_streaming='1;cfg_total_keys=0;cfg_visible_keys=0;cfg_score_shifts='1;
  cfg_value_exponents='1;cfg_query='1;cfg_epoch=0;cfg_tag=0;
  $display("BROKER_FRAME_BEGIN frame=%0d case=%0d cluster=%0d heads=%08h",frame,test_case,cluster_mode,heads);
 endtask
 task automatic complete_frame;
  while(!context_valid && !co_done_valid)@(negedge clk);
  if(co_done_valid)$fatal(1,"COMMIT_TRAINED_BROKER_FAILED code=%02h",co_error_code);
  if(!all_contexts_collected)$fatal(1,"COMMIT_TRAINED_EARLY_CONTEXT");
  repeat(46)begin
   @(negedge clk);
   if(context_ready || !context_valid || !c_lease_block || co_frame_valid)
    $fatal(1,"COMMIT_TRAINED_METADATA_BACKPRESSURE");
  end
  metadata_release_gate=1;
  while(!co_frame_valid && !co_done_valid)@(negedge clk);
  if(co_done_valid || done_error || reset_required || co_reset_required ||
     received_heads!==expected_heads || received!=2048 || $countones(first_value_configured)<2)
   $fatal(1,"COMMIT_TRAINED_FRAME_FAILED code=%02h",co_error_code);
  $display("BROKER_FRAME_PASS frame=%0d case=%0d values=%0d requests=%0d first_value_configured=%05h",frame,case_id,received,requests,first_value_configured);
 endtask
 initial begin
  if(!$value$plusargs("PAIRED_ROOT=%s",paired_root) || !$value$plusargs("PAIRED_UNITS=%s",units_file))$fatal(1,"CONNECTED_INPUTS_MISSING");
  void'($value$plusargs("FIXTURE_ROOT=%s",fixture_root));
  if(!$value$plusargs("QK=%s",qk_file) || !$value$plusargs("VALUES=%s",value_file) || !$value$plusargs("GOLD=%s",gold_file))$fatal(1,"BROKER_FIXTURES_MISSING");
  $readmemh(qk_file,qk);$readmemh(value_file,values);$readmemh(gold_file,golden);
  $readmemh(units_file,query_units);
  norm_file=$fopen("computed_normalization_q13.hex","w");bypass_file=$fopen("computed_bypass_q26.hex","w");
  if(norm_file==0 || bypass_file==0)$fatal(1,"CONNECTED_NATIVE_OUTPUT_OPEN");
  wait(ff_fixture_loaded && qkv_fixture_loaded);repeat(2)@(negedge clk);rst_n=1;
  prepare_live_qkv();
  @(negedge clk);h_cfg_valid=1;
  do @(posedge clk);while(!h_cfg_ready);
  @(negedge clk);h_cfg_valid=0;
  for(TARGET_QUERY=1;TARGET_QUERY<=2;TARGET_QUERY++)begin
    fixed_root=$sformatf("%s/query_%0d",paired_root,TARGET_QUERY);
    projection_values=0;projection_context_words=0;projection_weight_words=0;row_controller_commands=0;
    quant_values=0;quant_words=0;residual_writes=0;residual_norms=0;finish_seen=0;
    commit_reported=0;metadata_release_gate=0;projection_cfg_valid=0;projection_done_ready=0;
    $display("CONNECTED_QUERY_BEGIN query=%0d",TARGET_QUERY);
    {quant_output_units,quant_weight_units}=query_units[TARGET_QUERY-1];
    $readmemh(fixed_path("output_words.hex"),quant_expected);
    $readmemh(fixed_path("pre_residual.hex"),pre_residual);
    $readmemh(fixed_path("bypass_q26.hex"),expected_bypass);
    $readmemh(fixed_path("normalization_q13.hex"),expected_normal);
    $readmemh(fixed_path("residual_shifts.hex"),residual_shifts);
  $readmemh(fixed_path("query.hex"),trained_q);
  $readmemh(fixed_path("key.hex"),trained_k);
  $readmemh(fixed_path("value.hex"),trained_v);
  $readmemh(fixed_path("attention_rows.hex"),trained_gold);
  $readmemh(fixed_path("sizes.hex"),trained_sizes);
  $readmemh(fixed_path("context_words.hex"),converted_words);

  $readmemh(fixed_path("output_weights.hex"),output_weights);
  $readmemh(fixed_path("output_accumulators.hex"),output_accumulators);
  configure(4,1,32'hffffffff);complete_frame();
  while(!c_valid && !c_done)@(negedge clk);
  if(c_done || c_unit!==9'(EXPECTED_CONTEXT_EXPONENT) || c_tag!==32'h90100004 || c_query!==11'(TARGET_QUERY) || !c_lease)
   $fatal(1,"HANDOFF_TRAINED_CONTEXT_METADATA");
  for(int group_index=0;group_index<13;group_index++)project_group(group_index);
  while(!finish_seen)@(negedge clk);
  if(!projection_cfg_valid || projection_admitted_valid || !projection_command_idle)$fatal(1,"SHARED_MASKED_OFFER_NOT_FINISHED");
  $display("SHARED_MASKED_OFFER_FINISH_PASS");
  @(negedge clk);c_finish=0;
  while(!co_done_valid)@(negedge clk);
  if(co_done_error || co_reset_required || c_error || c_lease || c_valid || !c_needs_rebuild)
   $fatal(1,"COMMIT_TRAINED_FINISH_FAILED");
  repeat(3)begin @(negedge clk);if(!co_done_valid || cfg_ready || !busy)$fatal(1,"COMMIT_TRAINED_DONE_NOT_HELD");end
  co_done_ready=1;@(negedge clk);co_done_ready=0;
  if(!cfg_ready || busy || co_done_valid)$fatal(1,"COMMIT_TRAINED_REUSE_FAILED");
  $display("COMMIT_QUERY_DONE error=0");
  if(projection_values!=2048 || projection_context_words!=3328 || projection_weight_words!=expected_weight_word_reads())$fatal(1,"SHARED_PROJECTION_COVERAGE");
`ifdef QUANTIZED_PROJECTION
  if(quant_values!=2048 || quant_words!=256 || !quant_idle || quant_fault)$fatal(1,"SHARED_QUANTIZED_COVERAGE");
  $display("SHARED_QUANTIZED_PROJECTION_PASS words=256 codes=2048");
  if(residual_writes!=256 || residual_norms!=256 || residual_write_valid || residual_norm_valid)
    $fatal(1,"FIXED_RESIDUAL_FINAL_DRAIN");
  $display("FIXED_ATTENTION_PROJECTION_RESIDUAL_PASS query=%0d heads=32 projection_codes=2048 normalization_values=2048 bypass_values=2048",TARGET_QUERY);
`endif
  $display("SHARED_ATTENTION_PROJECTION_PASS heads=32 query=%0d context_values=2048 projection_dots=%0d context_word_reads=%0d weight_word_reads=%0d",TARGET_QUERY,projection_values,projection_context_words,projection_weight_words);

    $display("CONNECTED_QUERY_END query=%0d",TARGET_QUERY);
  end
  TARGET_QUERY=2;
  @(negedge clk);projection_cfg_valid=0;
  if(native_residual_valid!=={512{1'b1}} || native_bypass_valid!=={512{1'b1}} ||
     c_lease || co_route || !c_needs_rebuild || !c_actual_metadata_idle || !projection_complete_idle || !quant_idle)
    $fatal(1,"CONNECTED_HANDOFF_NOT_DRAINED");
  $fclose(norm_file);$fclose(bypass_file);
  h_source_done_valid=1;do @(posedge clk);while(!h_source_done_ready);
  @(negedge clk);h_source_done_valid=0;
  while(!h_captured_valid)@(negedge clk);
  if(h_captured_error || h_captured_tag!==32'h39300001 || h_captured_code!=0 ||
     shared_residual_write_beats!=2048 || shared_residual_write_acks!=256 || memory_write_owner!=WriteIdle)
    $fatal(1,"FULL_MEMORY_CAPTURE_INCOMPLETE");
  $display("FULL_MEMORY_CAPTURE_PASS rows=512 write_beats=2048 write_acks=256");
  // Negative control corrupts an acknowledged stored word, never a gold row.
  if(CORRUPT_NATIVE_RESIDUAL)begin
    residual_memory[0][25]=~residual_memory[0][25];residual_fault_injected=1;
    $display("FULL_MEMORY_CORRUPTED word=0 bit=25");
  end
  ff_phase=1;
  $display("CONNECTED_FF_PHASE_BEGIN native_residual_rows=512");
  wait(ff_done);
  if(!CONNECTED_PREFIX_ONLY)wait(final_complete && final_idle);
  else if(!final_idle || final_complete)$fatal(1,"CONNECTED_WRITEBACK_PREFIX_NOT_DRAINED");
  if(!CONNECTED_PREFIX_ONLY)begin
    @(negedge clk);
    if(!h_norm_done || !h_captured_valid || h_captured_error || shared_stats_rows!=512 || shared_replay_rows!=512 ||
       shared_bypass_rows!=512 || shared_residual_read_packets!=768 || shared_residual_read_beats!=6144 ||
       shared_scale_requests!=256 || shared_ff_read_requests!=projection.read_requests ||
       shared_ff_write_requests!=projection.write_requests+projection.activation_requests ||
       memory_read_owner!=ReadIdle || memory_write_owner!=WriteIdle || residual_ack_pending ||
       shared_ff_read_requests==0 || shared_ff_write_requests==0)
      $fatal(1,"FULL_MEMORY_FINAL_INVENTORY");
    h_release_valid=1;do @(posedge clk);while(!h_release_ready);
    @(negedge clk);h_release_valid=0;
    if(h_captured_valid || h_norm_done || !h_cfg_ready)$fatal(1,"FULL_MEMORY_FINAL_RELEASE");
    $display("FULL_MEMORY_COMPLETE_PASS stats=512 replay=512 bypass=512 write_beats=2048 write_acks=256 read_packets=768 read_beats=6144 scale_requests=256 ff_read_requests=%0d ff_write_requests=%0d scalar_contention=%0d",shared_ff_read_requests,shared_ff_write_requests,shared_read_contention);
  end
  if(metadata_rebuilds!=1 || c_needs_rebuild || (!CONNECTED_PREFIX_ONLY && !c_actual_metadata_idle))
    $fatal(1,"CONNECTED_METADATA_NOT_REBUILT count=%0d",metadata_rebuilds);
  $display("CONNECTED_METADATA_REBUILT count=%0d",metadata_rebuilds);
  if(CONNECTED_PREFIX_ONLY)$display("CONNECTED_NATIVE_ATTENTION_FF_PREFIX_PASS queries=2 native_residual_values=4096");
  else $display("CONNECTED_NATIVE_ATTENTION_FF_FULL_PASS queries=2 native_residual_values=4096 raw_down_values=4096");
  if(!CONNECTED_PREFIX_ONLY)
    $display("CONNECTED_NATIVE_ATTENTION_FF_WRITEBACK_FULL_PASS queries=2 raw_down_values=4096 final_values=4096");
  if(qkv_phase || !qkv_cache_committed || qkv_operands!=384)$fatal(1,"FRESH_QKV_FINAL_COVERAGE");
  $display("FRESH_QKV_COMPLETE operands=%0d",qkv_operands);
  $finish;
 end
 initial begin #450000000;$fatal(1,"BROKER_WATCHDOG state=%0d code=%02h pending_tensor=%0d pending_read=%0d",dut.state,error_code,dut.tensor_pending,dut.read_pending);end
`include "verilog/live_qkv_frame/qkv_wiring.svh"
endmodule
