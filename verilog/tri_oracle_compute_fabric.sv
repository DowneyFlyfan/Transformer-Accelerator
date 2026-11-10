`timescale 1ns/1ps
// Five clusters x four cores. Command routing and ports are local choices;
// this is a compute/memory fabric, not a complete vision-language processor.
module tri_oracle_compute_fabric #(
  parameter bit AGGREGATOR_SIGN_BANK=0,
  parameter bit AGGREGATOR_MERGE_TABLE=0,
  parameter bit CORE_STRIP_PREDICTOR=0,
  parameter bit CORE_HEAD_PREDICTOR=0
) (
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
    output wire [5119:0] out_data,
    input wire [2047:0] merge_sign_data,
    input wire [12:0] merge_sign_control,
    output wire [119:0] merge_sign_counts,
    input wire [21:0] merge_table_request,
    output wire [79:0] merge_table_word,
    input wire strip_rst_n,
    input wire [533:0] strip_request,
    output wire [111:0] strip_response,
    input logic [399:0] head_request,
    output logic [72:0] head_response
);
    wire [4:0] cluster_ready,load_errors;
    wire [2:0] table_owner = merge_table_request[19:17];
    logic [2:0] read_table_owner;
    wire [79:0] table_words[5];
    if (AGGREGATOR_MERGE_TABLE) begin : route_merge_table
        always_ff @(posedge clk) begin
            if (merge_table_request[21] && !merge_table_request[20]) read_table_owner <= table_owner;
        end
        assign merge_table_word = read_table_owner<5 ? table_words[read_table_owner] : '0;
    end else begin : no_merge_table
        assign merge_table_word = '0;
    end
    wire [2:0] strip_cluster=strip_request[533:531];
    wire [111:0] cluster_strip_responses[5];
    wire [2:0] head_cluster=head_request[399:397];
    wire [72:0] cluster_head_responses[5];
    assign head_response = CORE_HEAD_PREDICTOR && head_cluster<5 ?
        cluster_head_responses[head_cluster] : '0;
    assign strip_response = CORE_STRIP_PREDICTOR && strip_cluster<5 ?
        cluster_strip_responses[strip_cluster] : '0;
    assign cmd_ready=(|cmd_clusters) && ((cluster_ready & cmd_clusters)==cmd_clusters);
    assign load_error=(|load_errors) || (load_valid && load_core>=20);
    for(genvar cluster=0;cluster<5;cluster=cluster+1)begin: clusters
        localparam int MERGE_FEATURES=AGGREGATOR_SIGN_BANK ? (cluster==0 ? 512 : 384) : 0;
        localparam int SIGN_WIDTH=MERGE_FEATURES==0 ? 1 : MERGE_FEATURES;
        localparam int SIGN_START=cluster==0 ? 0 : 512+(cluster-1)*384;
        tri_oracle_compute_cluster #(
            .MERGE_FEATURES(MERGE_FEATURES), .AGGREGATOR_MERGE_TABLE(AGGREGATOR_MERGE_TABLE),
            .MERGE_TABLE_ENTRIES(cluster==4 ? 64 : 128),
            .CORE_STRIP_PREDICTOR(CORE_STRIP_PREDICTOR),
            .CORE_HEAD_PREDICTOR(CORE_HEAD_PREDICTOR)
        ) unit (
            .head_request({head_request[396:395],
                CORE_HEAD_PREDICTOR && head_cluster==3'(cluster) ? head_request[394:392] : 3'b0,
                head_request[391:0]}),
            .head_response(cluster_head_responses[cluster]),
            .strip_rst_n,
            .strip_request(CORE_STRIP_PREDICTOR && strip_cluster==3'(cluster) ? strip_request[530:0] : 531'b0),
            .strip_response(cluster_strip_responses[cluster]),
            .merge_sign_data(merge_sign_data[SIGN_START+:SIGN_WIDTH]),
            .merge_sign_control(merge_sign_control),
            .merge_sign_counts(merge_sign_counts[cluster*24+:24]),
            .merge_table_request({merge_table_request[21] && table_owner==3'(cluster),
                                  merge_table_request[20], merge_table_request[16:0]}),
            .merge_table_word(table_words[cluster]),
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
