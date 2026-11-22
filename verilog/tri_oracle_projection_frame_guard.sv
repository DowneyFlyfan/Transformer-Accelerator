`timescale 1ns/1ps
// New offers count only when admitted. A held but masked offer cannot block
// finish/abort. A projection error cancels the frame through the existing
// drain-before-reset protocol, even after its tensor completion is consumed.
module tri_oracle_projection_frame_guard (
 input logic frame_valid,cfg_valid,cfg_ready,window_idle,outer_cancel,done_valid,done_error,
 output logic admitted_valid,command_idle,projection_idle,frame_cancel
);
 always_comb begin
  admitted_valid=cfg_valid && frame_valid;
  command_idle=cfg_ready && !admitted_valid;
  projection_idle=command_idle && window_idle;
  frame_cancel=outer_cancel || (done_valid && done_error);
 end
endmodule
