`timescale 1ns/1ps

// The controller grants projection only after the metadata client has drained.
// Projection holds ownership through the last response handshake and release.
module tri_oracle_projection_shared_bank (
    input logic clk, rst_n,
    input logic metadata_idle,
    input logic acquire_valid,
    output logic acquire_ready,
    input logic release_valid,
    output logic release_ready,
    input logic row_valid,
    output logic row_ready,
    input logic [2047:0] row_data,
    input logic [4:0] row_shift,
    input logic [5:0] row_index,
    output logic frame_ready, fill_error,
    input logic req_valid,
    output logic req_ready,
    input logic [8:0] req_word,
    input logic [4:0] req_length,
    output logic rsp_valid,
    input logic rsp_ready,
    output logic rsp_last, rsp_error,
    output logic [63:0] rsp_data,
    input logic metadata_ce_n, metadata_we_n,
    input logic [8:0] metadata_address,
    input logic [63:0] metadata_write_data,
    output logic [63:0] metadata_read_data
);
    logic projection_owner;
    logic projection_ce_n, projection_we_n;
    logic store_in_ready, store_req_ready, store_release_ready;
    logic [8:0] projection_address;
    logic [63:0] projection_write_data, bank_output;

    assign acquire_ready = rst_n && !projection_owner && metadata_idle && metadata_ce_n;
    assign release_ready = projection_owner && store_release_ready;
    assign row_ready = projection_owner && store_in_ready;
    assign req_ready = projection_owner && store_req_ready;
    assign metadata_read_data = projection_owner ? '0 : bank_output;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) projection_owner <= 0;
        else if (acquire_valid && acquire_ready) projection_owner <= 1;
        else if (release_valid && release_ready) projection_owner <= 0;
    end

    tri_oracle_projection_activation_store #(.EXTERNAL_BANK(1)) store (
        .clk, .rst_n, .in_valid(row_valid && projection_owner), .in_ready(store_in_ready),
        .in_data(row_data), .in_shift(row_shift), .in_row(row_index), .frame_ready, .fill_error,
        .release_valid(release_valid && projection_owner), .release_ready(store_release_ready),
        .req_valid(req_valid && projection_owner), .req_word, .req_length, .req_ready(store_req_ready),
        .rsp_valid, .rsp_ready, .rsp_last, .rsp_error, .rsp_data,
        .bank_ce_n(projection_ce_n), .bank_we_n(projection_we_n), .bank_address(projection_address),
        .bank_write_data(projection_write_data), .bank_read_data(bank_output)
    );

    TS5N28HPCPSVTA512X64M4F shared_bank (
        .CLK(clk),
        .CEB(!rst_n || (projection_owner ? projection_ce_n : metadata_ce_n)),
        .WEB(projection_owner ? projection_we_n : metadata_we_n),
        .A(projection_owner ? projection_address : metadata_address),
        .D(projection_owner ? projection_write_data : metadata_write_data),
        .Q(bank_output)
    );
endmodule
