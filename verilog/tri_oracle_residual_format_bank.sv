`timescale 1ns/1ps

// Keep each token's bank format until the scheduler replaces that token.
// Configure before the first write. A scheduler must complete or discard a
// token before issuing downstream reads for it.
module tri_oracle_residual_format_bank (
    input logic clk, rst_n, lease_granted,
    input logic cfg_valid, cfg_token,
    input logic [4:0] cfg_down_shift,
    output logic cfg_ready,
    input logic req_valid, req_write, req_token,
    input logic [7:0] req_strip,
    input logic [231:0] req_bypass,
    input logic [127:0] req_normalization,
    output logic req_ready,
    output logic rsp_valid,
    input logic rsp_ready,
    output logic [231:0] rsp_bypass,
    output logic [127:0] rsp_normalization,
    output logic [4:0] rsp_down_shift,
    output logic [3:0] bank_ce_n, bank_we_n,
    output logic [8:0] bank_addr,
    output logic [255:0] bank_d,
    input logic [255:0] bank_q
);
    logic [1:0] configured;
    logic [4:0] down_shift [2];
    logic response_token;
    logic adapter_ready, adapter_offer, ce_n, we_n;
    logic compact_request, compact_response;
    logic [23:0] correction, read_correction;
    logic [191:0] compact_row;
    logic [231:0] compact_bypass;
    logic [15:0] compact_correction;

    assign cfg_ready = adapter_ready;
    assign req_ready = adapter_ready && !cfg_valid && configured[req_token];
    assign adapter_offer = req_valid && !cfg_valid && configured[req_token];
    assign compact_request = down_shift[req_token] >= 5'd11;
    assign rsp_down_shift = rsp_valid ? down_shift[response_token] : '0;
    assign compact_response = rsp_down_shift >= 5'd11;
    assign bank_ce_n = {ce_n || compact_request, {3{ce_n}}};
    assign bank_we_n = {we_n || compact_request, {3{we_n}}};
    assign bank_d = compact_request ? {64'd0, compact_row} : {correction, req_bypass};
    assign rsp_bypass = !rsp_valid ? '0 : compact_response ? compact_bypass : bank_q[231:0];
    assign read_correction = compact_response ? {8'd0, compact_correction} : bank_q[255:232];

    tri_oracle_residual_bank_adapter bank_port (
        .clk, .rst_n, .lease_granted, .req_valid(adapter_offer), .req_write, .req_token, .req_strip,
        .req_data(req_bypass), .req_ready(adapter_ready), .rsp_valid, .rsp_ready,
        .rsp_data(), .bank_ce_n(ce_n), .bank_we_n(we_n), .bank_addr, .bank_d(), .bank_q
    );
    tri_oracle_residual_replay_row rounding (
        .write_bypass(req_bypass), .write_normalization(req_normalization),
        .write_padding(correction), .read_bypass(rsp_bypass), .read_padding(read_correction),
        .read_normalization(rsp_normalization)
    );
    tri_oracle_residual_compact_row compact (
        .write_bypass(req_bypass), .write_correction(correction[15:0]), .write_row(compact_row),
        .read_row(bank_q[191:0]), .read_bypass(compact_bypass), .read_correction(compact_correction)
    );

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            configured <= '0;
            down_shift[0] <= '0;
            down_shift[1] <= '0;
            response_token <= 0;
        end else begin
            if (cfg_valid && cfg_ready) begin
                configured[cfg_token] <= 1;
                down_shift[cfg_token] <= cfg_down_shift;
            end
            if (req_valid && req_ready && !req_write) response_token <= req_token;
        end
    end
endmodule
