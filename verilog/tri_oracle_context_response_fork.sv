`timescale 1ns/1ps
// Observe accepted words at the existing serialized command boundary. Opcode5
// retains three words: signed value exponent[169:162], capture[170], signed
// zero-context exponent[179:171]. Disable capture for other queries while the
// one-token buffer is occupied. Source fields stay stable until source_ready.
// Store each row once before exposing the held response to the host. No extra
// 2048-bit result register. Other operations/malformed descriptors pass through.
module tri_oracle_context_response_fork (
  input logic clk,rst_n,
  input logic command_valid,command_ready,
  input logic [2:0] command_opcode,
  input logic [31:0] command_tag,
  input logic payload_valid,payload_ready,
  input logic [63:0] payload_data,
  input logic payload_last,
  input logic source_valid,
  output logic source_ready,
  input logic source_error,
  input logic [2:0] source_opcode,
  input logic [31:0] source_tag,
  input logic [2047:0] source_values,
  output logic response_valid,
  input logic response_ready,
  output logic response_error,
  output logic [2:0] response_opcode,
  output logic [31:0] response_tag,
  output logic [2047:0] response_values,
  output logic cfg_valid,
  input logic cfg_ready,
  output logic [31:0] cfg_tag,
  output logic [10:0] cfg_query,
  output logic signed [8:0] cfg_zero_exponent,
  output logic row_valid,
  input logic row_ready,
  output logic row_error,
  output logic [10:0] row_query,
  output logic [4:0] row_head,
  output logic [2047:0] row_data,
  output logic signed [7:0] row_value_exponent,
  input logic context_done_accepted,
  output logic frame_open,projection_active
);
  logic pending_header,payload_active,capture_enabled,row_consumed;
  logic [1:0] payload_index;
  logic [2:0] pending_opcode;
  logic [31:0] pending_tag;
  logic [10:0] pending_query;
  logic [4:0] pending_head;
  logic signed [7:0] pending_value_exponent;
  logic signed [8:0] pending_zero_exponent;
  logic capture_response;

  assign capture_response=pending_header && pending_opcode==3'd5 && capture_enabled;
  assign cfg_valid=rst_n && source_valid && capture_response && !frame_open && !row_consumed;
  assign cfg_tag=pending_tag;
  assign cfg_query=pending_query;
  assign cfg_zero_exponent=pending_zero_exponent;
  assign row_valid=rst_n && source_valid && capture_response && frame_open && !row_consumed;
  assign row_query=pending_query;
  assign row_head=pending_head;
  assign row_value_exponent=pending_value_exponent;
  assign row_error=source_error || source_opcode!=pending_opcode || source_tag!=pending_tag;
  assign row_data=source_values;
  assign response_valid=rst_n && source_valid && (!capture_response || row_consumed);
  assign source_ready=rst_n && response_ready && (!capture_response || row_consumed);
  assign response_error=source_error;
  assign response_opcode=source_opcode;
  assign response_tag=source_tag;
  assign response_values=source_values;
  assign projection_active=rst_n && pending_header && pending_opcode==3'd1;

  always_ff @(posedge clk or negedge rst_n)begin
    if(!rst_n)begin
      pending_header<=0;payload_active<=0;capture_enabled<=0;row_consumed<=0;frame_open<=0;
      payload_index<=0;pending_opcode<=0;pending_tag<=0;pending_query<=0;pending_head<=0;
      pending_value_exponent<=0;pending_zero_exponent<=0;
    end else begin
      if(context_done_accepted)frame_open<=0;
      if(cfg_valid && cfg_ready)frame_open<=1;
      if(row_valid && row_ready)row_consumed<=1;
      if(command_valid && command_ready)begin
        pending_header<=1;pending_opcode<=command_opcode;pending_tag<=command_tag;
        payload_active<=1;payload_index<=0;capture_enabled<=0;row_consumed<=0;
      end
      if(payload_active && payload_valid && payload_ready)begin
        if(payload_index==0)begin pending_head<=payload_data[4:0];pending_query<=payload_data[15:5];end
        if(payload_index==2)begin
          pending_value_exponent<=payload_data[41:34];pending_zero_exponent<=payload_data[51:43];
        end
        if(payload_last)begin
          payload_active<=0;
          capture_enabled<=pending_opcode==3'd5 && payload_index==2 && payload_data[42];
        end else if(payload_index!=3)payload_index<=payload_index+1'b1;
      end
      if(source_valid && source_ready)begin pending_header<=0;capture_enabled<=0;row_consumed<=0;payload_active<=0;end
    end
  end
endmodule
