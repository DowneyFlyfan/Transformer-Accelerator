`timescale 1ns/1ps
// Five clusters x four cores. Command routing and ports are local choices;
// this is a compute/memory fabric, not a complete vision-language processor.
module tri_oracle_compute_fabric (
    input wire clk,rst_n,load_valid,
    input wire [4:0] load_core,
    input wire [1:0] load_kind,
    input wire [9:0] load_addr,
    input wire [2047:0] load_data,
    input wire [31:0] load_row_enable,
    output wire load_error,
    input wire cmd_valid,
    output wire cmd_ready,
    input wire [4:0] cmd_clusters,cmd_weight,cmd_mask,
    input wire [9:0] cmd_activation,
    input wire [3:0] cmd_output,
    input wire cmd_accumulate,
    input wire [1:0] cmd_reduce,
    output wire [4:0] out_valid,
    input wire [4:0] out_ready,
    output wire [19:0] out_output,
    output wire [5119:0] out_data
);
    wire [4:0] cluster_ready,load_errors;
    assign cmd_ready=(|cmd_clusters) && ((cluster_ready & cmd_clusters)==cmd_clusters);
    assign load_error=(|load_errors) || (load_valid && load_core>=20);
    for(genvar cluster=0;cluster<5;cluster=cluster+1)begin: clusters
        tri_oracle_compute_cluster unit (
            .clk(clk),.rst_n(rst_n),
            .load_valid(load_valid && load_core[4:2]==3'(cluster)),
            .load_core(load_core[1:0]),.load_kind(load_kind),
            .load_addr(load_addr),.load_data(load_data),.load_row_enable(load_row_enable),
            .load_error(load_errors[cluster]),
            .cmd_valid(cmd_valid && cmd_ready && cmd_clusters[cluster]),
            .cmd_ready(cluster_ready[cluster]),.cmd_weight(cmd_weight),
            .cmd_mask(cmd_mask),.cmd_activation(cmd_activation),.cmd_output(cmd_output),
            .cmd_accumulate(cmd_accumulate),.cmd_reduce(cmd_reduce),
            .out_valid(out_valid[cluster]),.out_ready(out_ready[cluster]),
            .out_output(out_output[cluster*4+:4]),.out_data(out_data[cluster*1024+:1024])
        );
    end
endmodule
