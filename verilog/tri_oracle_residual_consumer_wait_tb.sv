`timescale 1ns/1ps
// Model the real consumer holding token0 until its last activation-write ack.
// This does not substitute a token supplied by the replay producer itself.
module tri_oracle_residual_consumer_wait_tb;
 localparam logic[31:0] Tag=32'h524c5701;
 logic clk=0,rst_n=0;
 always #5 clk=~clk;
 logic frame_available=0,start_valid=0,start_ready,clear_valid=0,clear_ready;
 logic[31:0] frame_tag=Tag;
 logic[9:0] frame_rows=4;
 logic[4:0] cfg_tokens=2;
 logic[8:0] cfg_strips=2;
 logic normalization_done,frame_fault;
 logic[3:0] fault_code,normalization_token,consumer_token=0;
 logic[8:0] normalization_strip;
 logic stats_valid,stats_ready,stats_last,replay_valid,replay_ready,replay_last;
 logic[127:0] stats_data,replay_data;
 logic bank_read_valid=0,bank_read_ready,bank_response_valid,bank_response_error,bank_response_ready=0;
 logic[8:0] bank_read_row=0;
 logic[231:0] bank_response_data;
 logic read_valid,read_ready,response_valid,response_error=0,response_ready;
 logic[31:0] read_tag,response_tag=Tag;
 logic[8:0] read_row,response_row=0;
 logic[231:0] response_bypass=0;
 logic[127:0] response_normalization;
 logic memory_busy=0;
 int response_delay=0,cycle=0,requests=0,responses=0,stats=0,replays=0;
 int lag_remaining=0,lag_cycles=0,read_ahead=0;
 bit lag_started=0,lag_completed=0;
 tri_oracle_residual_replay_link_wait_consumer link(.*);
 always_comb begin
  read_ready=rst_n && !memory_busy;
  response_valid=rst_n && memory_busy && response_delay==0;
  response_normalization=128'h80007000600050004000300020001000+128'(response_row);
  stats_ready=rst_n && lag_remaining==0;
  replay_ready=stats_ready;
 end
 always @(posedge clk)begin
  if(!rst_n)begin
   memory_busy<=0;response_delay<=0;cycle<=0;
   requests<=0;responses<=0;stats<=0;replays<=0;
   lag_remaining<=0;lag_cycles<=0;consumer_token<=0;lag_started<=0;lag_completed<=0;read_ahead<=0;
  end else begin
   cycle<=cycle+1;
   if(cycle>1000)$fatal(1,"CONSUMER_LAG_WATCHDOG");
   if(frame_fault)$fatal(1,"CONSUMER_LAG_FRAME_FAULT code=%0d consumer=%0d pending_token=%0d row=%0d lag=%0d",
                         fault_code,consumer_token,normalization_token,response_row,lag_remaining);
   if(read_valid && read_ready)begin
    if(read_tag!==Tag || read_row>=4)$fatal(1,"CONSUMER_LAG_BAD_DESCRIPTOR");
    memory_busy<=1;response_row<=read_row;response_delay<=2;requests<=requests+1;
    if(lag_remaining>0)read_ahead<=read_ahead+1;
    $display("CONSUMER_READ row=%0d consumer=%0d lag=%0d",read_row,consumer_token,lag_remaining);
   end
   if(response_delay>0)response_delay<=response_delay-1;
   if(response_valid && response_ready)begin memory_busy<=0;responses<=responses+1;end
   if(stats_valid && stats_ready)begin
    if(normalization_token!==4'(stats/2) || normalization_strip!==9'(stats%2) ||
       stats_last!==(stats%2==1) || stats_data!==128'h80007000600050004000300020001000+128'(stats))
     $fatal(1,"CONSUMER_LAG_STATS_VALUE");
    stats<=stats+1;
   end
   if(replay_valid && replay_ready)begin
    if(normalization_token!==4'(replays/2) || normalization_strip!==9'(replays%2) ||
       replay_last!==(replays%2==1) || replay_data!==128'h80007000600050004000300020001000+128'(replays))
     $fatal(1,"CONSUMER_LAG_REPLAY_VALUE");
    replays<=replays+1;
    if(replays==1)begin
     lag_remaining<=40;lag_started<=1;
     $display("CONSUMER_LAG_BEGIN token=0 held_cycles=40");
    end
   end
   if(lag_remaining>0)begin
    lag_remaining<=lag_remaining-1;lag_cycles<=lag_cycles+1;
    if(lag_remaining==1)begin consumer_token<=1;lag_completed<=1;$display("CONSUMER_TOKEN_ADVANCE token=1");end
   end
  end
 end
 initial begin
  repeat(3)@(negedge clk);rst_n=1;frame_available=1;
  @(negedge clk);start_valid=1;
  do @(posedge clk);while(!start_ready);
  @(negedge clk);start_valid=0;
  while(!normalization_done)@(negedge clk);
  if(frame_fault || !lag_started || !lag_completed || lag_cycles!=40 || read_ahead!=0 ||
     requests!=8 || responses!=8 || stats!=4 || replays!=4 || memory_busy)
   $fatal(1,"CONSUMER_LAG_FINAL_COUNTS requests=%0d responses=%0d stats=%0d replays=%0d lag=%0d ahead=%0d",
          requests,responses,stats,replays,lag_cycles,read_ahead);
  clear_valid=1;do @(posedge clk);while(!clear_ready);
  @(negedge clk);clear_valid=0;
  if(!start_ready || normalization_done)$fatal(1,"CONSUMER_LAG_CLEAR");
  $display("CONSUMER_LAG_PASS tokens=2 strips=2 stats=4 replay=4 requests=8 responses=8 lag_cycles=40 read_ahead=0");
  $finish;
 end
endmodule
