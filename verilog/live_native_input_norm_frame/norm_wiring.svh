 initial begin
  if(!$value$plusargs("NORM_INPUT_ROOT=%s",native_norm_root))$fatal(1,"LIVE_INPUT_NORM_FIXTURES_MISSING");
  $readmemh({native_norm_root,"/norm_raw.hex"},norm_raw_words);
  $readmemh({native_norm_root,"/norm_gamma.hex"},norm_gamma_words);
  $readmemh({native_norm_root,"/norm_epsilon.hex"},norm_epsilons);
  $readmemh({native_norm_root,"/norm_expected.hex"},norm_expected_words);
  $readmemh({native_norm_root,"/norm_expected_exponents.hex"},norm_expected_exponents);
  $readmemh({native_norm_root,"/norm_expected_outliers.hex"},norm_expected_outliers);
  $readmemh({native_norm_root,"/norm_expected_negative.hex"},norm_expected_negative);
  $readmemh({native_norm_root,"/static_head_shifts.hex"},qkv_shifts);
  qkv_biases[0]='0;norm_fixture_loaded=1;
 end
 tri_oracle_fused_input_normalizer input_normalizer(
  .clk,.rst_n,.cfg_valid(norm_cfg_valid),.cfg_ready(norm_cfg_ready),.cfg_tag(norm_cfg_tag),
  .cfg_strips(10'd256),.cfg_epsilon_q16(norm_cfg_epsilon),.cfg_gamma_exponent(-8'sd14),
  .stats_valid(norm_stats_valid),.stats_ready(norm_stats_ready),.stats_last(norm_stats_last),
  .stats_data(norm_stats_data),.stats_gamma(norm_stats_gamma),
  .replay_valid(norm_replay_valid),.replay_ready(norm_replay_ready),.replay_last(norm_replay_last),
  .replay_data(norm_replay_data),.replay_gamma(norm_replay_gamma),
  .out_valid(norm_out_valid),.out_ready(norm_out_ready),.out_last(norm_out_last),.out_error(norm_out_error),
  .out_tag(norm_out_tag),.out_index(norm_out_index),.out_count(norm_out_count),
  .out_activation(norm_out_activation),.out_exponent(norm_out_exponent),
  .out_outlier_mask(norm_out_outliers),.out_outlier_negative(norm_out_negative));
 always_comb norm_out_ready=rst_n&&norm_phase&&!norm_write_pending&&cycle%7!=2;
 function automatic logic[63:0] native_normalized_word(input int index);
  if(index<0||index>=768||!norm_cache_committed||!norm_acknowledged[index])
   $fatal(1,"LIVE_INPUT_NORM_UNCOMMITTED_READ index=%0d",index);
  return norm_cache[index];
 endfunction
 always @(posedge clk)begin :native_norm_cache_observer
  int index;
  logic[136:0]payload;
  if(!rst_n)begin
   norm_write_pending<=0;norm_write_delay<=0;norm_write_held<=0;norm_phase<=0;norm_cache_committed<=0;
   norm_writes=0;norm_acks=0;norm_reads=0;norm_stats_words=0;norm_replay_words=0;
   for(int i=0;i<768;i++)begin norm_written[i]<=0;norm_acknowledged[i]<=0;end
   for(int t=0;t<3;t++)begin norm_terminal_seen[t]<=0;norm_observed_exponents[t]<='0;end
  end else begin
   if(norm_cfg_valid&&norm_cfg_ready)$display("LIVE_INPUT_NORM_CONFIG token=%0d tag=%08h strips=256 epsilon=%016h gamma_exponent=-14",norm_token,norm_cfg_tag,norm_cfg_epsilon);
   if(norm_stats_valid&&norm_stats_ready)begin
    $display("LIVE_INPUT_NORM_STATS token=%0d strip=%0d raw=%064h gamma=%032h last=%0b",norm_token,norm_stats_words%256,norm_stats_data,norm_stats_gamma,norm_stats_last);norm_stats_words++;
   end
   if(norm_replay_valid&&norm_replay_ready)begin
    $display("LIVE_INPUT_NORM_REPLAY token=%0d strip=%0d raw=%064h gamma=%032h last=%0b",norm_token,norm_replay_words%256,norm_replay_data,norm_replay_gamma,norm_replay_last);norm_replay_words++;
   end
   payload={norm_out_last,norm_out_error,norm_out_tag,norm_out_index,norm_out_count,norm_out_activation,norm_out_exponent,norm_out_outliers,norm_out_negative};
   if(norm_write_held&&(!norm_out_valid||payload!==norm_held_output))$fatal(1,"LIVE_INPUT_NORM_OUTPUT_CHANGED");
   norm_write_held<=norm_out_valid&&!norm_out_ready;if(norm_out_valid&&!norm_out_ready)norm_held_output<=payload;
   if(norm_out_valid&&norm_out_ready)begin
    index=norm_token*256+int'(norm_out_index);
    if(!norm_phase||norm_cache_committed||norm_token>2||norm_out_error||norm_out_tag!==(NormTagBase+32'(norm_token))||
       norm_out_count!==8||norm_out_index>=256||norm_out_last!==(norm_out_index==255)||index<0||index>=768||norm_written[index])
     $fatal(1,"LIVE_INPUT_NORM_BAD_OUTPUT token=%0d index=%0d",norm_token,index);
    if(norm_out_activation!==norm_expected_words[index]||norm_out_exponent!==norm_expected_exponents[norm_token]||
       norm_out_outliers!==norm_expected_outliers[index]||norm_out_negative!==norm_expected_negative[index])$fatal(1,"LIVE_INPUT_NORM_VALUE token=%0d strip=%0d",norm_token,norm_out_index);
    if(norm_out_index==0)norm_observed_exponents[norm_token]<=norm_out_exponent;
    else if(norm_out_exponent!==norm_observed_exponents[norm_token])$fatal(1,"LIVE_INPUT_NORM_UNIT_CHANGED");
    norm_cache[index]<=norm_out_activation;norm_written[index]<=1;
    norm_pending_word<=index;norm_pending_data<=norm_out_activation;norm_write_pending<=1;norm_write_delay<=2+cycle%3;norm_writes++;
    if(norm_out_last)norm_terminal_seen[norm_token]<=1;
    $display("LIVE_INPUT_NORM_WRITE token=%0d strip=%0d tag=%08h exponent=%0d mask=%02h negative=%02h last=%0b data=%016h",norm_token,norm_out_index,norm_out_tag,$signed(norm_out_exponent),norm_out_outliers,norm_out_negative,norm_out_last,norm_out_activation);
   end
   if(norm_write_delay>0)norm_write_delay<=norm_write_delay-1;
   if(norm_write_pending&&norm_write_delay==0)begin
    if(!norm_written[norm_pending_word]||norm_acknowledged[norm_pending_word]||norm_cache[norm_pending_word]!==norm_pending_data)
     $fatal(1,"LIVE_INPUT_NORM_ACK_DEBT");
    norm_acknowledged[norm_pending_word]<=1;norm_write_pending<=0;norm_acks++;
    $display("LIVE_INPUT_NORM_ACK word=%0d data=%016h",norm_pending_word,norm_pending_data);
   end
   if(qkv_cfg_valid&&qkv_cfg_ready&&qkv_store_cfg_ready)begin
    if(!norm_cache_committed||norm_acks!=768||norm_phase||norm_write_pending)$fatal(1,"LIVE_INPUT_NORM_QKV_EARLY_CONFIGURATION");
    $display("LIVE_INPUT_NORM_QKV_UNITS shifts=%060h biases=%024h",qkv_shifts[0],qkv_biases[0]);
   end
   if(qkv_phase&&projection_rsp_valid&&projection_rsp_ready&&!qkv_read_weights)begin
    if(!norm_cache_committed||qkv_read_word<0||qkv_read_word>=768||!norm_acknowledged[qkv_read_word]||projection_rsp_data[63:0]!==norm_cache[qkv_read_word])
     $fatal(1,"LIVE_INPUT_NORM_READ_SOURCE");
    norm_reads++;$display("LIVE_INPUT_NORM_READ word=%0d data=%016h",qkv_read_word,projection_rsp_data[63:0]);
   end
  end
 end
 task automatic prepare_native_input_normalization;
  int bias;
  $display("LIVE_INPUT_NORM_BEGIN tokens=3 features=2048");
  if(!norm_fixture_loaded||norm_cache_committed||norm_writes!=0||norm_acks!=0)$fatal(1,"LIVE_INPUT_NORM_BAD_BEGIN");
  norm_phase=1;
  for(norm_token=0;norm_token<3;norm_token++)begin
   while(!norm_cfg_ready)@(negedge clk);
   @(negedge clk);norm_cfg_tag=NormTagBase+32'(norm_token);norm_cfg_epsilon=norm_epsilons[norm_token];norm_cfg_valid=1;
   do @(posedge clk);while(!norm_cfg_ready);
   @(negedge clk);norm_cfg_valid=0;
   for(int i=0;i<256;i++)begin
    @(negedge clk);norm_stats_valid=1;norm_stats_last=i==255;norm_stats_data=norm_raw_words[norm_token*256+i];norm_stats_gamma=norm_gamma_words[i];
    do @(posedge clk);while(!norm_stats_ready);
    @(negedge clk);norm_stats_valid=0;
   end
   for(int i=0;i<256;i++)begin
    @(negedge clk);norm_replay_valid=1;norm_replay_last=i==255;norm_replay_data=norm_raw_words[norm_token*256+i];norm_replay_gamma=norm_gamma_words[i];
    do @(posedge clk);while(!norm_replay_ready);
    @(negedge clk);norm_replay_valid=0;
   end
   while(!norm_terminal_seen[norm_token]||norm_acks!=(norm_token+1)*256||norm_write_pending)@(negedge clk);
   if(!norm_cfg_ready||norm_out_valid)$fatal(1,"LIVE_INPUT_NORM_TERMINAL_NOT_RELEASED");
   bias=-int'($signed(norm_observed_exponents[norm_token]));
   if(bias<0||bias>63)$fatal(1,"LIVE_INPUT_NORM_BIAS_RANGE");
   qkv_biases[0][norm_token*6+:6]=6'(bias);
   $display("LIVE_INPUT_NORM_TOKEN_COMMIT token=%0d exponent=%0d bias=%0d acks=%0d",norm_token,$signed(norm_observed_exponents[norm_token]),bias,norm_acks);
  end
  for(int i=0;i<768;i++)if(!norm_written[i]||!norm_acknowledged[i])$fatal(1,"LIVE_INPUT_NORM_UNWRITTEN_WORD");
  if(norm_writes!=768||norm_acks!=768||norm_stats_words!=768||norm_replay_words!=768||norm_write_pending)$fatal(1,"LIVE_INPUT_NORM_COMMIT_DEBT");
  norm_phase=0;norm_cache_committed=1;
  $display("LIVE_INPUT_NORM_COMMIT words=%0d acks=%0d biases=%024h shifts=%060h",norm_writes,norm_acks,qkv_biases[0],qkv_shifts[0]);
  if(corrupt_normalized_cache)begin
   norm_corruption_before=norm_cache[0];norm_cache[0]=norm_cache[0]^64'd1;norm_corruption_after=norm_cache[0];
   $display("LIVE_INPUT_NORM_CORRUPTED word=0 bit=0 before=%016h after=%016h",norm_corruption_before,norm_corruption_after);
  end
 endtask
