`timescale 1ns/1ps
// One descriptor owns one tensor fabric through its terminal acknowledgement.
// Paired descriptors pass through nonlinear conversion; down descriptors use
// the same core memories and accumulator slots directly. Mode is captured.
module tri_oracle_batched_shared392 #(
  parameter bit AGGREGATOR_SIGN_BANK=0
) (
  input logic clk,rst_n,cfg_valid,cfg_paired,
  output logic cfg_ready,
  input logic [31:0] cfg_tag,
  input logic [4:0] cfg_tokens,
  input logic [9:0] cfg_feature_words,
  input logic [16:0] cfg_dense_rows,
  input logic [7:0] cfg_count,
  input logic [2559:0] cfg_channels,cfg_keep,
  input logic [63:0] cfg_activation_base,cfg_weight_base,cfg_up_weight_base,
  input logic [31:0] cfg_activation_stride,
  input logic [95:0] cfg_gate_shifts,cfg_up_shifts,cfg_down_shifts,
  output logic out_valid,
  input logic out_ready,
  output logic [31:0] out_tag,
  output logic [3:0] out_token,
  output logic out_last,
  output logic [7:0] out_count,
  output logic [2559:0] out_channels,
  output logic [5119:0] out_data,
  output logic [639:0] out_down_input,
  output logic done_valid,
  input logic done_ready,
  output logic done_error,
  output logic [31:0] done_tag,
  output logic req_valid,
  input logic req_ready,
  output logic [63:0] req_address,
  output logic [4:0] req_length,
  input logic rsp_valid,
  output logic rsp_ready,
  input logic rsp_last,rsp_error,
  input logic [63:0] rsp_data,
  input logic [2047:0] merge_sign_data,
  input logic [12:0] merge_sign_control,
  output logic [119:0] merge_sign_counts
);
  logic busy,paired,accept;
  logic raw_ready,raw_valid,raw_out_ready,raw_last,raw_done_valid,raw_done_ready,raw_done_error;
  logic [31:0] raw_tag,raw_done_tag;
  logic [3:0] raw_token;
  logic [7:0] raw_count;
  logic [2559:0] raw_channels;
  logic [5119:0] raw_data;
  logic gated_ready,gated_valid,gated_last,gated_done_valid,gated_done_error;
  logic gated_raw_ready,gated_raw_done_ready;
  logic [31:0] gated_tag,gated_done_tag;
  logic [3:0] gated_token;
  logic [6:0] gated_count;
  logic [1279:0] gated_channels,gated_values;
  logic [639:0] gated_down;

  assign cfg_ready=!busy && raw_ready && (!cfg_paired || gated_ready);
  assign accept=cfg_valid && cfg_ready;
  assign raw_out_ready=busy && (paired ? gated_raw_ready : out_ready);
  assign raw_done_ready=busy && (paired ? gated_raw_done_ready : done_ready);
  assign out_valid=busy && (paired ? gated_valid : raw_valid);
  assign out_tag=paired ? gated_tag : raw_tag;
  assign out_token=paired ? gated_token : raw_token;
  assign out_last=paired ? gated_last : raw_last;
  assign out_count=paired ? {1'b0,gated_count} : raw_count;
  assign out_channels=paired ? {1280'b0,gated_channels} : raw_channels;
  assign out_down_input=paired ? gated_down : 640'b0;
  assign done_valid=busy && (paired ? gated_done_valid : raw_done_valid);
  assign done_error=paired ? gated_done_error : raw_done_error;
  assign done_tag=paired ? gated_done_tag : raw_done_tag;
  always_comb begin
    out_data=raw_data;
    if(paired)begin
      out_data=0;
      for(int row=0;row<80;row++)out_data[row*32+:32]={{16{gated_values[row*16+15]}},gated_values[row*16+:16]};
    end
  end
  always_ff @(posedge clk or negedge rst_n)begin
    if(!rst_n)begin busy<=0;paired<=0;end
    else if(accept)begin busy<=1;paired<=cfg_paired;end
    else if(done_valid && done_ready)busy<=0;
  end

  tri_oracle_batched_tensor390 #(.AGGREGATOR_SIGN_BANK(AGGREGATOR_SIGN_BANK)) tensor (
    .merge_sign_data,.merge_sign_control,.merge_sign_counts,
    .clk(clk),.rst_n(rst_n),.cfg_valid(accept),.cfg_ready(raw_ready),.cfg_paired(cfg_paired),
    .cfg_tag(cfg_tag),.cfg_tokens(cfg_tokens),.cfg_feature_words(cfg_feature_words),
    .cfg_dense_rows(cfg_dense_rows),.cfg_count(cfg_count),.cfg_channels(cfg_channels),.cfg_keep(cfg_keep),
    .cfg_activation_base(cfg_activation_base),.cfg_weight_base(cfg_weight_base),.cfg_up_weight_base(cfg_up_weight_base),
    .cfg_activation_stride(cfg_activation_stride),.out_valid(raw_valid),.out_ready(raw_out_ready),
    .out_tag(raw_tag),.out_token(raw_token),.out_last(raw_last),.out_count(raw_count),.out_channels(raw_channels),.out_data(raw_data),
    .done_valid(raw_done_valid),.done_ready(raw_done_ready),.done_error(raw_done_error),.done_tag(raw_done_tag),
    .req_valid(req_valid),.req_ready(req_ready),.req_address(req_address),.req_length(req_length),
    .rsp_valid(rsp_valid),.rsp_ready(rsp_ready),.rsp_last(rsp_last),.rsp_error(rsp_error),.rsp_data(rsp_data));
  tri_oracle_batched_nonlinear391 nonlinear (
    .clk(clk),.rst_n(rst_n),.cfg_valid(accept && cfg_paired),.cfg_ready(gated_ready),
    .cfg_tag(cfg_tag),.cfg_tokens(cfg_tokens),.cfg_count(cfg_count[6:0]),.cfg_channels(cfg_channels[1279:0]),
    .cfg_gate_shifts(cfg_gate_shifts),.cfg_up_shifts(cfg_up_shifts),.cfg_down_shifts(cfg_down_shifts),
    .out_valid(gated_valid),.out_ready(busy && paired && out_ready),.out_tag(gated_tag),.out_token(gated_token),
    .out_last(gated_last),.out_count(gated_count),.out_channels(gated_channels),.out_gated(gated_values),.out_down_input(gated_down),
    .done_valid(gated_done_valid),.done_ready(busy && paired && done_ready),.done_error(gated_done_error),.done_tag(gated_done_tag),
    .projection_ready(raw_ready),.projection_valid(busy && paired && raw_valid),.projection_last(raw_last),
    .projection_tag(raw_tag),.projection_done_tag(raw_done_tag),.projection_token(raw_token),
    .projection_count(raw_count[6:0]),.projection_channels(raw_channels[1279:0]),.projection_data(raw_data),
    .projection_done_valid(busy && paired && raw_done_valid),.projection_done_error(raw_done_error),
    .projection_out_ready(gated_raw_ready),.projection_done_ready(gated_raw_done_ready));
endmodule
