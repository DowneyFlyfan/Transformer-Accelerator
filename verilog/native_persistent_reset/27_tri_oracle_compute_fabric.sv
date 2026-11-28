`timescale 1ns/1ps
// Five clusters x four cores. Command routing and ports are local choices;
// this is a compute/memory fabric, not a complete vision-language processor.
module tri_oracle_compute_fabric #(
  parameter bit AGGREGATOR_SIGN_BANK=0,
  parameter bit AGGREGATOR_MERGE_TABLE=0,
  parameter bit LOCAL_TOKEN_SIZES=0, LOCAL_TOKEN_MERGE=0,
  parameter bit CORE_STRIP_PREDICTOR=0,
  parameter bit CORE_HEAD_PREDICTOR=0
) (
    input wire clk,rst_n,persistent_rst_n,load_valid,
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
    input tri_oracle_wac_softmax_types::request_t softmax_request,
  output tri_oracle_wac_softmax_types::response_t softmax_response,
  input logic [4:0] activation_reloaded,
  input logic [2:0] core_score_select,
  input tri_oracle_token_size_types::request_t token_sizes_request,
    output tri_oracle_token_size_types::response_t token_sizes_response,
    output logic [9:0] token_sizes_out_origin,
    input tri_oracle_merge_range_types::request_t merge_request,
    output tri_oracle_merge_range_types::response_t merge_response,
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
    tri_oracle_token_size_types::bank_command_t [4:0] bank_command;
    tri_oracle_token_size_types::bank_result_t [4:0] bank_result;
    tri_oracle_merge_range_types::range_command_t [4:0] range_commands;
    tri_oracle_merge_range_types::range_result_t [4:0] range_results;
    wire [12:0] local_sign_control;
    wire [21:0] local_table_request;
    wire [12:0] sign_command=LOCAL_TOKEN_MERGE ? local_sign_control : merge_sign_control;
    wire [21:0] table_command=LOCAL_TOKEN_MERGE ? local_table_request : merge_table_request;
    if (LOCAL_TOKEN_MERGE) begin : coordinate_merge
        tri_oracle_merge_range_relay relay (
            .clk, .rst_n(persistent_rst_n), .cfg_valid(merge_request.cfg_valid), .cfg_new_image(merge_request.cfg_new_image),
            .cfg_ready(merge_response.cfg_ready), .cfg_minimum_matches(merge_request.threshold),
            .sign_valid(merge_request.sign_valid), .sign_ready(merge_response.sign_ready),
            .map_valid(merge_response.map_valid), .map_ready(merge_request.map_ready),
            .map_index(merge_response.map_index), .map_origin(merge_response.map_origin),
            .map_last(merge_response.map_last), .done_valid(merge_response.done_valid),
            .done_error(merge_response.done_error), .done_ready(merge_request.done_ready),
            .sign_control(local_sign_control), .table_request(local_table_request),
            .commands(range_commands), .results(range_results)
        );
    end else begin : no_local_merge
        assign range_commands='0;
        assign merge_response='0;
        assign local_sign_control='0;
        assign local_table_request='0;
    end
    if (LOCAL_TOKEN_SIZES) begin : coordinate_token_sizes
        tri_oracle_token_size_control controller (
            .clk, .rst_n(persistent_rst_n), .frame_valid(token_sizes_request.frame_valid),
            .frame_ready(token_sizes_response.frame_ready),
            .map_valid(token_sizes_request.map_valid), .map_ready(token_sizes_response.map_ready),
            .map_origin(token_sizes_request.map_origin), .map_last(token_sizes_request.map_last),
            .query_valid(token_sizes_request.query_valid), .query_ready(token_sizes_response.query_ready),
            .query_position(token_sizes_request.query_position), .out_valid(token_sizes_response.out_valid),
            .out_ready(token_sizes_request.out_ready), .out_origin(token_sizes_out_origin), .out_count(token_sizes_response.out_count),
            .out_last(token_sizes_response.out_last), .error(token_sizes_response.error),
            .table_request(table_command), .table_word(merge_table_word), .bank_command, .bank_result
        );
    end else begin : no_local_token_sizes
        assign bank_command='0;
        assign token_sizes_response='0;
        assign token_sizes_out_origin='0;
    end
    if (!LOCAL_TOKEN_SIZES && AGGREGATOR_MERGE_TABLE) begin : route_merge_table
        always_ff @(posedge clk) begin
            if (merge_table_request[21] && !merge_table_request[20]) read_table_owner <= table_owner;
        end
        assign merge_table_word = read_table_owner<5 ? table_words[read_table_owner] : '0;
    end else if (!LOCAL_TOKEN_SIZES) begin : no_merge_table
        assign merge_table_word = '0;
    end
    wire [2:0] strip_cluster=strip_request[533:531];
    wire [111:0] cluster_strip_responses[5];
    wire [2:0] head_cluster=head_request[399:397];
    wire [72:0] cluster_head_responses[5];
    wire [2:0] softmax_cluster = softmax_request.owner[4:2];
    tri_oracle_wac_softmax_types::response_t [4:0] cluster_softmax_responses;
    assign softmax_response = softmax_cluster<5 ? cluster_softmax_responses[softmax_cluster] : '0;
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
        tri_oracle_partitioned_cluster #(
            .MERGE_FEATURES(MERGE_FEATURES), .AGGREGATOR_MERGE_TABLE(AGGREGATOR_MERGE_TABLE),
            .MERGE_TABLE_ENTRIES(cluster==4 ? 64 : 128),
            .LOCAL_TOKEN_SIZES(LOCAL_TOKEN_SIZES), .LOCAL_TOKEN_MERGE(LOCAL_TOKEN_MERGE), .MERGE_TABLE_START(cluster*128),
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
            .merge_sign_control(sign_command),
            .merge_sign_counts(merge_sign_counts[cluster*24+:24]),
            .merge_table_request({merge_table_request[21] && table_owner==3'(cluster),
                                  merge_table_request[20], merge_table_request[16:0]}),
            .merge_table_word(table_words[cluster]),
            .token_size_bank_command(bank_command[cluster]), .token_size_bank_result(bank_result[cluster]),
            .softmax_request(softmax_cluster==3'(cluster) ? softmax_request : '0),
            .softmax_response(cluster_softmax_responses[cluster]), .activation_reloaded(activation_reloaded[cluster]), .core_score_select,
            .merge_range_command(range_commands[cluster]), .merge_range_result(range_results[cluster]),
            .global_merge_word(merge_table_word), .global_sign_counts(merge_sign_counts),
            .clk(clk),.rst_n(rst_n),.persistent_rst_n(persistent_rst_n),
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
