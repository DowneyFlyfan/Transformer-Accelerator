 // Data sources are supplied normalized codes and trained weights only.
 // Expected dot/vector files are read solely by checks below.
 initial begin
  if(!$value$plusargs("QKV_ROOT=%s",qkv_root))$fatal(1,"FRESH_QKV_INPUTS_MISSING");
  $readmemh({qkv_root,"/activation.hex"},qkv_activation);
  $readmemh({qkv_root,"/weights.hex"},qkv_weights);
  $readmemh({qkv_root,"/cos.hex"},qkv_cosines);
  $readmemh({qkv_root,"/sin.hex"},qkv_sines);
  $readmemh({qkv_root,"/shifts.hex"},qkv_shifts);
  $readmemh({qkv_root,"/shift_biases.hex"},qkv_biases);
  $readmemh({qkv_root,"/expected.hex"},qkv_expected_vectors);
  $readmemh({qkv_root,"/dots.hex"},qkv_expected_dots);
  qkv_fixture_loaded=1;
 end

 always_comb begin
  shared_raw_cfg_valid=qkv_phase ? qt_cfg_valid:projection_admitted_valid;
  shared_raw_cfg_tag=qkv_phase ? qt_cfg_tag:projection_cfg_tag;
  shared_raw_cfg_tokens=qkv_phase ? qt_cfg_tokens:5'd1;
  shared_raw_cfg_dense_rows=qkv_phase ? 17'd2560:17'd2048;
  shared_raw_cfg_count=qkv_phase ? qt_cfg_count:projection_cfg_count;
  shared_raw_cfg_channels=qkv_phase ? qt_cfg_channels:projection_cfg_channels;
  shared_raw_cfg_keep=qkv_phase ? qt_cfg_keep:projection_cfg_keep;
  shared_raw_activation_base=qkv_phase ? qt_cfg_activation_base:64'h10000;
  shared_raw_weight_base=qkv_phase ? qt_cfg_weight_base:64'h200000;
  qt_cfg_ready=qkv_phase && shared_raw_cfg_ready;
  projection_cfg_ready=!qkv_phase && shared_raw_cfg_ready;
  projection_out_valid=!qkv_phase && shared_raw_out_valid;
  projection_out_tag=shared_raw_out_tag;projection_out_token=shared_raw_out_token;
  projection_out_last=shared_raw_out_last;projection_out_count=shared_raw_out_count;
  projection_out_channels=shared_raw_out_channels;projection_out_data=shared_raw_out_data;
  projection_done_valid=!qkv_phase && shared_raw_done_valid;
  projection_done_error=shared_raw_done_error;projection_done_tag=shared_raw_done_tag;
  shared_raw_out_ready=qkv_phase ? qt_out_ready:projection_out_ready;
  shared_raw_done_ready=qkv_phase ? qt_done_ready:projection_done_ready;
  qkv_angle_valid=qkv_phase && qkv_started && qkv_angle_index<3;
  qkv_angle_last=qkv_angle_index==2;
  qkv_angle_cos=qkv_angle_index<3 ? qkv_cosines[qkv_angle_index]:512'd0;
  qkv_angle_sin=qkv_angle_index<3 ? qkv_sines[qkv_angle_index]:512'd0;
  qkv_read_req_ready=rst_n && qkv_phase && !qkv_read_busy && cycle%5!=0;
  qkv_read_rsp_valid=rst_n && qkv_phase && qkv_read_busy && qkv_read_delay==0;
  qkv_read_rsp_last=qkv_read_remaining==1;
  qkv_read_rsp_data=0;
  if(qkv_read_busy)qkv_read_rsp_data=qkv_read_weights ? qkv_weights[qkv_read_word]:qkv_activation[qkv_read_word];
  qkv_write_ready=rst_n && qkv_phase && !qkv_write_pending && cycle%4!=0;
  qkv_write_rsp_valid=rst_n && qkv_phase && qkv_write_pending && qkv_write_delay==0;
 end

 tri_oracle_qkv429 fresh_projection (
  .clk,.rst_n,.cfg_valid(qkv_cfg_valid),.cfg_ready(qkv_cfg_ready),.cfg_tokens(5'd3),
  .cfg_start_head(6'd0),.cfg_heads(6'd40),.cfg_tag(QkvTag),
  .cfg_activation_base(QkvActivationBase),.cfg_weight_base(QkvWeightBase),
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
  .tensor_out_valid(qkv_phase && shared_raw_out_valid),.tensor_out_ready(qt_out_ready),
  .tensor_out_last(shared_raw_out_last),.tensor_out_tag(shared_raw_out_tag),.tensor_out_token(shared_raw_out_token),
  .tensor_out_count(shared_raw_out_count),.tensor_out_channels(shared_raw_out_channels),.tensor_out_data(shared_raw_out_data[4095:0]),
  .tensor_done_valid(qkv_phase && shared_raw_done_valid),.tensor_done_ready(qt_done_ready),
  .tensor_done_error(shared_raw_done_error),.tensor_done_tag(shared_raw_done_tag)
 );
 tri_oracle_qkv_store430 fresh_projection_store (
  .clk,.rst_n,.cfg_valid(qkv_cfg_valid),.cfg_ready(qkv_store_cfg_ready),.cfg_tag(QkvTag),
  .cfg_tokens(5'd3),.cfg_first_head(6'd0),.cfg_heads(6'd40),.cfg_slot(10'd0),.cfg_base(QkvCacheBase),
  .source_valid(qkv_out_valid),.source_ready(qkv_out_ready),.source_last(qkv_out_last),
  .source_tag(qkv_out_tag),.source_head(qkv_out_head),.source_token(qkv_out_token),.source_data(qkv_out_data),
  .source_done_valid(qkv_done_valid),.source_done_ready(qkv_done_ready),
  .source_done_error(qkv_done_error),.source_done_tag(qkv_done_tag),
  .write_valid(qkv_write_valid),.write_ready(qkv_write_ready),.write_address(qkv_write_address),.write_data(qkv_write_data),
  .write_rsp_valid(qkv_write_rsp_valid),.write_rsp_ready(qkv_write_rsp_ready),.write_rsp_error(1'b0),
  .done_valid(qkv_store_done_valid),.done_ready(qkv_store_done_ready),
  .done_error(qkv_store_done_error),.done_tag(qkv_store_done_tag)
 );

 always @(posedge clk)begin : fresh_projection_observation
  int head,token,channel,index;
  logic[63:0] offset;
  if(!rst_n)begin
   qkv_read_busy<=0;qkv_read_delay<=0;qkv_write_pending<=0;qkv_write_delay<=0;
   qkv_angle_index<=0;qkv_write_held<=0;
   for(int h=0;h<40;h++)for(int t=0;t<3;t++)begin qkv_written[h][t]<=0;qkv_acknowledged[h][t]<=0;end
  end else begin
   if(qkv_angle_valid && qkv_angle_ready)qkv_angle_index<=qkv_angle_index+1;
   if(qkv_phase && shared_raw_cfg_valid && shared_raw_cfg_ready)begin
    if(shared_raw_cfg_tokens!==5'd3 || shared_raw_cfg_count!==8'd128 || shared_raw_cfg_tag!==QkvTag ||
       shared_raw_cfg_dense_rows!==17'd2560 || !qkv_phase || ff_phase || co_route)
     $fatal(1,"FRESH_QKV_BAD_RAW_CONFIGURATION");
    qkv_configs++;
    $display("FRESH_QKV_CONFIG tag=%08h tokens=%0d count=%0d first_head=%0d",shared_raw_cfg_tag,shared_raw_cfg_tokens,shared_raw_cfg_count,int'(shared_raw_cfg_channels[15:0])/64);
   end
   if(qkv_phase && shared_raw_out_valid && shared_raw_out_ready)begin
    if(shared_raw_out_tag!==QkvTag || shared_raw_out_count!==8'd128 || shared_raw_out_token>2)
     $fatal(1,"FRESH_QKV_BAD_RAW_PACKET");
    for(int lane=0;lane<128;lane++)begin
     channel=int'(shared_raw_out_channels[lane*16+:16]);head=channel/64;token=int'(shared_raw_out_token);
     index=(head*3+token)*64+channel%64;
     if(head>=40 || shared_raw_out_data[lane*32+:32]!==qkv_expected_dots[index])
      $fatal(1,"FRESH_QKV_RAW_DOT_VALUE head=%0d token=%0d feature=%0d",head,token,channel%64);
    end
    qkv_packets++;
    $display("FRESH_QKV_RAW tag=%08h token=%0d count=%0d channels=%0640h data=%01024h",shared_raw_out_tag,shared_raw_out_token,shared_raw_out_count,shared_raw_out_channels,shared_raw_out_data[4095:0]);
   end
   if(qkv_phase && shared_raw_done_valid && shared_raw_done_ready)begin
    if(shared_raw_done_tag!==QkvTag || shared_raw_done_error)$fatal(1,"FRESH_QKV_RAW_TERMINAL_ERROR");
    qkv_tensor_completions++;
    $display("FRESH_QKV_TENSOR_DONE tag=%08h error=%0d",shared_raw_done_tag,shared_raw_done_error);
   end
   if(qkv_phase && projection_req_valid && projection_req_ready)begin
    if(qkv_read_busy || projection_req_length==0 || projection_req_length>16 || projection_req_address[2:0]!=0)
     $fatal(1,"FRESH_QKV_BAD_MEMORY_REQUEST");
    if(projection_req_address>=QkvActivationBase && projection_req_address<=QkvActivationBase+6144-64'(projection_req_length)*8)begin
     qkv_read_weights<=0;qkv_read_word<=int'((projection_req_address-QkvActivationBase)>>3);
    end else if(projection_req_address>=QkvWeightBase && projection_req_address<=QkvWeightBase+5242880-64'(projection_req_length)*8)begin
     qkv_read_weights<=1;qkv_read_word<=int'((projection_req_address-QkvWeightBase)>>3);
    end else $fatal(1,"FRESH_QKV_MEMORY_RANGE address=%016h",projection_req_address);
    qkv_read_busy<=1;qkv_read_remaining<=int'(projection_req_length);qkv_read_delay<=2+cycle%3;qkv_memory_requests++;
   end
   if(qkv_read_delay>0)qkv_read_delay<=qkv_read_delay-1;
   if(qkv_phase && projection_rsp_valid && projection_rsp_ready)begin
    if(!qkv_read_busy || projection_rsp_error)$fatal(1,"FRESH_QKV_MEMORY_RESPONSE_DEBT");
    qkv_memory_beats++;
    if(qkv_read_remaining==1)qkv_read_busy<=0;
    else begin qkv_read_word<=qkv_read_word+1;qkv_read_remaining<=qkv_read_remaining-1;qkv_read_delay<=cycle%3;end
   end
   if(qkv_write_valid && !qkv_write_ready)begin
    if(qkv_write_held && {qkv_held_address,qkv_held_data}!=={qkv_write_address,qkv_write_data})$fatal(1,"FRESH_QKV_UNSTABLE_WRITE");
    qkv_write_held<=1;qkv_held_address<=qkv_write_address;qkv_held_data<=qkv_write_data;
   end
   if(qkv_write_valid && qkv_write_ready)begin
    offset=qkv_write_address-QkvCacheBase;head=int'(offset>>16);token=int'((offset&64'hffff)>>6);
    if(qkv_write_pending || qkv_cache_committed || qkv_write_address<QkvCacheBase || head>=40 || token>=3 || offset[5:0]!=0)
     $fatal(1,"FRESH_QKV_BAD_CACHE_WRITE");
    if(qkv_written[head][token] || qkv_write_data!==qkv_expected_vectors[head*3+token])
     $fatal(1,"FRESH_QKV_PROJECTED_VECTOR_VALUE head=%0d token=%0d",head,token);
    qkv_cache[head][token]<=qkv_write_data;qkv_written[head][token]<=1;
    qkv_pending_head<=head;qkv_pending_token<=token;qkv_pending_address<=qkv_write_address;
    qkv_write_pending<=1;qkv_write_delay<=3+cycle%3;qkv_write_held<=0;qkv_vector_writes++;
    $display("FRESH_QKV_WRITE head=%0d token=%0d address=%016h data=%0128h",head,token,qkv_write_address,qkv_write_data);
   end
   if(qkv_write_delay>0)qkv_write_delay<=qkv_write_delay-1;
   if(qkv_write_rsp_valid && qkv_write_rsp_ready)begin
    if(!qkv_write_pending || !qkv_written[qkv_pending_head][qkv_pending_token] || qkv_acknowledged[qkv_pending_head][qkv_pending_token])
     $fatal(1,"FRESH_QKV_CACHE_ACK_DEBT");
    qkv_acknowledged[qkv_pending_head][qkv_pending_token]<=1;qkv_write_pending<=0;qkv_vector_acks++;
    $display("FRESH_QKV_ACK head=%0d token=%0d address=%016h",qkv_pending_head,qkv_pending_token,qkv_pending_address);
   end
   if(tensor_rsp_valid && tensor_rsp_ready)begin
    head=tensor_rsp_kind==0 ? int'(tensor_rsp_head):32+(int'(tensor_rsp_kind)-1)*4+int'(tensor_rsp_head)/8;
    token=tensor_rsp_kind==0 ? int'(tensor_rsp_query):int'(tensor_rsp_key);
    if(qkv_phase || !qkv_cache_committed || tensor_rsp_kind>2 || head>=40 || token>=3 || !qkv_acknowledged[head][token] ||
       tensor_rsp_data!==qkv_cache[head][token])$fatal(1,"FRESH_QKV_CACHE_RESPONSE_SOURCE");
    qkv_operands++;
    $display("FRESH_QKV_OPERAND kind=%0d head=%0d key=%0d query=%0d epoch=%04h tag=%08h size=%0d data=%0128h",tensor_rsp_kind,tensor_rsp_head,tensor_rsp_key,tensor_rsp_query,tensor_rsp_epoch,tensor_rsp_tag,tensor_rsp_size,tensor_rsp_data);
    if(tensor_rsp_data!==gold_vector_data(int'(tensor_rsp_kind),int'(tensor_rsp_head),int'(tensor_rsp_key)))begin
     if(corrupt_qkv_cache && head==0 && token==1 && tensor_rsp_data===(qkv_expected_vectors[1]^512'd1))begin
      $display("FRESH_QKV_EXPECTED_CORRUPTION_DETECTED head=0 token=1 bit=0");
      $fatal(1,"FRESH_QKV_CORRUPT_OPERAND_ASSERTION");
     end
     $fatal(1,"FRESH_QKV_UNEXPECTED_OPERAND_VALUE");
    end
   end
  end
 end

 task automatic prepare_live_qkv;
  logic[511:0] before_corruption;
  $display("FRESH_QKV_BEGIN tokens=3 heads=40 feature_words=256 dense_rows=2560");
  while(!qkv_cfg_ready || !qkv_store_cfg_ready)@(negedge clk);
  @(negedge clk);qkv_cfg_valid=1;
  do @(posedge clk);while(!(qkv_cfg_ready && qkv_store_cfg_ready));
  @(negedge clk);qkv_cfg_valid=0;qkv_started=1;
  while(!qkv_store_done_valid)@(negedge clk);
  if(qkv_store_done_error || qkv_store_done_tag!==QkvTag || qkv_angle_index!=3 ||
     qkv_configs!=20 || qkv_packets!=60 || qkv_tensor_completions!=20 || qkv_vector_writes!=120 || qkv_vector_acks!=120 ||
     qkv_write_pending || qkv_read_busy || !shared_raw_cfg_ready || shared_raw_out_valid || shared_raw_done_valid || projection_req_valid)
   $fatal(1,"FRESH_QKV_EARLY_CACHE_COMMIT");
  for(int head=0;head<40;head++)for(int token=0;token<3;token++)
   if(!qkv_written[head][token] || !qkv_acknowledged[head][token])$fatal(1,"FRESH_QKV_UNWRITTEN_CACHE_SLOT");
  qkv_store_done_ready=1;@(negedge clk);qkv_store_done_ready=0;
  if(qkv_store_done_valid || !qkv_cfg_ready || !qkv_store_cfg_ready)$fatal(1,"FRESH_QKV_TERMINAL_NOT_DRAINED");
  qkv_cache_committed=1;
  $display("FRESH_QKV_COMMIT tag=%08h configs=%0d packets=%0d vectors=%0d acks=%0d",QkvTag,qkv_configs,qkv_packets,qkv_vector_writes,qkv_vector_acks);
  if(corrupt_qkv_cache)begin
   before_corruption=qkv_cache[0][1];qkv_cache[0][1][0]=~qkv_cache[0][1][0];
   $display("FRESH_QKV_CORRUPTED head=0 token=1 bit=0 before=%0128h after=%0128h",before_corruption,qkv_cache[0][1]);
  end
  qkv_phase=0;
 endtask
