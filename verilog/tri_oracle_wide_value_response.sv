`timescale 1ns/1ps
module tri_oracle_wide_value_response (
    input  logic         clk, rst_n,
    input  logic         vector_req_valid,
    output logic         vector_req_ready,
    output logic         vector_rsp_valid,
    input  logic         vector_rsp_ready,
    output logic         vector_rsp_error,
    output logic [511:0] vector_rsp_data,
    output logic         bus_req_valid,
    input  logic         bus_req_ready,
    input  logic         bus_rsp_valid,
    output logic         bus_rsp_ready,
    input  logic         bus_rsp_last, bus_rsp_error,
    input  logic [511:0] bus_rsp_data
);
    logic pending, received, error;
    logic [511:0] value_word;

    assign bus_req_valid = rst_n && vector_req_valid && !pending && !received;
    assign vector_req_ready = rst_n && bus_req_ready && !pending && !received;
    assign bus_rsp_ready = pending;
    assign vector_rsp_valid = received;
    assign vector_rsp_error = received && error;
    assign vector_rsp_data = error ? '0 : value_word;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            pending <= 1'b0;
            received <= 1'b0;
            error <= 1'b0;
        end else begin
            if (vector_rsp_valid && vector_rsp_ready)
                received <= 1'b0;
            if (bus_req_valid && bus_req_ready) begin
                pending <= 1'b1;
                error <= 1'b0;
            end
            if (bus_rsp_valid && bus_rsp_ready) begin
                error <= error || bus_rsp_error || !bus_rsp_last;
                if (bus_rsp_last) begin
                    pending <= 1'b0;
                    received <= 1'b1;
                end
            end
        end
    end

    always_ff @(posedge clk)
        if (bus_rsp_valid && bus_rsp_ready && bus_rsp_last)
            value_word <= bus_rsp_data;
endmodule
