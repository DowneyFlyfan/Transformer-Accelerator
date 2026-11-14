`timescale 1ns/1ps

// Two 2,048-element tokens use 512 rows of four 64-bit input banks.
// Each row contains eight signed 29-bit residual codes. The owner keeps
// the lease until any outstanding read response is consumed or reset.
module tri_oracle_residual_bank_adapter (
    input logic clk, rst_n, lease_granted,
    input logic req_valid, req_write, req_token,
    output logic req_ready,
    input logic [7:0] req_strip,
    input logic [231:0] req_data,
    output logic rsp_valid,
    input logic rsp_ready,
    output logic [231:0] rsp_data,
    output logic bank_ce_n, bank_we_n,
    output logic [8:0] bank_addr,
    output logic [255:0] bank_d,
    input logic [255:0] bank_q
);
    logic request;

    assign req_ready = rst_n && lease_granted && !rsp_valid;
    assign request = req_valid && req_ready;
    assign bank_ce_n = !request;
    assign bank_we_n = !(request && req_write);
    assign bank_addr = {req_token, req_strip};
    assign bank_d = {24'd0, req_data};
    // With CE inactive, the compiled banks hold the last read result
    // throughout downstream stalls. Do not issue another read or write
    // until the current response retires.
    assign rsp_data = rsp_valid ? bank_q[231:0] : '0;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            rsp_valid <= 1'b0;
        else if (request)
            rsp_valid <= !req_write;
        else if (rsp_ready)
            rsp_valid <= 1'b0;
    end
endmodule
