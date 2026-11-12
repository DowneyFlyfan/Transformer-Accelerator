`timescale 1ns/1ps

// Share one 512-bit lane between the weight loader and sign predictor.
// Keep the selected client through a stalled offer and the last accepted beat.
module tri_oracle_wide_read_arbiter (
    input logic clk, rst_n,
    input logic [1:0] client_req_valid,
    output logic [1:0] client_req_ready,
    input logic [1:0][63:0] client_req_address,
    input logic [1:0][5:0] client_req_length,
    output logic [1:0] client_rsp_valid,
    input logic [1:0] client_rsp_ready,
    output logic [1:0] client_rsp_last, client_rsp_error,
    output logic [1:0][511:0] client_rsp_data,
    output logic mem_req_valid,
    input logic mem_req_ready,
    output logic [63:0] mem_req_address,
    output logic [5:0] mem_req_length,
    input logic mem_rsp_valid,
    output logic mem_rsp_ready,
    input logic mem_rsp_last, mem_rsp_error,
    input logic [511:0] mem_rsp_data
);
    logic owner, active;

    tri_oracle_scalar_request_owner ownership (
        .clk, .rst_n, .client_valid(client_req_valid), .client_ready(client_req_ready),
        .request_valid(mem_req_valid), .request_ready(mem_req_ready),
        .terminal_transfer(mem_rsp_valid && mem_rsp_ready && mem_rsp_last), .owner, .active
    );

    assign mem_req_address = client_req_address[owner];
    assign mem_req_length = client_req_length[owner];
    assign mem_rsp_ready = active && client_rsp_ready[owner];
    assign client_rsp_valid = active && mem_rsp_valid ? (2'b01 << owner) : '0;
    assign client_rsp_last = {2{mem_rsp_last}};
    assign client_rsp_error = {2{mem_rsp_error}};
    assign client_rsp_data = {2{mem_rsp_data}};
endmodule
