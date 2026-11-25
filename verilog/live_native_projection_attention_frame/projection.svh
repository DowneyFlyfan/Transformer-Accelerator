 // One physical tensor frontend is shared by projection and head prediction.
 assign tensor_cfg_ready=!qkv_phase && raw_cfg_ready;
 assign qt_cfg_ready=qkv_phase && raw_cfg_ready;
 assign tensor_out_valid=!qkv_phase && raw_out_valid;
 assign tensor_out_tag=raw_out_tag;
 assign tensor_out_token=raw_out_token;
 assign tensor_out_last=raw_out_last;
 assign tensor_out_count=raw_out_count;
 assign tensor_results=raw_out_data;
 assign tensor_done_valid=!qkv_phase && raw_done_valid;
 assign tensor_done_error=raw_done_error;
 assign tensor_done_tag=raw_done_tag;
 assign req_valid=!qkv_phase && raw_req_valid;
 assign req_address=raw_req_address;
 assign req_length=raw_req_length;
 assign rsp_ready=!qkv_phase && raw_rsp_ready;
 assign raw_req_ready=qkv_phase ? qkv_read_req_ready:req_ready;
 assign raw_rsp_valid=qkv_phase ? qkv_read_rsp_valid:rsp_valid;
 assign raw_rsp_last=qkv_phase ? qkv_read_rsp_last:rsp_last;
 assign raw_rsp_error=qkv_phase ? 1'b0:rsp_error;
 assign raw_rsp_data=qkv_phase ? qkv_read_rsp_data:rsp_data;
 assign qkv_cfg_tokens=5'(qkv_batch_tokens);
 assign qkv_cfg_slot=10'(qkv_first);
 assign qkv_cfg_activation_base=QkvActivationBase+64'(qkv_first*2048);

 initial begin
  if(!$value$plusargs("QKV_ROOT=%s",qkv_root))$fatal(1,"COMPLETE_PROJECTION_FIXTURES_MISSING");
  $readmemh({qkv_root,"/weights.hex"},qkv_weights);
  $readmemh({qkv_root,"/cos.hex"},qkv_cosines);
  $readmemh({qkv_root,"/sin.hex"},qkv_sines);
  $readmemh({qkv_root,"/expected.hex"},qkv_expected_vectors);
  $readmemh({qkv_root,"/dots.hex"},qkv_expected_dots);
  qkv_fixture_loaded=1;
 end
 always_comb begin
  qkv_angle_valid=qkv_phase && qkv_started && qkv_angle_index<qkv_batch_tokens;
  qkv_angle_last=qkv_angle_index==qkv_batch_tokens-1;
  qkv_angle_cos=qkv_angle_index<qkv_batch_tokens ? qkv_cosines[qkv_first+qkv_angle_index]:512'd0;
  qkv_angle_sin=qkv_angle_index<qkv_batch_tokens ? qkv_sines[qkv_first+qkv_angle_index]:512'd0;
  qkv_read_req_ready=rst_n && qkv_phase && !qkv_read_busy && cycles%5!=0;
  qkv_read_rsp_valid=rst_n && qkv_phase && qkv_read_busy && qkv_read_delay==0;
  qkv_read_rsp_last=qkv_read_remaining==1;
  qkv_read_rsp_data=0;
  if(qkv_read_busy)qkv_read_rsp_data=qkv_read_weights ? qkv_weights[qkv_read_word]:native_normalized_word(qkv_read_word);
  qkv_write_ready=rst_n && qkv_phase && !qkv_write_pending && cycles%4!=0;
  qkv_write_rsp_valid=rst_n && qkv_phase && qkv_write_pending && qkv_write_delay==0;
 end
 tri_oracle_qkv429 fresh_projection (
  .clk,.rst_n,.cfg_valid(qkv_cfg_valid),.cfg_ready(qkv_cfg_ready),.cfg_tokens(qkv_cfg_tokens),
  .cfg_start_head(6'd0),.cfg_heads(6'd40),.cfg_tag(qkv_tag),
  .cfg_activation_base(qkv_cfg_activation_base),.cfg_weight_base(QkvWeightBase),
  .cfg_shifts(qkv_shifts[0]),.cfg_shift_biases(qkv_biases[0]),
  .angle_valid(qkv_angle_valid),.angle_ready(qkv_angle_ready),.angle_last(qkv_angle_last),
  .angle_cos(qkv_angle_cos),.angle_sin(qkv_angle_sin),
  .out_valid(qkv_out_valid),.out_ready(qkv_out_ready),.out_last(qkv_out_last),
  .out_tag(qkv_out_tag),.out_head(qkv_out_head),.out_token(qkv_out_token),.out_data(qkv_out_data),
  .done_valid(qkv_done_valid),.done_ready(qkv_done_ready),.done_error(qkv_done_error),.done_tag(qkv_done_tag),
  .tensor_cfg_valid(qt_cfg_valid),.tensor_cfg_ready(qt_cfg_ready),.tensor_cfg_tag(qt_cfg_tag),
  .tensor_cfg_tokens(qt_cfg_tokens),.tensor_cfg_count(qt_cfg_count),
  .tensor_cfg_channels(qt_cfg_channels),.tensor_cfg_keep(qt_cfg_keep),
  .tensor_cfg_activation_base(qt_cfg_activation_base),.tensor_cfg_weight_base(qt_cfg_weight_base),
  .tensor_out_valid(qkv_phase && raw_out_valid),.tensor_out_ready(qt_out_ready),
  .tensor_out_last(raw_out_last),.tensor_out_tag(raw_out_tag),.tensor_out_token(raw_out_token),
  .tensor_out_count(raw_out_count),.tensor_out_channels(raw_out_channels),.tensor_out_data(raw_out_data[4095:0]),
  .tensor_done_valid(qkv_phase && raw_done_valid),.tensor_done_ready(qt_done_ready),
  .tensor_done_error(raw_done_error),.tensor_done_tag(raw_done_tag)
 );
 tri_oracle_qkv_store430 fresh_projection_store (
  .clk,.rst_n,.cfg_valid(qkv_cfg_valid),.cfg_ready(qkv_store_cfg_ready),.cfg_tag(qkv_tag),
  .cfg_tokens(qkv_cfg_tokens),.cfg_first_head(6'd0),.cfg_heads(6'd40),.cfg_slot(qkv_cfg_slot),.cfg_base(QkvCacheBase),
  .source_valid(qkv_out_valid),.source_ready(qkv_out_ready),.source_last(qkv_out_last),
  .source_tag(qkv_out_tag),.source_head(qkv_out_head),.source_token(qkv_out_token),.source_data(qkv_out_data),
  .source_done_valid(qkv_done_valid),.source_done_ready(qkv_done_ready),
  .source_done_error(qkv_done_error),.source_done_tag(qkv_done_tag),
  .write_valid(qkv_write_valid),.write_ready(qkv_write_ready),.write_address(qkv_write_address),.write_data(qkv_write_data),
  .write_rsp_valid(qkv_write_rsp_valid),.write_rsp_ready(qkv_write_rsp_ready),.write_rsp_error(1'b0),
  .done_valid(qkv_store_done_valid),.done_ready(qkv_store_done_ready),
  .done_error(qkv_store_done_error),.done_tag(qkv_store_done_tag)
 );
 always @(posedge clk)begin : complete_projection_observation
  int head,token,channel,index;
  logic[63:0]offset;
  if(!rst_n)begin
   qkv_read_busy<=0;qkv_read_delay<=0;qkv_write_pending<=0;qkv_write_delay<=0;
   qkv_angle_index<=0;qkv_write_held<=0;
   for(int h=0;h<40;h++)for(int t=0;t<281;t++)begin qkv_written[h][t]<=0;qkv_acknowledged[h][t]<=0;end
  end else begin
   if(qkv_angle_valid && qkv_angle_ready)begin
    $display("COMPLETE_QKV_ANGLE batch=%0d original=%0d local=%0d last=%0b cos=%0128h sin=%0128h",qkv_batch,qkv_first+qkv_angle_index,qkv_angle_index,qkv_angle_last,qkv_angle_cos,qkv_angle_sin);
    qkv_angle_index<=qkv_angle_index+1;
   end
   if(qkv_phase && qt_cfg_valid && qt_cfg_ready)begin
    if(qt_cfg_tokens!==qkv_cfg_tokens || qt_cfg_count!==8'd128 || qt_cfg_tag!==qkv_tag ||
       qt_cfg_activation_base!==qkv_cfg_activation_base || qt_cfg_weight_base!==QkvWeightBase)
     $fatal(1,"COMPLETE_QKV_BAD_RAW_CONFIGURATION");
    qkv_configs++;
    $display("COMPLETE_QKV_CONFIG batch=%0d tag=%08h tokens=%0d first_head=%0d channels=%0640h",qkv_batch,qt_cfg_tag,qt_cfg_tokens,int'(qt_cfg_channels[15:0])/64,qt_cfg_channels);
   end
   if(qkv_phase && raw_out_valid && qt_out_ready)begin
    if(raw_out_tag!==qkv_tag || raw_out_count!==8'd128 || int'(raw_out_token)>=qkv_batch_tokens || raw_out_last!==(int'(raw_out_token)==qkv_batch_tokens-1))
     $fatal(1,"COMPLETE_QKV_BAD_RAW_PACKET");
    for(int lane=0;lane<128;lane++)begin
     channel=int'(raw_out_channels[lane*16+:16]);head=channel/64;token=qkv_first+int'(raw_out_token);
     index=(head*281+token)*64+channel%64;
     if(head>=40 || raw_out_data[lane*32+:32]!==qkv_expected_dots[index])
      $fatal(1,"COMPLETE_QKV_RAW_DOT_VALUE head=%0d token=%0d feature=%0d",head,token,channel%64);
    end
    qkv_packets++;
    $display("COMPLETE_QKV_RAW batch=%0d tag=%08h token=%0d local=%0d channels=%0640h data=%01024h",qkv_batch,raw_out_tag,qkv_first+int'(raw_out_token),raw_out_token,raw_out_channels,raw_out_data[4095:0]);
   end
   if(qkv_phase && raw_done_valid && qt_done_ready)begin
    if(raw_done_tag!==qkv_tag || raw_done_error)$fatal(1,"COMPLETE_QKV_RAW_TERMINAL_ERROR");
    qkv_tensor_completions++;
    $display("COMPLETE_QKV_TENSOR_DONE batch=%0d tag=%08h",qkv_batch,raw_done_tag);
   end
   if(qkv_phase && raw_req_valid && raw_req_ready)begin
    if(qkv_read_busy || raw_req_length==0 || raw_req_length>16 || raw_req_address[2:0]!=0)
     $fatal(1,"COMPLETE_QKV_BAD_MEMORY_REQUEST");
    if(raw_req_address>=qkv_cfg_activation_base && raw_req_address<=qkv_cfg_activation_base+64'(qkv_batch_tokens*2048)-64'(raw_req_length)*8)begin
     qkv_read_weights<=0;qkv_read_word<=int'((raw_req_address-QkvActivationBase)>>3);
    end else if(raw_req_address>=QkvWeightBase && raw_req_address<=QkvWeightBase+5242880-64'(raw_req_length)*8)begin
     qkv_read_weights<=1;qkv_read_word<=int'((raw_req_address-QkvWeightBase)>>3);
    end else $fatal(1,"COMPLETE_QKV_MEMORY_RANGE address=%016h",raw_req_address);
    qkv_read_busy<=1;qkv_read_remaining<=int'(raw_req_length);qkv_read_delay<=2+cycles%3;qkv_memory_requests++;
   end
   if(qkv_read_delay>0)qkv_read_delay<=qkv_read_delay-1;
   if(qkv_phase && raw_rsp_valid && raw_rsp_ready)begin
    if(!qkv_read_busy || raw_rsp_error)$fatal(1,"COMPLETE_QKV_MEMORY_RESPONSE_DEBT");
    qkv_memory_beats++;
    if(qkv_read_remaining==1)qkv_read_busy<=0;
    else begin qkv_read_word<=qkv_read_word+1;qkv_read_remaining<=qkv_read_remaining-1;qkv_read_delay<=cycles%3;end
   end
   if(qkv_write_valid && !qkv_write_ready)begin
    if(qkv_write_held && {qkv_held_address,qkv_held_data}!=={qkv_write_address,qkv_write_data})$fatal(1,"COMPLETE_QKV_UNSTABLE_WRITE");
    qkv_write_held<=1;qkv_held_address<=qkv_write_address;qkv_held_data<=qkv_write_data;
   end
   if(qkv_write_valid && qkv_write_ready)begin
    offset=qkv_write_address-QkvCacheBase;head=int'(offset>>16);token=int'((offset&64'hffff)>>6);
    if(qkv_write_pending || qkv_cache_committed || qkv_write_address<QkvCacheBase || head>=40 || token<qkv_first || token>=qkv_first+qkv_batch_tokens || offset[5:0]!=0)
     $fatal(1,"COMPLETE_QKV_BAD_CACHE_WRITE");
    if(qkv_written[head][token] || qkv_write_data!==qkv_expected_vectors[head*281+token])
     $fatal(1,"COMPLETE_QKV_PROJECTED_VECTOR_VALUE head=%0d token=%0d",head,token);
    qkv_cache[head][token]<=qkv_write_data;qkv_written[head][token]<=1;
    qkv_pending_head<=head;qkv_pending_token<=token;qkv_pending_address<=qkv_write_address;
    qkv_write_pending<=1;qkv_write_delay<=3+cycles%3;qkv_write_held<=0;qkv_vector_writes++;
    $display("COMPLETE_QKV_WRITE batch=%0d head=%0d token=%0d address=%016h data=%0128h",qkv_batch,head,token,qkv_write_address,qkv_write_data);
   end
   if(qkv_write_delay>0)qkv_write_delay<=qkv_write_delay-1;
   if(qkv_write_rsp_valid && qkv_write_rsp_ready)begin
    if(!qkv_write_pending || !qkv_written[qkv_pending_head][qkv_pending_token] || qkv_acknowledged[qkv_pending_head][qkv_pending_token])$fatal(1,"COMPLETE_QKV_CACHE_ACK_DEBT");
    qkv_acknowledged[qkv_pending_head][qkv_pending_token]<=1;qkv_write_pending<=0;qkv_vector_acks++;
    $display("COMPLETE_QKV_ACK batch=%0d head=%0d token=%0d address=%016h",qkv_batch,qkv_pending_head,qkv_pending_token,qkv_pending_address);
   end
  end
 end
 task automatic prepare_complete_native_projection;
  int configs_before,packets_before,vectors_before,acks_before,completions_before;
  $display("COMPLETE_PROJECTION_BEGIN tokens=281 heads=40 tick=%0t",$time);
  prepare_native_input_normalization();
  if(!qkv_fixture_loaded || reading || context_phase)$fatal(1,"COMPLETE_QKV_BAD_BEGIN");
  for(qkv_batch=0;qkv_batch<18;qkv_batch++)begin
   qkv_first=qkv_batch*16;qkv_batch_tokens=281-qkv_first;if(qkv_batch_tokens>16)qkv_batch_tokens=16;
   qkv_tag=QkvTagBase+32'(qkv_batch);qkv_biases[0]='0;
   for(int local_token=0;local_token<qkv_batch_tokens;local_token++)qkv_biases[0][local_token*6+:6]=norm_token_biases[qkv_first+local_token];
   configs_before=qkv_configs;packets_before=qkv_packets;vectors_before=qkv_vector_writes;acks_before=qkv_vector_acks;completions_before=qkv_tensor_completions;
   while(!qkv_cfg_ready || !qkv_store_cfg_ready)@(negedge clk);
   @(negedge clk);qkv_angle_index=0;qkv_started=0;qkv_cfg_valid=1;
   $display("COMPLETE_QKV_BATCH_BEGIN batch=%0d first=%0d tokens=%0d slot=%0d activation_base=%016h tag=%08h",qkv_batch,qkv_first,qkv_batch_tokens,qkv_cfg_slot,qkv_cfg_activation_base,qkv_tag);
   do @(posedge clk);while(!(qkv_cfg_ready && qkv_store_cfg_ready));
   @(negedge clk);qkv_cfg_valid=0;qkv_started=1;
   while(!qkv_store_done_valid)@(negedge clk);
   if(qkv_store_done_error || qkv_store_done_tag!==qkv_tag || qkv_angle_index!=qkv_batch_tokens ||
      qkv_configs-configs_before!=20 || qkv_packets-packets_before!=20*qkv_batch_tokens ||
      qkv_tensor_completions-completions_before!=20 || qkv_vector_writes-vectors_before!=40*qkv_batch_tokens ||
      qkv_vector_acks-acks_before!=40*qkv_batch_tokens || qkv_write_pending || qkv_read_busy || !raw_cfg_ready || raw_out_valid || raw_done_valid || raw_req_valid)
    $fatal(1,"COMPLETE_QKV_EARLY_BATCH_COMMIT batch=%0d",qkv_batch);
   for(int h=0;h<40;h++)for(int t=qkv_first;t<qkv_first+qkv_batch_tokens;t++)
    if(!qkv_written[h][t] || !qkv_acknowledged[h][t])$fatal(1,"COMPLETE_QKV_UNWRITTEN_BATCH_SLOT");
   $display("COMPLETE_QKV_BATCH_DONE batch=%0d first=%0d tokens=%0d slot=%0d activation_base=%016h tag=%08h configs=%0d packets=%0d vectors=%0d acks=%0d",qkv_batch,qkv_first,qkv_batch_tokens,qkv_cfg_slot,qkv_cfg_activation_base,qkv_tag,qkv_configs-configs_before,qkv_packets-packets_before,qkv_vector_writes-vectors_before,qkv_vector_acks-acks_before);
   qkv_store_done_ready=1;@(negedge clk);qkv_store_done_ready=0;qkv_started=0;
   if(qkv_store_done_valid || !qkv_cfg_ready || !qkv_store_cfg_ready)$fatal(1,"COMPLETE_QKV_TERMINAL_NOT_DRAINED");
  end
  if(qkv_configs!=360 || qkv_packets!=5620 || qkv_vector_writes!=11240 || qkv_vector_acks!=11240 || norm_reads!=1438720)
   $fatal(1,"COMPLETE_QKV_FULL_COVERAGE");
  qkv_cache_committed=1;
  // External memory views are populated only from actual acknowledged native writes.
  for(int h=0;h<32;h++)for(int t=96;t<281;t++)for(int l=0;l<64;l++)queries[(h*185+t-96)*64+l]=qkv_cache[h][t][l*8+:8];
  for(int h=0;h<4;h++)for(int t=0;t<281;t++)for(int l=0;l<64;l++)keys[(h*281+t)*64+l]=qkv_cache[32+h][t][l*8+:8];
  $display("COMPLETE_PROJECTION_PASS tokens=281 dots=719360 vectors=11240 acks=11240 normalization_values=575488 tick=%0t",$time);
  @(negedge clk);qkv_phase=0;projection_phase=0;
 endtask
