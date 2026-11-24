`timescale 1ns/1ps
// Tagged, single-outstanding read sequencer. The owner keeps the memory frame
// leased until normal clear, or couples all consumers and the reader in reset
// after a fault. A bad bank response asserts abort before its acceptance edge.
module tri_oracle_residual_replay_link_wait_consumer (
 input logic clk,rst_n,frame_available,start_valid,
 output logic start_ready,
 input logic [31:0] frame_tag,
 input logic [9:0] frame_rows,
 input logic [4:0] cfg_tokens,
 input logic [8:0] cfg_strips,
 input logic clear_valid,
 output logic clear_ready,normalization_done,frame_fault,
 output logic [3:0] fault_code,normalization_token,
 output logic [8:0] normalization_strip,
 input logic [3:0] consumer_token,
 output logic stats_valid,stats_last,replay_valid,replay_last,
 input logic stats_ready,replay_ready,
 output logic [127:0] stats_data,replay_data,
 input logic bank_read_valid,
 output logic bank_read_ready,
 input logic [8:0] bank_read_row,
 output logic bank_response_valid,bank_response_error,
 input logic bank_response_ready,
 output logic [231:0] bank_response_data,
 output logic read_valid,
 input logic read_ready,
 output logic [31:0] read_tag,
 output logic [8:0] read_row,
 input logic response_valid,response_error,
 output logic response_ready,
 input logic [31:0] response_tag,
 input logic [8:0] response_row,
 input logic [231:0] response_bypass,
 input logic [127:0] response_normalization
);
 typedef enum logic [2:0] {Idle,Statistics,Replay,FinalReads,Fault,WaitConsumer} state_t;
 state_t state;
 logic [31:0] tag_reg;
 logic [4:0] tokens_reg;
 logic [8:0] strips_reg,strip_index,held_bank_row,pending_row,pending_strip;
 logic [3:0] token_index,pending_token,latched_fault_code,detected_fault_code;
 logic pending,pending_is_bank,bank_offer,fault_latched;
 logic bad_metadata,bad_consumer,bad_response,geometry_valid;
 logic [13:0] geometry_rows,row_offset;

 always_comb begin
  geometry_rows=14'(cfg_tokens)*14'(cfg_strips);
  geometry_valid=cfg_tokens>=1 && cfg_tokens<=16 && cfg_strips>=1 && cfg_strips<=256 &&
                 frame_rows>=2 && frame_rows<=512 && !frame_rows[0] && geometry_rows==14'(frame_rows);
  row_offset=14'(token_index)*14'(strips_reg)+14'(strip_index);
  bad_metadata=response_tag!==tag_reg || response_row!==pending_row;
  bad_consumer=!pending_is_bank && consumer_token!==pending_token;
  bad_response=response_error!==1'b0 || bad_metadata || bad_consumer;
  detected_fault_code=response_error!==1'b0 ? 4'd3:(bad_metadata ? 4'd2:4'd4);
  frame_fault=rst_n && (fault_latched || (pending && response_valid && bad_response));
  fault_code=fault_latched ? latched_fault_code:
             (pending && response_valid && bad_response ? detected_fault_code:4'd0);
  start_ready=rst_n && state==Idle && frame_available;
  clear_ready=rst_n && state==FinalReads && !pending && !bank_offer && !bank_read_valid;
  normalization_done=rst_n && state==FinalReads && !frame_fault;
  normalization_token=pending ? pending_token:token_index;
  normalization_strip=pending ? pending_strip:strip_index;

  // Once offered, the index and tag stay fixed until the accepted response.
  read_valid=rst_n && !pending && ((state==Statistics || state==Replay) ||
                                  (state==FinalReads && bank_offer));
  read_tag=tag_reg;
  read_row=state==FinalReads ? held_bank_row:9'(row_offset);
  stats_valid=rst_n && pending && !pending_is_bank && state==Statistics &&
              response_valid && !bad_response && !fault_latched;
  replay_valid=rst_n && pending && !pending_is_bank && state==Replay &&
               response_valid && !bad_response && !fault_latched;
  stats_last=pending_strip==strips_reg-1'b1;
  replay_last=stats_last;
  stats_data=stats_valid ? response_normalization:128'd0;
  replay_data=replay_valid ? response_normalization:128'd0;

  bank_read_ready=rst_n && state==FinalReads && !pending && !bank_offer && !clear_valid;
  // A fault does not discard an already accepted bank-response obligation.
  bank_response_valid=rst_n && pending && pending_is_bank && response_valid;
  bank_response_error=bank_response_valid && bad_response;
  bank_response_data=bank_response_valid && !bad_response ? response_bypass:232'd0;
  response_ready=0;
  if(rst_n && pending)begin
   if(pending_is_bank)response_ready=bank_response_ready;
   else if(bad_response || fault_latched)response_ready=1;
   else if(state==Statistics)response_ready=stats_ready;
   else if(state==Replay)response_ready=replay_ready;
  end
 end

 always_ff @(posedge clk or negedge rst_n)begin
  if(!rst_n)begin
   state<=Idle;tag_reg<=0;tokens_reg<=0;strips_reg<=0;strip_index<=0;token_index<=0;
   held_bank_row<=0;pending_row<=0;pending_strip<=0;pending_token<=0;
   pending<=0;pending_is_bank<=0;bank_offer<=0;fault_latched<=0;latched_fault_code<=0;
  end else begin
   if(start_valid && start_ready)begin
    tag_reg<=frame_tag;tokens_reg<=cfg_tokens;strips_reg<=cfg_strips;
    token_index<=0;strip_index<=0;
    if(geometry_valid)state<=Statistics;
    else begin state<=Fault;fault_latched<=1;latched_fault_code<=1;end
   end
   if(clear_valid && clear_ready)state<=Idle;
   // The consumer advances only after its final activation-write acknowledgment.
   if(state==WaitConsumer && consumer_token==token_index)state<=Statistics;
   if(bank_read_valid && bank_read_ready)begin
    held_bank_row<=bank_read_row;bank_offer<=1;
   end
   if(read_valid && read_ready)begin
    pending<=1;pending_is_bank<=state==FinalReads;pending_row<=read_row;
    pending_token<=token_index;pending_strip<=strip_index;bank_offer<=0;
   end
   if(pending && response_valid)begin
    if(bad_response)begin
     state<=Fault;fault_latched<=1;
     if(!fault_latched)latched_fault_code<=detected_fault_code;
    end
    if(response_ready)begin
     pending<=0;
     if(!pending_is_bank && !bad_response && !fault_latched)begin
      if(pending_strip==strips_reg-1'b1)begin
       strip_index<=0;
       if(state==Statistics)state<=Replay;
       else if({1'b0,pending_token}==tokens_reg-1'b1)state<=FinalReads;
       else begin token_index<=token_index+1'b1;state<=WaitConsumer;end
      end else strip_index<=strip_index+1'b1;
     end
    end
   end
  end
 end
endmodule
