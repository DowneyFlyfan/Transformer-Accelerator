`timescale 1ns/1ps
module tri_oracle_complete_head_broker_tb;
 logic clk=0,rst_n=0,cfg_valid=0,cfg_ready,cancel=0;
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
 logic context_valid,context_ready=0;
 logic [4:0] context_head;
 logic [15:0] context_query,context_epoch;
 logic [31:0] context_tag;
 logic signed [7:0] context_value_exponent;
 logic [2047:0] context_data;
 logic all_contexts_collected,done_valid,done_ready=0,done_error,reset_required,busy;
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
 always #5 clk=~clk;
 always_comb fabric_load_error=raw_fabric_load_error || inject_load_error;
 tri_oracle_complete_head_broker dut(.*);
 tri_oracle_compute_fabric #(
  .AGGREGATOR_SIGN_BANK(1),.AGGREGATOR_MERGE_TABLE(1),.LOCAL_TOKEN_SIZES(1),
  .LOCAL_TOKEN_MERGE(1),.CORE_STRIP_PREDICTOR(1),.CORE_HEAD_PREDICTOR(1)
 ) fabric (
  .clk,.rst_n,.load_valid(fabric_load_valid),.load_core(fabric_load_core),.load_kind(fabric_load_kind),
  .load_addr(fabric_load_addr),.load_data(fabric_load_data),.load_row_enable(fabric_load_rows),.load_error(raw_fabric_load_error),
  .cmd_valid(fabric_cmd_valid),.cmd_ready(fabric_cmd_ready),.cmd_clusters(fabric_cmd_clusters),.cmd_weight(fabric_cmd_weight),
  .cmd_mask(fabric_cmd_mask),.cmd_activation(fabric_cmd_activation),.cmd_output(fabric_cmd_output),
  .cmd_accumulate(fabric_cmd_accumulate),.cmd_reduce(fabric_cmd_reduce),.core_score_select(fabric_core_select),
  .out_valid(fabric_out_valid),.out_ready(fabric_out_ready),.out_output(fabric_out_slot),.out_data(fabric_out_data),
  .activation_reloaded(fabric_activation_reloaded),.softmax_request,.softmax_response,
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
  if(case_id==3 && head!=31 && index>=32)return 960+index;
  return index;
 endfunction
 function automatic logic signed[7:0] exponent(input int head);
  if(case_id==0)return head==19?-8'sd7:-8'sd6;
  if(head==0)return 8'sh80;
  if(head==31)return 8'sd127;
  return 8'(head%7-9);
 endfunction
 function automatic logic[511:0] vector_data(input int kind,head,key);
  logic[511:0] data;int code,index;
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
  if(case_id==0)return $signed(golden[head==19?0:1][feature*32+:32]);
  if(case_id==1)return 16384*v(head,0,feature)+49151*v(head,1,feature);
  n=case_id==2?128:(head==31?1024:64);p=65536/n;total=0;
  for(int key=0;key<n;key++)total+=longint'(p)*v(head,source_key(head,key),feature);
  return 32'(total);
 endfunction
 always_comb tensor_req_ready=rst_n && !serving && !tensor_rsp_valid && cycle%5!=0;
 always @(negedge clk)if(auto_accept)context_ready=cycle%7!=0;
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
    tensor_rsp_size<=case_id==1 && tensor_req_kind==1 ? 10'(1+2*int'(tensor_req_key)):10'd1;
    requests++;
    $display("BROKER_TENSOR_REQUEST frame=%0d kind=%0d head=%0d key=%0d query=%0d epoch=%04h tag=%08h data=%0128h size=%0d",frame,
     tensor_req_kind,tensor_req_head,tensor_req_key,tensor_req_query,tensor_req_epoch,tensor_req_tag,
     vector_data(tensor_req_kind,tensor_req_head,tensor_req_key),case_id==1 && tensor_req_kind==1?1+2*int'(tensor_req_key):1);
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
  first_value_configured=0;held=0;requests=0;check_contexts=1;auto_accept=0;context_ready=0;
  expected_query=test_case==2?16'd127:test_case==3?16'd1023:16'd1;
  expected_epoch=test_case==0?16'h9ab3:16'h44a1;expected_tag=test_case==0?32'h5317b92d:32'h90100000+32'(test_case);
  @(negedge clk);cfg_heads=heads;cfg_streaming=test_case==3?32'h7fffffff:test_case==0?32'h00080000:32'd0;
  cfg_total_keys=cluster_mode?11'd281:11'd128;cfg_visible_keys=test_case==2?11'd128:11'd2;
  if(test_case==3)begin cfg_total_keys=1024;cfg_visible_keys=1024;end
  cfg_score_shifts=0;if(test_case==0)cfg_score_shifts[20*7+:7]=-7'sd1;
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
  while(!context_valid && !done_valid)@(negedge clk);
  if(done_valid)$fatal(1,"BROKER_UNEXPECTED_FAILED_COMPLETION frame=%0d code=%02h",frame,error_code);
  if(!all_contexts_collected)$fatal(1,"BROKER_EARLY_CONTEXT_EMISSION");
  repeat(29)begin @(negedge clk);if(!context_valid || done_valid)$fatal(1,"BROKER_CONTEXT_NOT_HELD");end
  auto_accept=1;
  while(!done_valid)@(negedge clk);
  auto_accept=0;context_ready=0;
  if(done_error || reset_required || received_heads!==expected_heads || received!=64*$countones(expected_heads))
   $fatal(1,"BROKER_FRAME_FAILED frame=%0d code=%02h received=%08h expected=%08h values=%0d",frame,error_code,received_heads,expected_heads,received);
  if($countones(first_value_configured)<2)$fatal(1,"BROKER_SERIAL_HEAD_POLICY_REJECTED frame=%0d configured=%05h",frame,first_value_configured);
  repeat(3)begin @(negedge clk);if(!done_valid || cfg_ready || !busy)$fatal(1,"BROKER_DONE_NOT_HELD");end
  done_ready=1;@(negedge clk);done_ready=0;
  #1;if(!cfg_ready || busy)$fatal(1,"BROKER_POSITIVE_REUSE_NOT_READY");
  $display("BROKER_FRAME_PASS frame=%0d case=%0d values=%0d requests=%0d first_value_configured=%05h",frame,case_id,received,requests,first_value_configured);
 endtask
 initial begin
  if(!$value$plusargs("QK=%s",qk_file) || !$value$plusargs("VALUES=%s",value_file) || !$value$plusargs("GOLD=%s",gold_file))$fatal(1,"BROKER_FIXTURES_MISSING");
  $readmemh(qk_file,qk);$readmemh(value_file,values);$readmemh(gold_file,golden);
  repeat(2)@(negedge clk);rst_n=1;
  @(negedge clk);cfg_valid=1;cancel=1;#1;
  if(cfg_ready || busy)$fatal(1,"BROKER_CANCELLED_CONFIGURATION_ACCEPTED");
  @(negedge clk);cfg_valid=0;cancel=0;
  if(busy)$fatal(1,"BROKER_CANCELLED_CONFIGURATION_STARTED");
  $display("BROKER_COINCIDENT_CONFIG_CANCEL_PASS");
  configure(0,1,32'h00180000);complete_frame();
  if($test$plusargs("SMOKE"))begin $display("BROKER_SMOKE_PASS");$finish;end
  configure(0,1,32'h00180000);complete_frame();
  configure(1,0,32'hffffffff);complete_frame();
  configure(1,1,32'hffffffff);complete_frame();
  configure(2,0,32'hffffffff);complete_frame();
  configure(3,1,32'hffffffff);complete_frame();
  configure(0,1,32'h00180000);
  while(!fabric_load_valid)@(negedge clk);
  inject_load_error=1;repeat(6)@(negedge clk);inject_load_error=0;
  while(!done_valid)@(negedge clk);
  if(!done_error || !reset_required || cfg_ready || !busy || error_code!==8'h11 ||
      dut.tensor_pending || dut.read_pending || dut.sb_busy || dut.u_busy!=0 || context_valid)
   $fatal(1,"BROKER_EARLY_SCORE_ERROR_NOT_PROPAGATED code=%02h",error_code);
  $display("BROKER_EARLY_SCORE_ERROR_DRAIN_PASS");
  rst_n=0;repeat(2)@(negedge clk);rst_n=1;
  // A partial local normalizer is cancelled only by coupled reset. Accepted
  // transport traffic drains first; the failed broker cannot admit new work.
  configure(2,0,32'h00180000);
  while(dut.state!=dut.NormSend || dut.norm_cursor<3)@(negedge clk);
  cancel=1;@(negedge clk);cancel=0;
  while(!done_valid)@(negedge clk);
  if(!done_error || !reset_required || cfg_ready || !busy || dut.tensor_pending || dut.read_pending || dut.sb_busy || dut.u_busy!=0)
   $fatal(1,"BROKER_CANCEL_NOT_DRAINED_OR_NOT_RESET_FENCED");
  done_ready=1;repeat(5)@(negedge clk);done_ready=0;
  if(cfg_ready || !reset_required)$fatal(1,"BROKER_FAILED_BATCH_REUSED_WITHOUT_RESET");
  $display("BROKER_CANCEL_PARTIAL_NORMALIZER_RESET_FENCE_PASS");
  rst_n=0;repeat(2)@(negedge clk);rst_n=1;
  configure(0,1,32'h00180000);complete_frame();
  $display("BROKER_FULL_BATCH_PASS frames=7 head_context_values=8576");$finish;
 end
 initial begin #50000000;$fatal(1,"BROKER_WATCHDOG state=%0d code=%02h pending_tensor=%0d pending_read=%0d",dut.state,error_code,dut.tensor_pending,dut.read_pending);end
endmodule
