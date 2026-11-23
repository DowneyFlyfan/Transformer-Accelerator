`timescale 1ns/1ps
// Production memory boundary; the chip owner connects the existing vector bus
// muxes, and supplies the actual producer's frame terminal. No testbench array.
module tri_oracle_residual_external_transport (
  input logic clk,rst_n,
  input logic cfg_valid,
  output logic cfg_ready,
  input logic [31:0] cfg_tag,
  input logic [63:0] cfg_base,
  input logic [9:0] cfg_rows,
  input logic abort_frame,
  input logic bypass_valid,
  output logic bypass_ready,
  input logic [31:0] bypass_tag,
  input logic [8:0] bypass_row,
  input logic [231:0] bypass_data,
  input logic normalization_valid,
  output logic normalization_ready,
  input logic [31:0] normalization_tag,
  input logic [8:0] normalization_row,
  input logic [127:0] normalization_data,
  input logic source_done_valid,source_done_error,
  output logic source_done_ready,
  input logic [31:0] source_done_tag,
  output logic captured_valid,captured_error,
  output logic [31:0] captured_tag,
  output logic [7:0] captured_code,
  input logic release_valid,
  output logic release_ready,
  input logic read_valid,
  output logic read_ready,
  input logic [31:0] read_tag,
  input logic [8:0] read_row,
  output logic response_valid,response_error,
  input logic response_ready,
  output logic [31:0] response_tag,
  output logic [8:0] response_row,
  output logic [231:0] response_bypass,
  output logic [127:0] response_normalization,
  output logic write_valid,
  input logic write_ready,
  output logic [63:0] write_address,
  output logic [511:0] write_data,
  input logic write_rsp_valid,write_rsp_error,
  output logic write_rsp_ready,
  output logic read_packet_valid,
  input logic read_packet_ready,
  output logic [63:0] read_packet_address,
  input logic read_packet_rsp_valid,read_packet_rsp_error,
  output logic read_packet_rsp_ready,
  input logic [511:0] read_packet_rsp_data
);
  logic writer_cfg_ready,reader_busy,cfg_fire;
  logic [31:0] frame_tag;
  logic [63:0] frame_base;
  logic [9:0] frame_rows;
  always_comb begin
    cfg_ready=writer_cfg_ready && !reader_busy;
    cfg_fire=cfg_valid && cfg_ready;
    release_ready=rst_n && captured_valid && !reader_busy;
  end
  always_ff @(posedge clk)if(cfg_fire)begin
    frame_tag<=cfg_tag;frame_base<=cfg_base;frame_rows<=cfg_rows;
  end
  tri_oracle_residual_external_writer writer (
    .clk,.rst_n,.cfg_valid(cfg_valid && !reader_busy),.cfg_ready(writer_cfg_ready),
    .cfg_tag,.cfg_base,.cfg_rows,.abort_frame,
    .bypass_valid,.bypass_ready,.bypass_tag,.bypass_row,.bypass_data,
    .normalization_valid,.normalization_ready,.normalization_tag,.normalization_row,.normalization_data,
    .source_done_valid,.source_done_ready,.source_done_error,.source_done_tag,
    .write_valid,.write_ready,.write_address,.write_data,.write_rsp_valid,.write_rsp_ready,.write_rsp_error,
    .done_valid(captured_valid),.done_error(captured_error),.done_ready(release_valid && release_ready),
    .done_tag(captured_tag),.done_code(captured_code)
  );
  tri_oracle_residual_external_reader reader (
    .clk,.rst_n,.frame_available(captured_valid && !captured_error && !release_valid),
    .invalidate(cfg_fire),.frame_tag,.frame_base,.frame_rows,
    .req_valid(read_valid),.req_ready(read_ready),.req_tag(read_tag),.req_row(read_row),
    .rsp_valid(response_valid),.rsp_ready(response_ready),.rsp_error(response_error),
    .rsp_tag(response_tag),.rsp_row(response_row),.rsp_bypass(response_bypass),
    .rsp_normalization(response_normalization),.busy(reader_busy),
    .packet_req_valid(read_packet_valid),.packet_req_ready(read_packet_ready),
    .packet_req_address(read_packet_address),.packet_rsp_valid(read_packet_rsp_valid),
    .packet_rsp_ready(read_packet_rsp_ready),.packet_rsp_error(read_packet_rsp_error),
    .packet_rsp_data(read_packet_rsp_data)
  );
endmodule
