`timescale 1ns/1ps

// One accepted frame owns its scalar/channel mode through residual and scale
// drainage. Changing future configuration offers cannot redirect a response.
// Reset must also reset the outstanding read transactions in both peers.
module tri_oracle_selectable_bank_writeback (
  input logic clk, rst_n, lease_granted,
  input logic frame_cfg_valid, frame_abort, frame_channel_scales,
  input logic [9:0] frame_down_shifts,
  input logic [63:0] frame_scale_base,
  output logic frame_cfg_ready, frame_active,
  input logic in_valid,
  output logic in_ready, packet_error,
  input logic [31:0] in_tag,
  input logic [3:0] in_token,
  input logic [15:0] in_start,
  input logic [7:0] in_count,
  input logic in_last,
  input logic [5119:0] in_data,
  output logic bank_read_valid,
  input logic bank_read_ready,
  output logic [8:0] bank_read_row,
  input logic bank_response_valid,
  output logic bank_response_ready,
  input logic [231:0] bank_response_data,
  output logic req_valid,
  input logic req_ready,
  output logic [63:0] req_address,
  output logic [4:0] req_length,
  input logic rsp_valid,
  output logic rsp_ready,
  input logic rsp_last, rsp_error,
  input logic [63:0] rsp_data,
  output logic out_valid,
  input logic out_ready,
  output logic [31:0] out_tag,
  output logic [3:0] out_token,
  output logic [15:0] out_start,
  output logic [3:0] out_count,
  output logic out_last,
  output logic [127:0] out_data
);
  logic channel_mode, accept_frame;
  logic [1:0] writer_ready, writer_active, writer_in_ready, writer_error;
  logic [1:0] writer_bank_valid, writer_bank_response_ready;
  logic [1:0][8:0] writer_bank_row;
  logic [1:0] writer_out_valid, writer_out_last;
  logic [1:0][31:0] writer_out_tag;
  logic [1:0][3:0] writer_out_token, writer_out_count;
  logic [1:0][15:0] writer_out_start;
  logic [1:0][127:0] writer_out_data;
  logic channel_req_valid, channel_rsp_ready;
  logic [63:0] channel_req_address;
  logic [4:0] channel_req_length;

  assign frame_active=|writer_active;
  assign frame_cfg_ready=!frame_active && !bank_response_valid && writer_ready[frame_channel_scales];
  assign accept_frame=frame_cfg_valid && frame_cfg_ready;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) channel_mode<=0;
    else if (accept_frame) channel_mode<=frame_channel_scales;
  end

  assign in_ready=writer_in_ready[channel_mode];
  assign packet_error=writer_error[channel_mode];
  assign bank_read_valid=writer_bank_valid[channel_mode];
  assign bank_read_row=writer_bank_row[channel_mode];
  assign bank_response_ready=writer_bank_response_ready[channel_mode];
  assign out_valid=writer_out_valid[channel_mode];
  assign out_tag=writer_out_tag[channel_mode];
  assign out_token=writer_out_token[channel_mode];
  assign out_start=writer_out_start[channel_mode];
  assign out_count=writer_out_count[channel_mode];
  assign out_last=writer_out_last[channel_mode];
  assign out_data=writer_out_data[channel_mode];
  assign req_valid=channel_mode && channel_req_valid;
  assign req_address=channel_mode ? channel_req_address : 64'd0;
  assign req_length=channel_mode ? channel_req_length : 5'd0;
  assign rsp_ready=channel_mode && channel_rsp_ready;

  tri_oracle_decoder_bank_writeback scalar_writer (
    .clk, .rst_n, .lease_granted, .frame_abort, .frame_down_shifts,
    .frame_cfg_valid(accept_frame && !frame_channel_scales),
    .frame_cfg_ready(writer_ready[0]), .frame_active(writer_active[0]),
    .in_valid(in_valid && !channel_mode), .in_ready(writer_in_ready[0]), .packet_error(writer_error[0]),
    .in_tag, .in_token, .in_start, .in_count, .in_last, .in_data,
    .bank_read_valid(writer_bank_valid[0]), .bank_read_ready(bank_read_ready && !channel_mode),
    .bank_read_row(writer_bank_row[0]), .bank_response_valid(bank_response_valid && !channel_mode),
    .bank_response_ready(writer_bank_response_ready[0]), .bank_response_data,
    .out_valid(writer_out_valid[0]), .out_ready(out_ready && !channel_mode),
    .out_tag(writer_out_tag[0]), .out_token(writer_out_token[0]), .out_start(writer_out_start[0]),
    .out_count(writer_out_count[0]), .out_last(writer_out_last[0]), .out_data(writer_out_data[0])
  );

  tri_oracle_decoder_channel_writeback channel_writer (
    .clk, .rst_n, .lease_granted, .frame_abort, .frame_down_shifts, .frame_scale_base,
    .frame_cfg_valid(accept_frame && frame_channel_scales),
    .frame_cfg_ready(writer_ready[1]), .frame_active(writer_active[1]),
    .in_valid(in_valid && channel_mode), .in_ready(writer_in_ready[1]), .packet_error(writer_error[1]),
    .in_tag, .in_token, .in_start, .in_count, .in_last, .in_data,
    .bank_read_valid(writer_bank_valid[1]), .bank_read_ready(bank_read_ready && channel_mode),
    .bank_read_row(writer_bank_row[1]), .bank_response_valid(bank_response_valid && channel_mode),
    .bank_response_ready(writer_bank_response_ready[1]), .bank_response_data,
    .req_valid(channel_req_valid), .req_ready(req_ready && channel_mode),
    .req_address(channel_req_address), .req_length(channel_req_length),
    .rsp_valid(rsp_valid && channel_mode), .rsp_ready(channel_rsp_ready), .rsp_last, .rsp_error, .rsp_data,
    .out_valid(writer_out_valid[1]), .out_ready(out_ready && channel_mode),
    .out_tag(writer_out_tag[1]), .out_token(writer_out_token[1]), .out_start(writer_out_start[1]),
    .out_count(writer_out_count[1]), .out_last(writer_out_last[1]), .out_data(writer_out_data[1])
  );
endmodule
