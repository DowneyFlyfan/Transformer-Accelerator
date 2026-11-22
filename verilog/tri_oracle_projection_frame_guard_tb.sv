`timescale 1ns/1ps
module tri_oracle_projection_frame_guard_tb;
 logic frame_valid,cfg_valid,cfg_ready,window_idle,outer_cancel,done_valid,done_error;
 logic admitted_valid,command_idle,projection_idle,frame_cancel;
 tri_oracle_projection_frame_guard dut(.*);
 initial begin
  frame_valid=0;cfg_valid=1;cfg_ready=1;window_idle=1;
  outer_cancel=0;done_valid=0;done_error=0;#1;
  if(admitted_valid || !command_idle || !projection_idle || frame_cancel)
   $fatal(1,"MASKED_OFFER_BLOCKS_FINISH");
  frame_valid=1;#1;
  if(!admitted_valid || command_idle || projection_idle)$fatal(1,"ELIGIBLE_OFFER_NOT_ACCOUNTED");
  cfg_valid=0;cfg_ready=0;#1;
  if(admitted_valid || command_idle || projection_idle)$fatal(1,"ACTIVE_COMMAND_NOT_ACCOUNTED");
  cfg_ready=1;window_idle=0;#1;
  if(!command_idle || projection_idle)$fatal(1,"TRANSPORT_DRAIN_NOT_ACCOUNTED");
  window_idle=1;done_error=1;#1;
  if(frame_cancel)$fatal(1,"STALE_ERROR_CANCELLED_FRAME");
  done_valid=1;#1;
  if(!frame_cancel)$fatal(1,"PROJECTION_FAILURE_NOT_FORWARDED");
  done_valid=0;done_error=0;outer_cancel=1;#1;
  if(!frame_cancel)$fatal(1,"OUTER_CANCEL_NOT_FORWARDED");
  $display("PROJECTION_FRAME_GUARD_PASS cases=7");$finish;
 end
endmodule
