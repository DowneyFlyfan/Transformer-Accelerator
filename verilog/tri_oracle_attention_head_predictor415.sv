`timescale 1ns/1ps
// Schedule the selected sink, inner, and recent tiles for one query head.
// Query memory starts at position 96, while key memory starts at position 0.
// The caller selects the key head and supplies the score scale as integer alpha.
// The configured ratio and 32-key tile geometry are local reconstruction choices.
module tri_oracle_attention_head_predictor415 #(
    parameter bit CORE_HEAD_PREDICTOR=0
) (
    input logic clk, rst_n,
    input logic cfg_valid,
    output logic cfg_ready,
    input logic [31:0] cfg_tag, cfg_alpha,
    input logic [12:0] cfg_tokens,
    input logic [7:0] cfg_ratio_num, cfg_ratio_den,
    input logic [63:0] cfg_query_base, cfg_key_base,
    output logic out_valid, out_error, out_streaming,
    input logic out_ready,
    output logic [31:0] out_tag,
    output logic [17:0] out_inner, out_outer,

    output logic tensor_cfg_valid,
    input logic tensor_cfg_ready,
    output logic [31:0] tensor_cfg_tag,
    output logic [4:0] tensor_cfg_tokens,
    output logic [16:0] tensor_cfg_dense_rows,
    output logic [2559:0] tensor_cfg_channels, tensor_cfg_keep,
    output logic [63:0] tensor_cfg_activation_base, tensor_cfg_weight_base,
    input logic tensor_out_valid, tensor_out_last,
    output logic tensor_out_ready,
    input logic [31:0] tensor_out_tag,
    input logic [3:0] tensor_out_token,
    input logic [7:0] tensor_out_count,
    input logic [3071:0] tensor_out_data,
    input logic tensor_done_valid, tensor_done_error,
    output logic tensor_done_ready,
    input logic [31:0] tensor_done_tag,
    input logic [4:0] cfg_head_id,
    output logic [399:0] head_request,
    input logic [72:0] head_response
);
    localparam logic [12:0] FIRST_QUERY = 96;
    typedef enum logic [2:0] {Idle, Configure, OfferBatch, WaitBatch, Result, Invalid} state_t;
    state_t state;
    logic [31:0] tag, alpha;
    logic [4:0] classifier_owner;
    logic [12:0] tokens, query_position, next_query, remaining;
    logic [63:0] query_addr, key_base;
    logic [7:0] ratio_num, ratio_den;
    logic bad_config, batch_failed;
    logic query_wraps, key_wraps;
    logic [15:0] inner_start, recent_start;

    logic batch_valid, batch_ready, batch_last;
    logic [31:0] batch_tag;
    logic [63:0] batch_query_addr, batch_key_base;
    logic [16:0] batch_key_rows;
    logic [15:0] batch_query_first;
    logic [4:0] batch_queries;
    logic [47:0] batch_tile_start;
    logic score_valid, score_ready, score_last, score_error;
    logic [31:0] score_tag;
    logic [1:0] score_region;
    logic [7:0] score_lanes;
    logic [255:0] score_data;
    logic classifier_cfg_ready, classifier_valid, classifier_error, classifier_streaming;
    logic [31:0] classifier_tag;
    logic [17:0] classifier_inner, classifier_outer;

    assign query_wraps = ({1'b0, cfg_query_base} + ((65'(cfg_tokens)-65'(FIRST_QUERY)) << 6) - 65'd1) >
                         65'h0ffffffffffffffff;
    assign key_wraps = ({1'b0, cfg_key_base} + (65'(cfg_tokens) << 6) - 65'd1) > 65'h0ffffffffffffffff;
    assign bad_config = cfg_tokens <= FIRST_QUERY || cfg_tokens > FIRST_QUERY+13'd4096 || cfg_ratio_den == 0 ||
                        cfg_query_base[2:0] != 0 || cfg_key_base[2:0] != 0 || query_wraps || key_wraps;
    assign cfg_ready = state == Idle;
    assign out_valid = state == Invalid || (state == Result && classifier_valid);
    assign out_error = state == Invalid || classifier_error;
    assign out_tag = state == Invalid ? tag : classifier_tag;
    assign out_inner = state == Invalid ? '0 : classifier_inner;
    assign out_outer = state == Invalid ? '0 : classifier_outer;
    assign out_streaming = state == Result && classifier_streaming;

    assign remaining = tokens - query_position;
    assign batch_queries = remaining >= 16 ? 5'd16 : 5'(remaining);
    assign next_query = query_position + 13'(batch_queries);
    assign recent_start = {3'b0, query_position[12:5], 5'b0};
    assign inner_start = recent_start - 16'd64;
    assign batch_valid = state == OfferBatch;
    assign batch_last = next_query == tokens;
    assign batch_tag = tag;
    assign batch_query_addr = query_addr;
    assign batch_key_base = key_base;
    assign batch_key_rows = 17'(tokens);
    assign batch_query_first = 16'(query_position);
    assign batch_tile_start = {recent_start, inner_start, 16'd0};

    tri_oracle_attention_tile_batch413 tile (.*);
    if (CORE_HEAD_PREDICTOR) begin : distributed_classification
        // The owner is held from configuration until result retirement.
        assign head_request = {classifier_owner, state == Configure, score_valid,
                               state == Result && out_ready, tag, alpha, 13'(tokens-FIRST_QUERY),
                               ratio_num, ratio_den, score_last, score_tag,
                               score_tag==tag ? score_region : 2'd3, score_lanes, score_data};
        assign {classifier_cfg_ready, score_ready, classifier_valid, classifier_error,
                classifier_streaming, classifier_tag, classifier_inner, classifier_outer} = head_response;
    end else begin : local_classification
        assign head_request = '0;
        tri_oracle_attention_head_classifier410 classifier (
            .clk, .rst_n, .cfg_valid(state == Configure), .cfg_ready(classifier_cfg_ready),
            .cfg_tag(tag), .cfg_alpha(alpha), .cfg_rows(tokens-FIRST_QUERY),
            .cfg_ratio_num(ratio_num), .cfg_ratio_den(ratio_den),
            .in_valid(score_valid), .in_ready(score_ready), .in_last(score_last), .in_tag(score_tag),
            .in_region(score_region), .in_lanes(score_lanes), .in_scores(score_data),
            .out_valid(classifier_valid), .out_ready(state == Result && out_ready), .out_tag(classifier_tag),
            .out_error(classifier_error), .out_streaming(classifier_streaming),
            .out_inner(classifier_inner), .out_outer(classifier_outer)
        );
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= Idle;
            tag <= 0; alpha <= 0; tokens <= 0; classifier_owner <= 0;
            query_addr <= 0; key_base <= 0; query_position <= FIRST_QUERY;
            ratio_num <= 0; ratio_den <= 0; batch_failed <= 0;
        end else case (state)
            Idle: if (cfg_valid) begin
                tag <= cfg_tag; alpha <= cfg_alpha; tokens <= cfg_tokens;
                classifier_owner <= cfg_head_id>=5'd20 ? cfg_head_id-5'd20 : cfg_head_id;
                query_addr <= cfg_query_base; key_base <= cfg_key_base;
                ratio_num <= cfg_ratio_num; ratio_den <= cfg_ratio_den;
                query_position <= FIRST_QUERY;
                batch_failed <= 0;
                if (bad_config) state <= Invalid;
                else state <= Configure;
            end
            Configure: if (classifier_cfg_ready) state <= OfferBatch;
            OfferBatch: if (batch_ready) state <= WaitBatch;
            WaitBatch: begin
                if (score_valid && score_ready && score_error) batch_failed <= 1;
                if (batch_ready) begin
                    if (batch_failed || batch_last) state <= Result;
                    else begin
                        query_position <= next_query;
                        query_addr <= query_addr + (64'(batch_queries) << 6);
                        state <= OfferBatch;
                    end
                end
            end
            Result: if (classifier_valid && out_ready) state <= Idle;
            Invalid: if (out_ready) state <= Idle;
            default: state <= Idle;
        endcase
    end
endmodule
