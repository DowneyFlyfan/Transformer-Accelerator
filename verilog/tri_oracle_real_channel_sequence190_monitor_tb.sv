`timescale 1ns/1ps
module tri_oracle_real_channel_sequence190_monitor_tb;
  logic clk=0;always #5 clk=~clk;
  logic rst_n=0,packet_valid=0,packet_ready=0,packet_last=0,packet_error=0,packet_fallback=0;
  logic [31:0] packet_tag=32'h19001234;
  logic [7:0] packet_count=0;
  logic [2559:0] packet_channels=0;
  int channels_seen,packets_seen,mode=0;
  bit done;
  tri_oracle_real_channel_sequence190_monitor monitor(.*);
  initial begin
    if($value$plusargs("MUTANT=%d",mode)) begin end
    repeat(3) @(negedge clk);rst_n=1;
    for(int packet=0;packet<36;packet++) begin
      @(negedge clk);packet_valid=1;packet_ready=0;packet_count=packet==35?32:160;packet_last=packet==35;
      for(int row=0;row<160;row++) packet_channels[row*16+:16]=16'(packet*160+row);
      if(mode==1 && packet==0) packet_channels[0+:16]=1;
      if(mode==2 && packet==1) packet_channels[0+:16]=0;
      if(mode==3 && packet==0) packet_count=159;
      if(mode==4 && packet==0) packet_last=1;
      if(mode==5 && packet==0) packet_tag=0;
      if(mode==8 && packet==0) packet_valid=1'bx;
      @(negedge clk);
      if(mode==6 && packet==0) packet_channels[0+:16]=1;
      @(negedge clk);packet_ready=1;
      @(posedge clk);@(negedge clk);packet_valid=0;packet_ready=0;packet_channels='x;
    end
    if(mode==7) begin
      @(negedge clk);packet_valid=1;packet_ready=1;
      @(posedge clk);@(negedge clk);
    end
    if(!done || channels_seen!=5632 || packets_seen!=36) $fatal(1,"REAL_CHANNEL_MONITOR_INVENTORY");
    $display("REAL_CHANNEL_MONITOR_PASS channels=%0d packets=%0d",channels_seen,packets_seen);$finish;
  end
  initial begin #10000; $fatal(1,"REAL_CHANNEL_MONITOR_WATCHDOG"); end
endmodule
