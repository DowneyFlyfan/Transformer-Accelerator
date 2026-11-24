`timescale 1ns/1ps
module tri_oracle_fused_input_normalizer_tb;
 logic clk=0,rst_n=0;
 always #5 clk=~clk;
 logic cfg_valid=0,cfg_ready;
 logic[31:0]cfg_tag=0,expected_tag=0;
 logic[9:0]cfg_strips=0;
 logic[63:0]cfg_epsilon_q16=0;
 logic signed[7:0]cfg_gamma_exponent=0;
 logic stats_valid=0,stats_ready,stats_last=0;
 logic[255:0]stats_data=0;
 logic[127:0]stats_gamma=0;
 logic replay_valid=0,replay_ready,replay_last=0;
 logic[255:0]replay_data=0;
 logic[127:0]replay_gamma=0;
 logic out_valid,out_ready=0,out_last,out_error;
 logic[31:0]out_tag;
 logic[9:0]out_index;
 logic[3:0]out_count;
 logic[63:0]out_activation;
 logic signed[8:0]out_exponent;
 logic[7:0]out_outlier_mask,out_outlier_negative;
 tri_oracle_fused_input_normalizer dut(.*);
 logic[255:0]raw_words[71936],control_raw[512];
 logic[127:0]gamma_words[256],control_gamma[512];
 logic[63:0]expected_words[71936],control_expected[512];
 logic[7:0]expected_outliers[71936],expected_negative[71936],control_outliers[512],control_negative[512];
 logic[63:0]epsilons[281];
 logic[8:0]exponents[281];
 int cycle=0,received=0,terminals=0,errors=0,frames=0,values=0,cfg_stall_cycles=0;
 int expected_strips=0,current_token=0,expected_exponent=0;
 bit active=0,trained=0,expected_fault=0,hold_output=0,held=0;
 logic[136:0]held_word;
 string root,controls;
 int tokens=3;
 function automatic logic[136:0]visible_word();
  return {out_last,out_error,out_tag,out_index,out_count,out_activation,out_exponent,out_outlier_mask,out_outlier_negative};
 endfunction
 always @(negedge clk) out_ready<=rst_n&&!hold_output&&(cycle%7!=2)&&(cycle%7!=3);
 always @(posedge clk)begin
  cycle++;
  if(cycle>1500000)$fatal(1,"FUSED_UNIT_WATCHDOG");
  if(!rst_n)held=0;
  else begin
   if(held&&(!out_valid||visible_word()!==held_word))$fatal(1,"FUSED_STALLED_OUTPUT_CHANGED");
   held=out_valid&&!out_ready;if(held)held_word=visible_word();
   if(cfg_valid&&cfg_ready)$display("FUSED_UNIT_CONFIG tag=%08h strips=%0d epsilon=%016h gamma_exponent=%0d",cfg_tag,cfg_strips,cfg_epsilon_q16,$signed(cfg_gamma_exponent));
   if(cfg_valid&&!cfg_ready)begin cfg_stall_cycles++;$display("FUSED_UNIT_CONFIG_STALL offered_tag=%08h active_tag=%08h ready=%0b",cfg_tag,expected_tag,cfg_ready);end
   if(stats_valid&&stats_ready)$display("FUSED_UNIT_STATS tag=%08h cycle=%0d raw=%064h gamma=%032h last=%0b",cfg_tag,cycle,stats_data,stats_gamma,stats_last);
   if(replay_valid&&replay_ready)$display("FUSED_UNIT_REPLAY tag=%08h cycle=%0d raw=%064h gamma=%032h last=%0b",cfg_tag,cycle,replay_data,replay_gamma,replay_last);
   if(out_valid&&out_ready)begin
    if(!active||out_tag!==expected_tag)$fatal(1,"FUSED_UNEXPECTED_OUTPUT");
    if(out_error)begin
     if(!expected_fault||!out_last||out_count!==0||out_activation!==0||out_outlier_mask!==0||out_outlier_negative!==0)$fatal(1,"FUSED_BAD_ERROR_WORD");
     errors++;terminals++;active=0;$display("FUSED_UNIT_EXPECTED_ERROR tag=%08h provisional_strips=%0d",out_tag,received);
    end else begin
     if(out_index!==10'(received)||out_count!==8||out_exponent!==9'(expected_exponent))$fatal(1,"FUSED_METADATA_MISMATCH strip=%0d",received);
     if(trained)begin
      if(out_activation!==expected_words[current_token*256+received]||out_outlier_mask!==expected_outliers[current_token*256+received]||out_outlier_negative!==expected_negative[current_token*256+received])$fatal(1,"FUSED_TRAINED_VALUE_MISMATCH token=%0d strip=%0d",current_token,received);
     end else if(out_activation!==control_expected[received]||out_outlier_mask!==control_outliers[received]||out_outlier_negative!==control_negative[received])$fatal(1,"FUSED_CONTROL_VALUE_MISMATCH strip=%0d",received);
     if(out_last!==(received+1==expected_strips))$fatal(1,"FUSED_BAD_LAST");
     $display("FUSED_UNIT_VALUE tag=%08h trained=%0b token=%0d strip=%0d exponent=%0d mask=%02h negative=%02h codes=%016h last=%0b",out_tag,trained,current_token,received,$signed(out_exponent),out_outlier_mask,out_outlier_negative,out_activation,out_last);
     received++;values+=8;
     if(out_last)begin if(expected_fault)$fatal(1,"FUSED_MISSING_EXPECTED_ERROR");terminals++;frames++;active=0;end
    end
   end
  end
 end
 task automatic configure(input int strips,input logic[63:0]epsilon,input int gamma_e,input int exponent,input bit fault);
  if(active)$fatal(1,"FUSED_DRIVER_OVERLAP");
  expected_strips=strips;expected_exponent=exponent;expected_fault=fault;received=0;active=1;
  @(negedge clk);cfg_tag++;expected_tag=cfg_tag;cfg_strips=10'(strips);cfg_epsilon_q16=epsilon;cfg_gamma_exponent=8'(gamma_e);cfg_valid=1;
  do @(posedge clk);while(!cfg_ready);
  @(negedge clk);cfg_valid=0;
 endtask
 task automatic stats(input logic[255:0]data,input logic[127:0]gamma,input bit last);
  @(negedge clk);stats_valid=1;stats_data=data;stats_gamma=gamma;stats_last=last;
  do @(posedge clk);while(!stats_ready);
  @(negedge clk);stats_valid=0;
 endtask
 task automatic replay(input logic[255:0]data,input logic[127:0]gamma,input bit last);
  @(negedge clk);replay_valid=1;replay_data=data;replay_gamma=gamma;replay_last=last;
  do @(posedge clk);while(!replay_ready);
  @(negedge clk);replay_valid=0;
 endtask
 task automatic await_terminal();
  wait(!active);@(negedge clk);if(!cfg_ready)$fatal(1,"FUSED_TERMINAL_DID_NOT_RELEASE");
 endtask
 task automatic load_control(input int ident,input int words);
  $readmemh($sformatf("%s/control%0d_raw.hex",controls,ident),control_raw,0,words-1);
  $readmemh($sformatf("%s/control%0d_gamma.hex",controls,ident),control_gamma,0,words-1);
  $readmemh($sformatf("%s/control%0d_expected.hex",controls,ident),control_expected,0,words-1);
  $readmemh($sformatf("%s/control%0d_outliers.hex",controls,ident),control_outliers,0,words-1);
  $readmemh($sformatf("%s/control%0d_negative.hex",controls,ident),control_negative,0,words-1);
 endtask
 task automatic good_control(input int ident,input int strips,input logic[63:0]epsilon,input int gamma_e,input int exponent);
  trained=0;load_control(ident,strips);configure(strips,epsilon,gamma_e,exponent,0);
  for(int i=0;i<strips;i++)stats(control_raw[i],control_gamma[i],i+1==strips);
  for(int i=0;i<strips;i++)replay(control_raw[i],control_gamma[i],i+1==strips);
  await_terminal();$display("FUSED_UNIT_CONTROL_PASS ident=%0d",ident);
 endtask
 task automatic reset_frame();
  @(negedge clk);$display("FUSED_UNIT_RESET active_tag=%08h",expected_tag);rst_n=0;stats_valid=0;replay_valid=0;cfg_valid=0;active=0;
  repeat(3)@(negedge clk);if(out_valid||!cfg_ready)$fatal(1,"FUSED_RESET_DID_NOT_CANCEL");rst_n=1;
  repeat(2)@(negedge clk);
 endtask
 initial begin
  if(!$value$plusargs("NORM_ROOT=%s",root)||!$value$plusargs("CONTROL_ROOT=%s",controls))$fatal(1,"FUSED_UNIT_ROOT_MISSING");
  if($value$plusargs("TOKENS=%d",tokens))begin end
  if(tokens!=3&&tokens!=281)$fatal(1,"FUSED_UNIT_TOKEN_COUNT");
  $readmemh({root,"/raw.hex"},raw_words);$readmemh({root,"/gamma.hex"},gamma_words);
  $readmemh({root,"/expected.hex"},expected_words);$readmemh({root,"/outliers.hex"},expected_outliers);
  $readmemh({root,"/outlier_negative.hex"},expected_negative);$readmemh({root,"/epsilon.hex"},epsilons);
  $readmemh({root,"/expected_exponents.hex"},exponents);
  reset_frame();
  good_control(0,1,0,0,0);good_control(1,1,0,0,1);good_control(2,2,0,0,0);
  good_control(3,2,0,-14,-14);good_control(4,512,0,-14,1);
  good_control(5,1,64'hffffffffffffffff,-128,-118);
  good_control(6,1,0,-14,0);good_control(7,1,1,-14,0);
  trained=0;load_control(0,1);
  configure(0,0,0,0,1);await_terminal();configure(513,0,0,0,1);await_terminal();
  configure(2,0,0,0,1);stats(control_raw[0],control_gamma[0],1);await_terminal();
  configure(1,0,0,0,1);stats(control_raw[0],control_gamma[0],0);stats(control_raw[0],control_gamma[0],1);await_terminal();
  configure(1,0,0,0,1);stats('0,control_gamma[0],1);await_terminal();
  configure(2,0,0,0,1);stats(control_raw[0],control_gamma[0],0);stats(control_raw[0],control_gamma[0],1);replay(control_raw[0],control_gamma[0],1);await_terminal();
  configure(1,0,0,0,1);stats(control_raw[0],control_gamma[0],1);replay(control_raw[0],control_gamma[0],0);replay(control_raw[0],control_gamma[0],1);await_terminal();
  configure(2,0,0,0,1);stats(control_raw[0],control_gamma[0],0);stats(control_raw[0],control_gamma[0],1);replay(control_raw[0],control_gamma[0],0);replay(control_raw[0]^256'd3,control_gamma[0]^128'd64,1);await_terminal();
  configure(2,0,0,0,1);stats(control_raw[0],control_gamma[0],0);stats(control_raw[0],control_gamma[0],1);replay(control_raw[0],control_gamma[0],0);replay(control_raw[0],control_gamma[0]^128'd128,1);await_terminal();
  configure(2,0,0,0,0);stats(control_raw[0],control_gamma[0],0);reset_frame();
  configure(1,0,0,0,0);hold_output=1;stats(control_raw[0],control_gamma[0],1);replay(control_raw[0],control_gamma[0],1);wait(out_valid);
  @(negedge clk);cfg_valid=1;cfg_tag=cfg_tag+32'h40000;cfg_strips=1;cfg_epsilon_q16=0;cfg_gamma_exponent=0;
  repeat(8)begin @(negedge clk);if(cfg_ready)$fatal(1,"FUSED_BUSY_CONFIGURATION_ACCEPTED");end
  reset_frame();hold_output=0;
  good_control(0,1,0,0,0);
  for(int t=0;t<tokens;t++)begin
   trained=1;current_token=t;configure(256,epsilons[t],-14,$signed(exponents[t]),0);
   for(int i=0;i<256;i++)begin if(i%17==3)repeat(2)@(negedge clk);stats(raw_words[t*256+i],gamma_words[i],i==255);end
   for(int i=0;i<256;i++)replay(raw_words[t*256+i],gamma_words[i],i==255);
   await_terminal();$display("FUSED_UNIT_TRAINED_TOKEN_PASS token=%0d",t);
  end
  if(cfg_stall_cycles<8)$fatal(1,"FUSED_CONFIGURATION_STALL_NOT_OBSERVED");
  if(errors!=9||frames!=9+tokens)$fatal(1,"FUSED_UNIT_COUNTS errors=%0d frames=%0d",errors,frames);
  $display("FUSED_NORMALIZATION_UNIT_PASS trained_tokens=%0d trained_values=%0d controls=8 recovery=1 errors=9 reset_controls=2 configuration_stall_cycles=%0d",tokens,tokens*2048,cfg_stall_cycles);$finish;
 end
endmodule
