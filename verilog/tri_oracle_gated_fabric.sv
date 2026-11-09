`timescale 1ns / 1ps
// One shared five-cluster fabric executes both full gate/up projections.
module tri_oracle_gated_fabric (
    input logic clk,
    input logic rst_n,
    input logic in_valid,
    output logic in_ready,
    input logic in_last,
    input logic in_fallback,
    input logic [31:0] in_tag,
    input logic [2559:0] in_channels,
    input logic [7:0] in_count,
    input logic [63:0] in_activation_base,
    input logic [63:0] in_weight_base,
    input logic [63:0] in_up_weight_base,
    input logic [9:0] in_features,
    input logic [5:0] in_gate_shift,
    input logic [5:0] in_up_shift,
    output logic out_valid,
    input logic out_ready,
    output logic out_last,
    output logic out_fallback,
    output logic out_error,
    output logic [31:0] out_tag,
    output logic [7:0] out_count,
    output logic [2559:0] out_channels,
    output logic [5119:0] out_data,
    output logic req_valid,
    input logic req_ready,
    output logic [63:0] req_address,
    output logic [4:0] req_length,
    input logic rsp_valid,
    input logic rsp_last,
    input logic rsp_error,
    output logic rsp_ready,
    input logic [63:0] rsp_data
);
  logic projection_in_valid, projection_in_ready;
  logic projection_in_last, projection_in_fallback;
  logic [31:0] projection_in_tag;
  logic [2559:0] projection_in_channels;
  logic [7:0] projection_in_count;
  logic [63:0] projection_in_activation_base, projection_in_weight_base;
  logic [9:0] projection_in_features;
  logic projection_out_valid, projection_out_ready;
  logic projection_out_last, projection_out_fallback, projection_out_error;
  logic [31:0] projection_out_tag;
  logic [2559:0] projection_out_channels;
  logic [7:0] projection_out_count;
  logic [5119:0] projection_out_data;

  tri_oracle_fabric_gated_executor controller (.*);
  tri_oracle_fabric_projection fabric (
      .clk(clk),
      .rst_n(rst_n),
      .in_valid(projection_in_valid),
      .in_ready(projection_in_ready),
      .in_last(projection_in_last),
      .in_fallback(projection_in_fallback),
      .in_tag(projection_in_tag),
      .in_channels(projection_in_channels),
      .in_count(projection_in_count),
      .in_activation_base(projection_in_activation_base),
      .in_weight_base(projection_in_weight_base),
      .in_features(projection_in_features),
      .out_valid(projection_out_valid),
      .out_ready(projection_out_ready),
      .out_last(projection_out_last),
      .out_fallback(projection_out_fallback),
      .out_error(projection_out_error),
      .out_tag(projection_out_tag),
      .out_count(projection_out_count),
      .out_channels(projection_out_channels),
      .out_data(projection_out_data),
      .req_valid(req_valid),
      .req_ready(req_ready),
      .req_address(req_address),
      .req_length(req_length),
      .rsp_valid(rsp_valid),
      .rsp_last(rsp_last),
      .rsp_error(rsp_error),
      .rsp_ready(rsp_ready),
      .rsp_data(rsp_data)
  );
endmodule
