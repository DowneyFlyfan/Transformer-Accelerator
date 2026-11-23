`timescale 1ns/1ps
module tri_oracle_external_residual_frame (
 input logic clk,rst_n,cfg_valid,
 output logic cfg_ready,
 input logic[31:0] cfg_tag,
 input logic[63:0] cfg_base,
 input logic[9:0] cfg_rows,
 input logic[4:0] cfg_tokens,
 input logic[8:0] cfg_strips,
 input logic abort_frame,
 input logic bypass_valid,
 output logic bypass_ready,
 input logic[31:0] bypass_tag,
 input logic[8:0] bypass_row,
 input logic[231:0] bypass_data,
 input logic normalization_valid,
 output logic normalization_ready,
 input logic[31:0] normalization_tag,
 input logic[8:0] normalization_row,
 input logic[127:0] normalization_data,
 input logic source_done_valid,source_done_error,
 output logic source_done_ready,
 input logic[31:0] source_done_tag,
 output logic captured_valid,captured_error,
 output logic[31:0] captured_tag,
 output logic[7:0] captured_code,
 input logic normalization_start_valid,
 output logic normalization_start_ready,normalization_done,frame_fault,
 output logic[7:0] fault_code,
 output logic[3:0] normalization_token,
 output logic[8:0] normalization_strip,
 input logic[3:0] consumer_token,
 output logic stats_valid,stats_last,replay_valid,replay_last,
 input logic stats_ready,replay_ready,
 output logic[127:0] stats_data,replay_data,
 input logic bank_read_valid,
 output logic bank_read_ready,
 input logic[8:0] bank_read_row,
 output logic bank_response_valid,bank_response_error,
 input logic bank_response_ready,
 output logic[231:0] bank_response_data,
 input logic release_valid,
 output logic release_ready,
 input logic[1:0] scalar_req_valid,
 output logic[1:0] scalar_req_ready,
 input logic[127:0] scalar_req_address,
 input logic[9:0] scalar_req_length,
 output logic[1:0] scalar_rsp_valid,scalar_rsp_last,scalar_rsp_error,
 input logic[1:0] scalar_rsp_ready,
 output logic[127:0] scalar_rsp_data,
 input logic scalar_write_req_valid,
 output logic scalar_write_req_ready,
 input logic[63:0] scalar_write_address,
 input logic[4:0] scalar_write_length,
 input logic scalar_write_data_valid,scalar_write_data_last,
 output logic scalar_write_data_ready,
 input logic[63:0] scalar_write_data,
 input logic[7:0] scalar_write_strobe,
 output logic scalar_write_rsp_valid,scalar_write_rsp_error,
 input logic scalar_write_rsp_ready,
 output logic mr_req_valid,
 input logic mr_req_ready,
 output logic[63:0] mr_address,
 output logic[4:0] mr_length,
 input logic mr_rsp_valid,mr_last,mr_error,
 output logic mr_rsp_ready,
 input logic[63:0] mr_data,
 output logic mw_req_valid,
 input logic mw_req_ready,
 output logic[63:0] mw_address,
 output logic[4:0] mw_length,
 output logic mw_data_valid,mw_last,
 input logic mw_data_ready,
 output logic[63:0] mw_data,
 output logic[7:0] mw_strobe,
 input logic mw_rsp_valid,mw_error,
 output logic mw_rsp_ready
);
 // The frame owner keeps the external region leased through release. Active
 // replay faults require a coupled consumer/reader reset; capture abort uses
 // the existing writer's abort protocol. No arithmetic is changed here.
 logic[9:0] rows_reg;
 logic[4:0] tokens_reg;
 logic[8:0] strips_reg;
 logic transport_release_valid,transport_release_ready,link_release_valid,link_release_ready;
 logic link_fault;
 logic[3:0] link_fault_code;
 logic read_valid,read_ready,response_valid,response_ready,response_error;
 logic[31:0] read_tag,response_tag;
 logic[8:0] read_row,response_row;
 logic[231:0] response_bypass;
 logic[127:0] response_normalization;
 logic write_valid,write_ready,write_rsp_valid,write_rsp_ready,write_rsp_error;
 logic[63:0] write_address;
 logic[511:0] write_data;
 logic read_packet_valid,read_packet_ready,read_packet_rsp_valid,read_packet_rsp_ready,read_packet_rsp_error;
 logic[63:0] read_packet_address;
 logic[511:0] read_packet_rsp_data;
 logic scalar_owner,scalar_owner_active,scalar_bus_req_valid,scalar_bus_req_ready;
 logic scalar_bus_rsp_valid,scalar_bus_rsp_ready,scalar_bus_rsp_last,scalar_bus_rsp_error;
 logic[63:0] scalar_bus_rsp_data;
 always_ff @(posedge clk or negedge rst_n)begin
  if(!rst_n)begin rows_reg<=0;tokens_reg<=0;strips_reg<=0;end
  else if(cfg_valid && cfg_ready)begin rows_reg<=cfg_rows;tokens_reg<=cfg_tokens;strips_reg<=cfg_strips;end
 end
 always_comb begin
  release_ready=transport_release_ready && (link_release_ready || (captured_valid && captured_error));
  transport_release_valid=release_valid && (link_release_ready || (captured_valid && captured_error));
  link_release_valid=release_valid && transport_release_ready && !captured_error;
  frame_fault=rst_n && ((captured_valid && captured_error) || link_fault);
  fault_code=captured_valid && captured_error ? captured_code:{4'd0,link_fault_code};
  scalar_bus_rsp_ready=scalar_owner_active && scalar_rsp_ready[scalar_owner];
  scalar_rsp_valid=0;
  if(scalar_owner_active)scalar_rsp_valid[scalar_owner]=scalar_bus_rsp_valid;
  scalar_rsp_last={2{scalar_bus_rsp_last}};scalar_rsp_error={2{scalar_bus_rsp_error}};
  scalar_rsp_data={2{scalar_bus_rsp_data}};
 end
 tri_oracle_residual_external_transport transport(
  .clk,.rst_n,.cfg_valid,.cfg_ready,.cfg_tag,.cfg_base,.cfg_rows,.abort_frame,
  .bypass_valid,.bypass_ready,.bypass_tag,.bypass_row,.bypass_data,
  .normalization_valid,.normalization_ready,.normalization_tag,.normalization_row,.normalization_data,
  .source_done_valid,.source_done_ready,.source_done_error,.source_done_tag,
  .captured_valid,.captured_error,.captured_tag,.captured_code,
  .release_valid(transport_release_valid),.release_ready(transport_release_ready),
  .read_valid,.read_ready,.read_tag,.read_row,.response_valid,.response_ready,.response_error,
  .response_tag,.response_row,.response_bypass,.response_normalization,
  .write_valid,.write_ready,.write_address,.write_data,.write_rsp_valid,.write_rsp_ready,.write_rsp_error,
  .read_packet_valid,.read_packet_ready,.read_packet_address,.read_packet_rsp_valid,.read_packet_rsp_ready,
  .read_packet_rsp_error,.read_packet_rsp_data
 );
 tri_oracle_residual_replay_link replay_link(
  .clk,.rst_n,.frame_available(captured_valid && !captured_error),
  .start_valid(normalization_start_valid),.start_ready(normalization_start_ready),
  .frame_tag(captured_tag),.frame_rows(rows_reg),.cfg_tokens(tokens_reg),.cfg_strips(strips_reg),
  .clear_valid(link_release_valid),.clear_ready(link_release_ready),
  .normalization_done,.frame_fault(link_fault),.fault_code(link_fault_code),
  .normalization_token,.normalization_strip,.consumer_token,
  .stats_valid,.stats_ready,.stats_last,.stats_data,.replay_valid,.replay_ready,.replay_last,.replay_data,
  .bank_read_valid,.bank_read_ready,.bank_read_row,.bank_response_valid,.bank_response_ready,.bank_response_error,.bank_response_data,
  .read_valid,.read_ready,.read_tag,.read_row,.response_valid,.response_ready,.response_error,
  .response_tag,.response_row,.response_bypass,.response_normalization
 );
 tri_oracle_scalar_request_owner read_owner(
  .clk,.rst_n,.client_valid(scalar_req_valid),.client_ready(scalar_req_ready),
  .request_valid(scalar_bus_req_valid),.request_ready(scalar_bus_req_ready),
  .terminal_transfer(scalar_bus_rsp_valid && scalar_bus_rsp_ready && scalar_bus_rsp_last),
  .owner(scalar_owner),.active(scalar_owner_active)
 );
 tri_oracle_external_read_mux read_mux(
  .clk,.rst_n,.scalar_req_valid(scalar_bus_req_valid),.scalar_req_ready(scalar_bus_req_ready),
  .scalar_req_address(scalar_req_address[scalar_owner*64+:64]),.scalar_req_length(scalar_req_length[scalar_owner*5+:5]),
  .scalar_rsp_valid(scalar_bus_rsp_valid),.scalar_rsp_ready(scalar_bus_rsp_ready),
  .scalar_rsp_last(scalar_bus_rsp_last),.scalar_rsp_error(scalar_bus_rsp_error),.scalar_rsp_data(scalar_bus_rsp_data),
  .vector_req_valid(read_packet_valid),.vector_req_ready(read_packet_ready),.vector_req_address(read_packet_address),
  .vector_rsp_valid(read_packet_rsp_valid),.vector_rsp_ready(read_packet_rsp_ready),
  .vector_rsp_error(read_packet_rsp_error),.vector_rsp_data(read_packet_rsp_data),
  .mem_req_valid(mr_req_valid),.mem_req_ready(mr_req_ready),.mem_req_address(mr_address),.mem_req_length(mr_length),
  .mem_rsp_valid(mr_rsp_valid),.mem_rsp_ready(mr_rsp_ready),.mem_rsp_last(mr_last),.mem_rsp_error(mr_error),.mem_rsp_data(mr_data)
 );
 tri_oracle_external_write_mux write_mux(
  .clk,.rst_n,.scalar_req_valid(scalar_write_req_valid),.scalar_req_ready(scalar_write_req_ready),
  .scalar_req_address(scalar_write_address),.scalar_req_length(scalar_write_length),
  .scalar_data_valid(scalar_write_data_valid),.scalar_data_ready(scalar_write_data_ready),.scalar_data_last(scalar_write_data_last),
  .scalar_data(scalar_write_data),.scalar_strobe(scalar_write_strobe),
  .scalar_rsp_valid(scalar_write_rsp_valid),.scalar_rsp_ready(scalar_write_rsp_ready),.scalar_rsp_error(scalar_write_rsp_error),
  .vector_req_valid(write_valid),.vector_req_ready(write_ready),.vector_req_address(write_address),.vector_req_data(write_data),
  .vector_rsp_valid(write_rsp_valid),.vector_rsp_ready(write_rsp_ready),.vector_rsp_error(write_rsp_error),
  .mem_req_valid(mw_req_valid),.mem_req_ready(mw_req_ready),.mem_req_address(mw_address),.mem_req_length(mw_length),
  .mem_data_valid(mw_data_valid),.mem_data_ready(mw_data_ready),.mem_data_last(mw_last),.mem_data(mw_data),.mem_strobe(mw_strobe),
  .mem_rsp_valid(mw_rsp_valid),.mem_rsp_ready(mw_rsp_ready),.mem_rsp_error(mw_error)
 );
endmodule
