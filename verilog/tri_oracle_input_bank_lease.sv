`timescale 1ns/1ps
module tri_oracle_input_bank_lease (
    input logic clk, rst_n,
    input logic owner_available,
    input logic native_request, native_start, native_end, native_write,
    input logic [1:0] native_ce_n, native_we_n,
    input logic [8:0] native_address,
    input logic [127:0] native_data,
    input logic [127:0] bank_read,
    input logic probability_request, probability_release,
    input logic [1:0] probability_ce_n, probability_we_n,
    input logic [8:0] probability_address,
    input logic [127:0] probability_data,
    output logic probability_grant,
    output logic [127:0] probability_read,
    output logic owner_request, owner_start, owner_end, owner_write,
    output logic [1:0] bank_ce_n, bank_we_n,
    output logic [8:0] bank_address,
    output logic [127:0] bank_data
);
    logic probability_owner, acquire;

    assign probability_grant = owner_available && !native_request && !probability_owner;
    assign acquire = probability_request && probability_grant;
    assign owner_request = native_request || probability_request;
    assign owner_start = native_start || acquire;
    assign owner_end = probability_owner ? probability_release : native_end;
    assign owner_write = probability_owner ? |(~probability_ce_n & ~probability_we_n) : native_write;

    assign bank_ce_n = probability_owner ? probability_ce_n : native_ce_n;
    assign bank_we_n = probability_owner ? probability_we_n : native_we_n;
    assign bank_address = probability_owner ? probability_address : native_address;
    assign bank_data = probability_owner ? probability_data : native_data;
    assign probability_read = probability_owner ? bank_read : '0;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) probability_owner <= 1'b0;
        else if (acquire) probability_owner <= 1'b1;
        else if (probability_release) probability_owner <= 1'b0;
    end
endmodule
