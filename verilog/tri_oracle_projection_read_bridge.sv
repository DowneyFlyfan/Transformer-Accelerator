`timescale 1ns/1ps

// Serve narrow reads within the aligned 4 KiB activation window when enabled.
// Keep the selected source through the accepted terminal beat of each burst.
module tri_oracle_projection_read_bridge #(
    parameter logic [51:0] ACTIVATION_PAGE = 52'h10
) (
    input logic clk, rst_n, projection_enabled,
    input logic req_valid, req_wide,
    output logic req_ready,
    input logic [63:0] req_address,
    input logic [5:0] req_length,
    output logic rsp_valid, rsp_last, rsp_error,
    input logic rsp_ready,
    output logic [511:0] rsp_data,
    output logic external_req_valid,
    input logic external_req_ready,
    output logic external_req_wide,
    output logic [63:0] external_req_address,
    output logic [5:0] external_req_length,
    input logic external_rsp_valid, external_rsp_last, external_rsp_error,
    output logic external_rsp_ready,
    input logic [511:0] external_rsp_data,
    output logic local_req_valid,
    input logic local_req_ready,
    output logic [8:0] local_req_word,
    output logic [4:0] local_req_length,
    input logic local_rsp_valid, local_rsp_last, local_rsp_error,
    output logic local_rsp_ready,
    input logic [63:0] local_rsp_data,
    output logic idle
);
    typedef enum logic [1:0] {Idle, External, Local} owner_t;
    owner_t owner;
    logic local_address;
    assign idle = owner == Idle;
    assign local_address = projection_enabled && !req_wide && req_address[63:12] == ACTIVATION_PAGE;
    assign local_req_valid = rst_n && idle && req_valid && local_address;
    assign external_req_valid = rst_n && idle && req_valid && !local_address;
    assign req_ready = rst_n && idle && (local_address ? local_req_ready : external_req_ready);
    assign local_req_word = req_address[11:3];
    // The bank checks length, including zero. Force the same error response
    // when low address bits or the upper length bit would otherwise be lost.
    assign local_req_length = req_address[2:0] != 0 || req_length[5] ? 5'd0 : req_length[4:0];
    assign external_req_wide = req_wide;
    assign external_req_address = req_address;
    assign external_req_length = req_length;

    assign external_rsp_ready = rst_n && owner == External && rsp_ready;
    assign local_rsp_ready = rst_n && owner == Local && rsp_ready;
    assign rsp_valid = rst_n && (owner == Local ? local_rsp_valid : owner == External && external_rsp_valid);
    assign rsp_last = owner == Local ? local_rsp_last : external_rsp_last;
    assign rsp_error = owner == Local ? local_rsp_error : external_rsp_error;
    assign rsp_data = owner == Local ? {448'b0, local_rsp_data} : external_rsp_data;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) owner <= Idle;
        else if (idle && req_valid && req_ready) owner <= local_address ? Local : External;
        else if (rsp_valid && rsp_ready && rsp_last) owner <= Idle;
    end
endmodule
