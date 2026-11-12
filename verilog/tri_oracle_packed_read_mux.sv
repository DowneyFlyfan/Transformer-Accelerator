`timescale 1ns/1ps

// One external request at a time. A narrow response uses bits [63:0] and
// advances by eight bytes. A wide response uses all lanes and advances by
// 64 bytes. The selected client checks the burst protocol and drains errors.
module tri_oracle_packed_read_mux (
  input  logic clk, rst_n,

  input  logic narrow_req_valid,
  output logic narrow_req_ready,
  input  logic [63:0] narrow_req_address,
  input  logic [4:0] narrow_req_length,
  output logic narrow_rsp_valid,
  input  logic narrow_rsp_ready,
  output logic narrow_rsp_last, narrow_rsp_error,
  output logic [63:0] narrow_rsp_data,

  input  logic wide_req_valid,
  output logic wide_req_ready,
  input  logic [63:0] wide_req_address,
  input  logic [5:0] wide_req_length,
  output logic wide_rsp_valid,
  input  logic wide_rsp_ready,
  output logic wide_rsp_last, wide_rsp_error,
  output logic [511:0] wide_rsp_data,

  output logic mem_req_valid,
  input  logic mem_req_ready,
  output logic mem_req_wide,
  output logic [63:0] mem_req_address,
  output logic [5:0] mem_req_length,
  input  logic mem_rsp_valid,
  output logic mem_rsp_ready,
  input  logic mem_rsp_last, mem_rsp_error,
  input  logic [511:0] mem_rsp_data
);
  logic active, owner;

  tri_oracle_scalar_request_owner reads (
    .clk, .rst_n,
    .client_valid({wide_req_valid, narrow_req_valid}),
    .client_ready({wide_req_ready, narrow_req_ready}),
    .request_valid(mem_req_valid), .request_ready(mem_req_ready),
    .owner, .active,
    .terminal_transfer(mem_rsp_valid && mem_rsp_ready && mem_rsp_last)
  );

  assign mem_req_wide = owner;
  assign mem_req_address = owner ? wide_req_address : narrow_req_address;
  assign mem_req_length = owner ? wide_req_length : {1'b0, narrow_req_length};
  assign mem_rsp_ready = active && (owner ? wide_rsp_ready : narrow_rsp_ready);
  assign narrow_rsp_valid = active && !owner && mem_rsp_valid;
  assign wide_rsp_valid = active && owner && mem_rsp_valid;
  assign {narrow_rsp_last, narrow_rsp_error, narrow_rsp_data} =
      {mem_rsp_last, mem_rsp_error, mem_rsp_data[63:0]};
  assign {wide_rsp_last, wide_rsp_error, wide_rsp_data} = {mem_rsp_last, mem_rsp_error, mem_rsp_data};
endmodule
