`timescale 1ns/1ps
// Prepared normalized-strip prediction feeds exactly one numeric compute frame.
module tri_oracle_predicted_feedforward_frame (
    input logic clk,rst_n,cfg_valid,
    output logic cfg_ready,
    input logic [31:0] cfg_tag,
    input logic [63:0] cfg_activation_base,cfg_weight_base,cfg_up_weight_base,cfg_down_weight_base,
    input logic [9:0] cfg_features,
    input logic [16:0] cfg_dense_features,
    input logic [15:0] cfg_output_count,
    input logic [5:0] cfg_gate_shift,cfg_up_shift,cfg_down_shift,
    input logic in_valid,in_last,in_group_last,
    input logic [10:0] in_group,
    input logic [127:0] norm_activations,
    input logic [255:0] gate_weight_signs,up_weight_signs,
    output logic in_ready,
    output logic out_valid,
    input logic out_ready,
    output logic out_last,out_error,out_fallback,
    output logic [31:0] out_tag,
    output logic [15:0] out_start,
    output logic [7:0] out_count,
    output logic [5119:0] out_data,
    output logic req_valid,
    input logic req_ready,
    output logic [63:0] req_address,
    output logic [4:0] req_length,
    input logic rsp_valid,rsp_last,rsp_error,
    output logic rsp_ready,
    input logic [63:0] rsp_data
);

  logic prediction_rst_n,prediction_cfg_ready,numeric_cfg_ready,joint_config;
  logic prediction_in_ready,packet_valid,packet_ready,numeric_packet_ready;
  logic packet_last,packet_fallback,packet_error;
  logic [31:0] packet_tag,frame_tag;
  logic [7:0] packet_count;
  logic [2559:0] packet_channels;
  logic [7:0] numeric_count;
  always_comb begin
    cfg_ready=prediction_rst_n && prediction_cfg_ready && numeric_cfg_ready;
    joint_config=cfg_valid && cfg_ready;
    in_ready=prediction_in_ready && !out_error;
    packet_ready=numeric_packet_ready && !out_error;
    numeric_count=packet_error || packet_tag!=frame_tag ? 8'd161 : packet_count;
  end
  // Only the memory-free prediction block is reset on a numeric error.
  // Prediction errors become invalid packets accepted at the numeric idle
  // packet boundary, after outstanding memory traffic has completed.
  always_ff @(posedge clk or negedge rst_n) begin
    if(!rst_n) begin prediction_rst_n<=0;frame_tag<=0;end
    else begin
      prediction_rst_n<=!(out_valid && out_error);
      if(joint_config) frame_tag<=cfg_tag;
    end
  end
  tri_oracle_prediction_packet_stream prediction (
      .clk(clk),.rst_n(prediction_rst_n),.cfg_valid(joint_config),.cfg_ready(prediction_cfg_ready),
      .cfg_tag(cfg_tag),.cfg_features(cfg_features),.cfg_dense_rows(cfg_dense_features),
      .in_valid(in_valid && !out_error),.in_last(in_last),.in_group_last(in_group_last),.in_group(in_group),
      .norm_activations(norm_activations),.gate_weight_signs(gate_weight_signs),.up_weight_signs(up_weight_signs),
      .in_ready(prediction_in_ready),.out_valid(packet_valid),.out_ready(packet_ready),
      .out_last(packet_last),.out_fallback(packet_fallback),.out_error(packet_error),
      .out_tag(packet_tag),.out_count(packet_count),.out_channels(packet_channels)
  );
  tri_oracle_feedforward_frame numeric (
      .clk(clk),.rst_n(rst_n),.cfg_valid(joint_config),.cfg_ready(numeric_cfg_ready),
      .cfg_tag(cfg_tag),.cfg_activation_base(cfg_activation_base),.cfg_weight_base(cfg_weight_base),
      .cfg_up_weight_base(cfg_up_weight_base),.cfg_down_weight_base(cfg_down_weight_base),
      .cfg_features(cfg_features),.cfg_dense_features(cfg_dense_features),.cfg_output_count(cfg_output_count),
      .cfg_gate_shift(cfg_gate_shift),.cfg_up_shift(cfg_up_shift),.cfg_down_shift(cfg_down_shift),
      .in_valid(packet_valid && !out_error),.in_ready(numeric_packet_ready),.in_last(packet_last),
      .in_fallback(packet_fallback),.in_count(numeric_count),.in_channels(packet_channels),
      .out_valid(out_valid),.out_ready(out_ready),.out_last(out_last),.out_error(out_error),
      .out_fallback(out_fallback),.out_tag(out_tag),.out_start(out_start),.out_count(out_count),.out_data(out_data),
      .req_valid(req_valid),.req_ready(req_ready),.req_address(req_address),.req_length(req_length),
      .rsp_valid(rsp_valid),.rsp_last(rsp_last),.rsp_error(rsp_error),.rsp_ready(rsp_ready),.rsp_data(rsp_data)
  );
endmodule
