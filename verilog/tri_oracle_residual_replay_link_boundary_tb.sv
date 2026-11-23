`timescale 1ns/1ps
// Direct protocol controls for the actual synthesizable link. Literal response
// payloads test delivery; they do not represent trained-model arithmetic.
module tri_oracle_residual_replay_link_boundary_tb;
 localparam logic[31:0] Tag=32'h524c3201;
 localparam logic[127:0] Word0=128'h0123456789abcdef_fedcba9876543210;
 localparam logic[127:0] Word1=128'h0001000200030004_0005000600070008;
 logic clk=0,rst_n=0;
 always #5 clk=~clk;
 logic frame_available=0,start_valid=0,start_ready,clear_valid=0,clear_ready;
 logic[31:0] frame_tag=Tag;
 logic[9:0] frame_rows=2;
 logic[4:0] cfg_tokens=1;
 logic[8:0] cfg_strips=2;
 logic normalization_done,frame_fault;
 logic[3:0] fault_code,normalization_token,consumer_token=0;
 logic[8:0] normalization_strip;
 logic stats_valid,stats_ready=0,stats_last,replay_valid,replay_ready=0,replay_last;
 logic[127:0] stats_data,replay_data;
 logic bank_read_valid=0,bank_read_ready,bank_response_valid,bank_response_error,bank_response_ready=0;
 logic[8:0] bank_read_row=0;
 logic[231:0] bank_response_data;
 logic read_valid,read_ready=0,response_valid=0,response_error=0,response_ready;
 logic[31:0] read_tag,response_tag=Tag;
 logic[8:0] read_row,response_row=0;
 logic[231:0] response_bypass='1;
 logic[127:0] response_normalization=0;
 int requests=0,responses=0,normal_accepts=0;
 tri_oracle_residual_replay_link link(.*);
 always @(posedge clk)if(rst_n)begin
  if(read_valid && read_ready)requests++;
  if(response_valid && response_ready)responses++;
  if(stats_valid && stats_ready || replay_valid && replay_ready)normal_accepts++;
  if(responses>requests || requests-responses>1)$fatal(1,"BOUNDARY_OUTSTANDING_DEBT");
 end
 initial begin repeat(2000)@(posedge clk);$fatal(1,"BOUNDARY_WATCHDOG");end
 task automatic reset_frame;
  @(negedge clk);rst_n=0;frame_available=0;start_valid=0;clear_valid=0;
  read_ready=0;response_valid=0;response_error=0;response_tag=Tag;
  stats_ready=0;replay_ready=0;bank_read_valid=0;bank_response_ready=0;
  frame_tag=Tag;frame_rows=2;cfg_tokens=1;cfg_strips=2;
  requests=0;responses=0;normal_accepts=0;
  repeat(3)@(negedge clk);rst_n=1;frame_available=1;
  @(negedge clk);start_valid=1;#1;if(!start_ready)$fatal(1,"BOUNDARY_START_READY");
  @(posedge clk);@(negedge clk);start_valid=0;
  frame_tag=~Tag;frame_rows=512;cfg_tokens=16;cfg_strips=32;
 endtask
 task automatic request_row(input logic[8:0] row);
  while(!read_valid)@(negedge clk);
  repeat(4)begin
   @(posedge clk);#1;
   if(!read_valid || read_tag!==Tag || read_row!==row || clear_ready || frame_fault)
    $fatal(1,"BOUNDARY_HELD_REQUEST row=%0d",row);
  end
  @(negedge clk);read_ready=1;@(posedge clk);@(negedge clk);read_ready=0;
 endtask
 task automatic normal_row(input bit replay,input logic[8:0] row,input logic[127:0] value);
  request_row(row);
  @(negedge clk);response_valid=1;response_error=0;response_tag=Tag;response_row=row;response_normalization=value;
  repeat(4)begin
   @(posedge clk);#1;
   if(frame_fault || response_ready || normalization_token!==0 || normalization_strip!==row ||
      (replay ? (!replay_valid || stats_valid || replay_data!==value || replay_last!==row[0]):
                (!stats_valid || replay_valid || stats_data!==value || stats_last!==row[0])))
    $fatal(1,"BOUNDARY_HELD_NORMALIZATION replay=%0d row=%0d",replay,row);
  end
  @(negedge clk);if(replay)replay_ready=1;else stats_ready=1;
  @(posedge clk);@(negedge clk);response_valid=0;stats_ready=0;replay_ready=0;
 endtask
 initial begin
  reset_frame();normal_row(0,0,Word0);request_row(1);
  @(negedge clk);response_valid=1;response_row=0;response_normalization=Word1;
  #1;if(!frame_fault || fault_code!==2 || stats_valid || replay_valid || !response_ready)
   $fatal(1,"BOUNDARY_WRONG_ROW_DELIVERED");
  @(posedge clk);@(negedge clk);response_valid=0;clear_valid=1;
  repeat(4)begin @(posedge clk);#1;
   if(!frame_fault || fault_code!==2 || clear_ready || start_ready || read_valid || stats_valid || replay_valid)
    $fatal(1,"BOUNDARY_FAULT_CLEARED");
  end
  if(requests!=2 || responses!=2 || normal_accepts!=1)$fatal(1,"BOUNDARY_WRONG_ROW_COUNTS");
  $display("LINK_BOUNDARY_WRONG_ROW_PASS requests=2 responses=2 accepted=1");
  reset_frame();normal_row(0,0,Word0);normal_row(0,1,Word1);
  normal_row(1,0,Word0);normal_row(1,1,Word1);
  if(!normalization_done || normal_accepts!=4)$fatal(1,"BOUNDARY_NORMALIZATION_INCOMPLETE");
  @(negedge clk);bank_read_valid=1;bank_read_row=1;
  #1;if(!bank_read_ready)$fatal(1,"BOUNDARY_BANK_NOT_READY");
  @(posedge clk);@(negedge clk);bank_read_valid=0;bank_read_row=0;
  request_row(1);
  @(negedge clk);response_valid=1;response_row=1;response_error=1;
  #1;if(!frame_fault || fault_code!==3 || !bank_response_valid || !bank_response_error ||
        bank_response_data!==0 || response_ready)$fatal(1,"BOUNDARY_ABORT_BEFORE_HANDSHAKE");
  repeat(4)begin @(posedge clk);#1;
   if(!frame_fault || fault_code!==3 || !bank_response_valid || !bank_response_error ||
      bank_response_data!==0 || response_ready || clear_ready || read_valid)
    $fatal(1,"BOUNDARY_ERROR_RESPONSE_DEBT_DROPPED");
  end
  @(negedge clk);bank_response_ready=1;@(posedge clk);@(negedge clk);response_valid=0;bank_response_ready=0;
  if(!frame_fault || fault_code!==3 || bank_response_valid || requests!=5 || responses!=5 || normal_accepts!=4)
   $fatal(1,"BOUNDARY_ERROR_DRAIN_COUNTS");
  $display("LINK_BOUNDARY_BANK_ABORT_PASS requests=5 responses=5 accepted=4");
  $display("REPLAY_LINK_BOUNDARY_PASS controls=2");$finish;
 end
endmodule
