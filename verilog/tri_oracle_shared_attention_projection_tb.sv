`timescale 1ns/1ps
module tri_oracle_shared_attention_projection_tb;
 logic clk=1'bx,rst_n=0,cfg_valid=0,cfg_ready,cancel=0;
 initial begin #1;clk=0;end
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
 string qk_file,value_file,gold_file;

 logic c_cfg_valid,c_cfg_ready,c_row_ready,c_metadata_idle=0;
 logic c_lease_block,c_needs_rebuild,c_lease,c_valid,c_done,c_done_ready,c_error;
 logic [31:0] c_tag;
 logic [10:0] c_query;
 logic signed [8:0] c_unit;
 logic [767:0] c_metadata_read;
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
  logic projection_out_valid,projection_out_ready=0,projection_out_last;
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
    physical_softmax_request=co_route ? '0 : softmax_request;
    softmax_response=co_route ? '0 : physical_softmax_response;
    projection_req_ready=p_ready;
    projection_rsp_valid=p_rsp_valid;projection_rsp_last=p_rsp_last;
    projection_rsp_error=p_rsp_error;projection_rsp_data=p_rsp_data;
    p_valid=projection_req_valid;p_address=projection_req_address;p_length={1'b0,projection_req_length};
    p_rsp_ready=projection_rsp_ready;
    external_req_ready=rst_n && !external_serving && !external_rsp_valid && cycle%5!=0;
    external_rsp_last=external_remaining==1;
    external_rsp_error=projection_fault_case && projection_weight_words==0;
    external_rsp_data={448'b0,output_weights[external_word]};
  end
  tri_oracle_projection_frame_guard frame_guard (
    .frame_valid(co_frame_valid),.cfg_valid(projection_cfg_valid),.cfg_ready(projection_cfg_ready),
    .window_idle(projection_window_idle),.outer_cancel(cancel),.done_valid(projection_done_valid),.done_error(projection_done_error),
    .admitted_valid(projection_admitted_valid),.command_idle(projection_command_idle),
    .projection_idle(projection_complete_idle),.frame_cancel
  );
  tri_oracle_fabric_owner_mux shared_owner (
    .rst_n,.projection_owned(co_route),.attention_request(attention_bus),.projection_request(projection_bus),
    .fabric_request(physical_bus),.fabric_response(physical_return),
    .attention_response(attention_return),.projection_response(projection_return)
  );
  tri_oracle_external_tensor390 projection (
    .clk,.rst_n,.cfg_valid(projection_admitted_valid),.cfg_ready(projection_cfg_ready),
    .cfg_paired(1'b0),.cfg_tag(projection_cfg_tag),.cfg_tokens(5'd1),.cfg_feature_words(10'd256),
    .cfg_dense_rows(17'd2048),.cfg_count(projection_cfg_count),
    .cfg_channels(projection_cfg_channels),.cfg_keep(projection_cfg_keep),
    .cfg_activation_base(64'h10000),.cfg_weight_base(64'h200000),.cfg_up_weight_base(64'b0),.cfg_activation_stride(32'd2048),
    .out_valid(projection_out_valid),.out_ready(projection_out_ready),.out_tag(projection_out_tag),
    .out_token(projection_out_token),.out_last(projection_out_last),.out_count(projection_out_count),
    .out_channels(projection_out_channels),.out_data(projection_out_data),
    .done_valid(projection_done_valid),.done_ready(projection_done_ready),.done_error(projection_done_error),.done_tag(projection_done_tag),
    .req_valid(projection_req_valid),.req_ready(projection_req_ready),.req_address(projection_req_address),.req_length(projection_req_length),
    .rsp_valid(projection_rsp_valid),.rsp_ready(projection_rsp_ready),.rsp_last(projection_rsp_last),.rsp_error(projection_rsp_error),.rsp_data(projection_rsp_data[63:0]),
    .softmax_request('0),.backend_rst_n(projection_bus.rst_n),
    .load_valid(projection_bus.load_valid),.load_error(projection_return.load_error),
    .load_core(projection_bus.load_core),.load_kind(projection_bus.load_kind),.load_addr(projection_bus.load_addr),
    .load_data(projection_bus.load_data),.load_row_enable(projection_bus.load_rows),
    .backend_cmd_valid(projection_bus.cmd_valid),.backend_cmd_ready(projection_return.cmd_ready),
    .backend_clusters(projection_bus.cmd_clusters),.backend_cmd_weight(projection_bus.cmd_weight),.backend_cmd_mask(projection_bus.cmd_mask),
    .backend_cmd_activation(projection_bus.cmd_activation),.backend_cmd_output(projection_bus.cmd_output),
    .backend_cmd_accumulate(projection_bus.cmd_accumulate),.backend_cmd_reduce(projection_bus.cmd_reduce),
    .backend_core_select(projection_bus.core_select),.backend_activation_reloaded(projection_bus.activation_reloaded),
    .backend_out_valid(projection_return.out_valid),.backend_out_ready(projection_bus.out_ready),
    .backend_out_output(projection_return.out_output),.backend_out_data(projection_return.out_data)
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
      if(projection_values!=2048 || !projection_complete_idle || external_serving || external_rsp_valid)
        $fatal(1,"SHARED_EARLY_FINISH");
      finish_seen=1;
    end
    if(co_route && (attention_return.cmd_ready || attention_return.out_valid!=0 || attention_return.load_error))
      $fatal(1,"SHARED_INACTIVE_ATTENTION_HANDSHAKE");
    if(!co_route && (projection_return.cmd_ready || projection_return.out_valid!=0 || projection_return.load_error))
      $fatal(1,"SHARED_INACTIVE_PROJECTION_HANDSHAKE");
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
    projection_out_ready=1;@(negedge clk);projection_out_ready=0;
    while(!projection_done_valid)@(negedge clk);
    if(projection_done_error || projection_done_tag!==32'h80000000+32'(group_index))
      $fatal(1,"SHARED_PROJECTION_DONE_ERROR");
    repeat(3)begin @(negedge clk);if(!projection_done_valid || !c_lease || finish_seen)$fatal(1,"SHARED_COMMAND_NOT_HELD");end
    projection_done_ready=1;@(negedge clk);projection_done_ready=0;
    $display("SHARED_PROJECTION_GROUP_PASS group=%0d values=%0d",group_index,group_count);
  endtask

 tri_oracle_context_handoff collector (
  .clk,.rst_n(co_collector_rst_n),.cfg_valid(c_cfg_valid),.cfg_ready(c_cfg_ready),.cfg_tag(cfg_tag),.cfg_query(cfg_query[10:0]),.cfg_zero_exponent(9'sd0),
  .row_valid(co_row_valid),.row_ready(c_row_ready),.row_error(context_query!=280 || context_epoch!=16'h44a1 || context_tag!=32'h90100004),
  .row_query(context_query[10:0]),.row_head(context_head),.row_data(context_data),.row_value_exponent(context_value_exponent),
  .metadata_idle(c_metadata_idle),.metadata_block(c_lease_block),.metadata_needs_rebuild(c_needs_rebuild),.metadata_rebuilt(1'b0),.lease_active(c_lease),
  .metadata_ce_n(6'b111111),.metadata_we_n(6'b111111),.metadata_address(54'b0),
  .metadata_write_data(768'b0),.metadata_write_mask({768{1'b1}}),.metadata_read_data(c_metadata_read),
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
  .strip_rst_n(rst_n),.strip_request('0),.strip_response(),.head_request('0),.head_response()
 );
 function automatic int q(input int head,feature);
  return ((head*3+(feature%32)*5)%17)-8;
 endfunction
 function automatic int v(input int head,key,feature);
  return ((head*13+key*7+feature*3)%23)-11;
 endfunction
 function automatic int source_key(input int head,index);
  if(case_id==4 && TRAIN_STREAMING[head] && index>=32)return 217+index;
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
 function automatic logic[511:0] vector_data(input int kind,head,key);
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
 task automatic configure(input int test_case,input bit cluster_mode,input logic[31:0] heads);
  frame++;case_id=test_case;expected_heads=heads;received_heads=0;received=0;configured_owners=0;first_value_seen=0;
  first_value_configured=0;held=0;requests=0;check_contexts=1;auto_accept=0;
  expected_query=test_case==4?16'd280:test_case==2?16'd127:test_case==3?16'd1023:16'd1;
  expected_epoch=test_case==0?16'h9ab3:16'h44a1;expected_tag=test_case==0?32'h5317b92d:32'h90100000+32'(test_case);
  @(negedge clk);cfg_heads=heads;cfg_streaming=test_case==3?32'h7fffffff:test_case==0?32'h00080000:32'd0;
  cfg_total_keys=cluster_mode?11'd281:11'd128;cfg_visible_keys=test_case==2?11'd128:11'd2;
  if(test_case==3)begin cfg_total_keys=1024;cfg_visible_keys=1024;end
  cfg_score_shifts=0;if(test_case==0)cfg_score_shifts[20*7+:7]=-7'sd1;
  if(test_case==4)begin cfg_score_shifts=TRAIN_SHIFTS;cfg_streaming=TRAIN_STREAMING;cfg_visible_keys=281;end
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
  c_metadata_idle=1;
  while(!co_frame_valid && !co_done_valid)@(negedge clk);
  if(co_done_valid || done_error || reset_required || co_reset_required ||
     received_heads!==expected_heads || received!=2048 || $countones(first_value_configured)<2)
   $fatal(1,"COMMIT_TRAINED_FRAME_FAILED code=%02h",co_error_code);
  $display("BROKER_FRAME_PASS frame=%0d case=%0d values=%0d requests=%0d first_value_configured=%05h",frame,case_id,received,requests,first_value_configured);
 endtask
 initial begin
  if(!$value$plusargs("QK=%s",qk_file) || !$value$plusargs("VALUES=%s",value_file) || !$value$plusargs("GOLD=%s",gold_file))$fatal(1,"BROKER_FIXTURES_MISSING");
  $readmemh(qk_file,qk);$readmemh(value_file,values);$readmemh(gold_file,golden);
  $readmemh(".cache/late_clipping_20261121/frame_integration/complete_head_handoff_v1/query.hex",trained_q);
  $readmemh(".cache/late_clipping_20261121/frame_integration/complete_head_handoff_v1/key.hex",trained_k);
  $readmemh(".cache/late_clipping_20261121/frame_integration/complete_head_handoff_v1/value.hex",trained_v);
  $readmemh(".cache/late_clipping_20261121/frame_integration/complete_head_handoff_v1/contexts.hex",trained_gold);
  $readmemh(".cache/late_clipping_20261121/frame_integration/complete_head_handoff_v1/sizes.hex",trained_sizes);
  $readmemh(".cache/late_clipping_20261121/frame_integration/complete_head_handoff_v1/projection_words.hex",converted_words);

  $readmemh(".cache/late_clipping_20261121/frame_integration/shared_attention_projection_v1/output_weight_words.hex",output_weights);
  $readmemh(".cache/late_clipping_20261121/frame_integration/shared_attention_projection_v1/output_accumulators.hex",output_accumulators);
  repeat(2)@(negedge clk);rst_n=1;
  @(negedge clk);cfg_valid=1;cancel=1;#1;
  if(cfg_ready || busy)$fatal(1,"BROKER_CANCELLED_CONFIGURATION_ACCEPTED");
  @(negedge clk);cfg_valid=0;cancel=0;
  if(busy)$fatal(1,"BROKER_CANCELLED_CONFIGURATION_STARTED");
  $display("BROKER_COINCIDENT_CONFIG_CANCEL_PASS");
  configure(4,1,32'hffffffff);complete_frame();
  while(!c_valid && !c_done)@(negedge clk);
  if(c_done || c_unit!==-9'sd7 || c_tag!==32'h90100004 || c_query!==11'd280 || !c_lease)
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
  if(projection_values!=2048 || projection_context_words!=3328 || projection_weight_words!=524288)$fatal(1,"SHARED_PROJECTION_COVERAGE");
  $display("SHARED_ATTENTION_PROJECTION_PASS heads=32 query=280 context_values=2048 projection_dots=%0d context_word_reads=%0d weight_word_reads=%0d",projection_values,projection_context_words,projection_weight_words);$finish;
 end
 initial begin #150000000;$fatal(1,"BROKER_WATCHDOG state=%0d code=%02h pending_tensor=%0d pending_read=%0d",dut.state,error_code,dut.tensor_pending,dut.read_pending);end
endmodule
