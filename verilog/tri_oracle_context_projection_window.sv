`timescale 1ns/1ps
// Read the existing256-word context frame through the real projection bus.
// Wide requests and other pages retain the external path. No data buffer is
// added: the context controller holds each response until the bus accepts it.
// client_idle must reflect projection-command completion, not just bus idle.
module tri_oracle_context_projection_window #(
  parameter logic [51:0] ACTIVATION_PAGE=52'h10
) (
  input logic clk,rst_n,projection_enabled,client_idle,
  input logic req_valid,req_wide,
  output logic req_ready,
  input logic [63:0] req_address,
  input logic [5:0] req_length,
  output logic rsp_valid,rsp_last,rsp_error,
  input logic rsp_ready,
  output logic [511:0] rsp_data,
  output logic external_req_valid,
  input logic external_req_ready,
  output logic external_req_wide,
  output logic [63:0] external_req_address,
  output logic [5:0] external_req_length,
  input logic external_rsp_valid,external_rsp_last,external_rsp_error,
  output logic external_rsp_ready,
  input logic [511:0] external_rsp_data,
  output logic word_req_valid,
  input logic word_req_ready,
  output logic [9:0] word_req_word,
  input logic word_rsp_valid,word_rsp_error,
  output logic word_rsp_ready,
  input logic [63:0] word_rsp_data,
  input logic finish_valid,
  output logic finish_ready,memory_finish_valid,
  input logic memory_finish_ready,
  output logic idle
);
  typedef enum logic [1:0] {Idle,Issue,Receive,Bad} state_t;
  state_t state;
  logic bridge_idle,bridge_req_ready,allow_request,can_finish;
  logic local_req_valid,local_req_ready,local_rsp_valid,local_rsp_ready,local_rsp_last,local_rsp_error;
  logic [8:0] local_req_word,word;
  logic [4:0] local_req_length,remaining;
  logic [63:0] local_rsp_data;
  logic [9:0] request_end;
  logic invalid_request;

  assign can_finish=client_idle && bridge_idle && state==Idle;
  assign memory_finish_valid=rst_n && finish_valid && can_finish;
  assign finish_ready=rst_n && memory_finish_ready && can_finish;
  // An early finish must let the active command complete its remaining reads.
  // Once the command is idle, finish wins over a newly offered request.
  assign allow_request=!(finish_valid && client_idle);
  assign req_ready=bridge_req_ready && allow_request;
  assign idle=rst_n && bridge_idle && state==Idle;
  assign local_req_ready=rst_n && state==Idle;
  assign request_end={1'b0,local_req_word}+10'(local_req_length);
  assign invalid_request=local_req_length==0 || local_req_length>16 || request_end>256;
  assign word_req_valid=rst_n && state==Issue;
  assign word_req_word={1'b0,word};
  assign word_rsp_ready=rst_n && state==Receive && local_rsp_ready;
  assign local_rsp_valid=rst_n && (state==Bad || (state==Receive && word_rsp_valid));
  assign local_rsp_last=state==Bad || word_rsp_error || remaining==1;
  assign local_rsp_error=state==Bad || word_rsp_error;
  assign local_rsp_data=state==Receive && !word_rsp_error ? word_rsp_data : 64'b0;

  tri_oracle_projection_read_bridge #(.ACTIVATION_PAGE(ACTIVATION_PAGE)) bridge (
    .clk,.rst_n,.projection_enabled,
    .req_valid(req_valid && allow_request),.req_ready(bridge_req_ready),.req_wide,.req_address,.req_length,
    .rsp_valid,.rsp_ready,.rsp_last,.rsp_error,.rsp_data,
    .external_req_valid,.external_req_ready,.external_req_wide,.external_req_address,.external_req_length,
    .external_rsp_valid,.external_rsp_ready,.external_rsp_last,.external_rsp_error,.external_rsp_data,
    .local_req_valid,.local_req_ready,.local_req_word,.local_req_length,
    .local_rsp_valid,.local_rsp_ready,.local_rsp_last,.local_rsp_error,.local_rsp_data,.idle(bridge_idle)
  );
  always_ff @(posedge clk or negedge rst_n)begin
    if(!rst_n)begin state<=Idle;word<=0;remaining<=0;end
    else case(state)
      Idle:if(local_req_valid && local_req_ready)begin
        word<=local_req_word;remaining<=local_req_length;
        state<=invalid_request ? Bad : Issue;
      end
      Issue:if(word_req_ready)state<=Receive;
      Receive:if(word_rsp_valid && local_rsp_ready)begin
        if(word_rsp_error || remaining==1)state<=Idle;
        else begin word<=word+9'd1;remaining<=remaining-5'd1;state<=Issue;end
      end
      Bad:if(local_rsp_ready)state<=Idle;
      default:state<=Idle;
    endcase
  end
endmodule
