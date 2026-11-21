`timescale 1ns/1ps
// Coherent context status and memory release over the existing16-bit host link.
// Reply: A687,status low/high,tag low/high,action(last). Only one request queues.
module tri_oracle_host_context_link (
  input logic clk,rst_n,control_valid,control_finish,
  output logic control_ready,
  input logic context_valid,lease_active,metadata_needs_rebuild,
  input logic [31:0] context_tag,
  input logic [10:0] context_query,
  input logic signed [8:0] context_exponent,
  output logic finish_valid,done_ready,
  input logic finish_ready,done_valid,done_error,
  input logic source_valid,source_last,
  input logic [15:0] source_data,
  output logic source_ready,
  input logic tx_ready,
  output logic tx_valid,tx_last,
  output logic [15:0] tx_data
);
  typedef enum logic [1:0] {Idle,Finish,AwaitDone,Reply} state_t;
  state_t state;
  logic source_in_progress,send_reply,action;
  logic [2:0] word_index;
  logic [27:0] snapshot;
  logic [31:0] saved_tag;
  function automatic logic [27:0] status_word(input logic request_error,finish_action);
    return {1'b0,finish_action,request_error,done_error,done_valid,
            metadata_needs_rebuild,lease_active,context_valid,context_query,context_exponent};
  endfunction
  assign control_ready=rst_n && state==Idle;
  assign finish_valid=rst_n && state==Finish && !done_valid;
  assign done_ready=rst_n && state==AwaitDone;
  assign send_reply=state==Reply && !source_in_progress;
  assign source_ready=rst_n && !send_reply && tx_ready;
  assign tx_valid=rst_n && (send_reply || source_valid);
  assign tx_last=tx_valid && (send_reply ? word_index==5 : source_last);
  always_comb begin
    tx_data=source_data;
    if(send_reply)case(word_index)
      0:tx_data=16'ha687;
      1:tx_data=snapshot[15:0];
      2:tx_data={4'b0,snapshot[27:16]};
      3:tx_data=saved_tag[15:0];
      4:tx_data=saved_tag[31:16];
      default:tx_data={15'b0,action};
    endcase
  end
  always_ff @(posedge clk or negedge rst_n)begin
    if(!rst_n)begin
      state<=Idle;source_in_progress<=0;word_index<=0;action<=0;
      snapshot<=0;saved_tag<=0;
    end else begin
      // A source's first offered word owns its packet even when it is stalled.
      if(!send_reply && source_valid)source_in_progress<=!(tx_ready && source_last);
      case(state)
        Idle:if(control_valid)begin
          action<=control_finish;word_index<=0;
          if(!control_finish)begin snapshot<=status_word(0,0);saved_tag<=context_tag;state<=Reply;end
          else if(done_valid)state<=AwaitDone;
          else if(context_valid)state<=Finish;
          else begin snapshot<=status_word(1,1);saved_tag<=context_tag;state<=Reply;end
        end
        Finish:begin
          if(done_valid || finish_ready)state<=AwaitDone;
        end
        AwaitDone:if(done_valid)begin
          snapshot<=status_word(0,1);saved_tag<=context_tag;state<=Reply;
        end
        Reply:if(send_reply && tx_ready)begin
          if(word_index==5)begin state<=Idle;word_index<=0;end
          else word_index<=word_index+3'd1;
        end
        default:state<=Idle;
      endcase
    end
  end
endmodule
