`timescale 1ns/1ps
// Atomic full32-head admission and commit, without a payload buffer.
// Gate NEW projection commands with frame_valid. Keep existing projection
// traffic attached using context_route_enable until projection_idle confirms
// command AND transport drain. collector_rst_n resets both collector/window.
// A failed transaction requires global reset after failed completion; the
// broker is cancelled/drained before the collector receives its local reset.
module tri_oracle_attention_context_commit (
 input logic clk,rst_n,cfg_valid,
 output logic cfg_ready,
 input logic [31:0] cfg_heads,cfg_tag,
 input logic [15:0] cfg_query,cfg_epoch,
 input logic cancel,
 output logic broker_cfg_valid,
 input logic broker_cfg_ready,
 output logic collector_cfg_valid,
 input logic collector_cfg_ready,
 input logic broker_row_valid,
 output logic broker_row_ready,
 input logic broker_all_collected,
 input logic [4:0] broker_row_head,
 input logic [15:0] broker_row_query,broker_row_epoch,
 input logic [31:0] broker_row_tag,
 output logic collector_row_valid,
 input logic collector_row_ready,
 input logic broker_done_valid,
 output logic broker_done_ready,
 input logic broker_done_error,broker_reset_required,
 output logic broker_cancel,
 input logic collector_context_valid,collector_done_valid,collector_done_error,
 output logic collector_done_ready,collector_rst_n,
 input logic projection_idle,
 output logic frame_valid,context_route_enable,
 input logic finish_valid,
 output logic finish_ready,collector_finish_valid,
 input logic collector_finish_ready,
 output logic done_valid,
 input logic done_ready,
 output logic done_error,reset_required,busy,
 output logic [7:0] error_code
);
 typedef enum logic[2:0] {Idle,Receive,Ready,Release,Done,Abort,ResetCollector,Failed} state_t;
 state_t state;
 logic [15:0] query,epoch;
 logic [31:0] tag,seen;
 logic broker_finished,committed;
 logic cfg_good,bad_row,fault;
 logic [7:0] fault_code;
 logic [31:0] accepted_heads;

 always_comb begin
  cfg_good=cfg_heads==32'hffffffff && cfg_query<2048;
  cfg_ready=rst_n && state==Idle && !cancel && broker_cfg_ready && collector_cfg_ready;
  broker_cfg_valid=cfg_valid && cfg_ready && cfg_good;
  collector_cfg_valid=broker_cfg_valid;
  // The broker releases each archive after its row is accepted. The first
  // accepted row is a retained witness that all heads were archived together.
  bad_row=broker_row_valid && ((seen==0 && !broker_all_collected) || broker_row_query!=query ||
   broker_row_epoch!=epoch || broker_row_tag!=tag || seen[broker_row_head]);
  fault=0;fault_code=0;
  if(state==Receive || state==Ready || state==Release)begin
   if(cancel)begin fault=1;fault_code=8'h02;end
   else if(broker_reset_required || (broker_done_valid && broker_done_error))begin fault=1;fault_code=8'h05;end
   else if(collector_done_error || (state==Receive && collector_done_valid))begin fault=1;fault_code=8'h06;end
   else if(state==Receive && bad_row)begin fault=1;fault_code=8'h03;end
   else if(state==Ready && !collector_context_valid)begin fault=1;fault_code=8'h06;end
  end
  collector_row_valid=rst_n && state==Receive && broker_row_valid && !fault && !broker_finished;
  broker_row_ready=collector_row_valid && collector_row_ready;
  accepted_heads=seen;
  if(collector_row_valid && collector_row_ready)accepted_heads[broker_row_head]=1;
  broker_done_ready=rst_n && (state==Receive || state==Abort) && !broker_finished;
  // Broker row-valid itself depends on cancel; do not feed a row-dependent
  // combinational fault back into that input. Accepted traffic still drains.
  broker_cancel=rst_n && !broker_finished && state==Abort;
  collector_done_ready=rst_n && state==Release;
  collector_rst_n=rst_n && state!=ResetCollector && state!=Failed;
  frame_valid=rst_n && state==Ready && !fault && !finish_valid;
  context_route_enable=rst_n && committed && collector_context_valid &&
   (state==Ready || state==Release || state==Abort);
  collector_finish_valid=rst_n && state==Ready && !fault && projection_idle && finish_valid;
  finish_ready=rst_n && state==Ready && !fault && projection_idle && collector_finish_ready;
  done_valid=rst_n && (state==Done || state==Failed);
  done_error=state==Failed;
  reset_required=state==Failed;
  busy=rst_n && state!=Idle;
 end

 always_ff @(posedge clk or negedge rst_n)begin
  if(!rst_n)begin
   state<=Idle;query<=0;epoch<=0;tag<=0;seen<=0;
   broker_finished<=0;committed<=0;error_code<=0;
  end else begin
   if(broker_done_valid && broker_done_ready)broker_finished<=1;
   if(collector_row_valid && collector_row_ready)seen<=accepted_heads;
   case(state)
    Idle:if(cfg_valid && cfg_ready)begin
     query<=cfg_query;epoch<=cfg_epoch;tag<=cfg_tag;seen<=0;broker_finished<=0;committed<=0;error_code<=0;
     if(cfg_good)state<=Receive;
     else begin broker_finished<=1;error_code<=8'h01;state<=Abort;end
    end
    Receive:begin
     if(fault)begin error_code<=fault_code;state<=Abort;end
     else if(broker_done_valid && broker_done_ready && accepted_heads!=32'hffffffff)begin
      error_code<=8'h04;state<=Abort;
     end else if(accepted_heads==32'hffffffff && collector_context_valid &&
                 (broker_finished || (broker_done_valid && broker_done_ready)))begin
      committed<=1;state<=Ready;
     end
    end
    Ready:begin
     if(fault)begin error_code<=fault_code;state<=Abort;end
     else if(finish_valid && finish_ready)state<=Release;
    end
    Release:begin
     if(fault)begin error_code<=fault_code;state<=Abort;end
     else if(collector_done_valid && collector_done_ready)state<=Done;
    end
    Done:if(done_ready)state<=Idle;
    Abort:if((broker_finished || (broker_done_valid && broker_done_ready)) && projection_idle)state<=ResetCollector;
    ResetCollector:state<=Failed;
    Failed:begin end
    default:begin error_code<=8'hff;state<=Abort;end
   endcase
  end
 end
endmodule
