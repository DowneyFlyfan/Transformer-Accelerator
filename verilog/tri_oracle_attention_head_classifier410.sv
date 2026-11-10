`timescale 1ns/1ps
// Head max/intensity and type decision from the paper's Fig. 31.6.4.
// A row has four eight-score beats per sink, inner, and recent tile.
// Lane masks exclude causal padding. Alpha is expressed in integer score
// units. The ratio is configurable because the paper does not publish it.
// Error retires only after the malformed packet's LAST. If configuration
// fails before input starts, cancel any held input on the tagged error.
module tri_oracle_attention_head_classifier410 #(
    parameter bit SERIAL_RATIO=0,
    parameter bit SHARED_CONFIG=0
) (
    input logic clk, rst_n,
    input logic cfg_valid,
    output logic cfg_ready,
    input logic [31:0] cfg_tag, cfg_alpha,
    input logic [12:0] cfg_rows,
    input logic [7:0] cfg_ratio_num, cfg_ratio_den,
    input logic in_valid, in_last,
    output logic in_ready,
    input logic [31:0] in_tag,
    input logic [1:0] in_region,
    input logic [7:0] in_lanes,
    input logic [255:0] in_scores,
    output logic out_valid,
    input logic out_ready,
    output logic out_error, out_streaming,
    output logic [31:0] out_tag,
    output logic [17:0] out_inner, out_outer
);
    typedef enum logic [2:0] {Idle, Sink, Inner, Recent, Classify, Drain, Hold} state_t;
    localparam logic signed [31:0] MIN_SCORE = 32'sh80000000;
    state_t state;
    wire [31:0] alpha;
    logic [12:0] rows_left;
    wire [7:0] ratio_num, ratio_den;
    logic [1:0] beat_index, expected_region;
    logic row_has_sink, expected_last, malformed, streaming, tag_mismatch;
    logic signed [31:0] row_max, pair_max [0:3], beat_max, updated_max;
    logic [3:0] pair_valid;
    logic signed [33:0] cutoff;
    logic [7:0] hits;
    logic [1:0] pair_hits [0:3];
    logic [3:0] beat_hits;
    logic [17:0] total_inner, total_outer;
    logic ratio_done, ratio_streaming;

    function automatic logic signed [31:0] valid_maximum(
        input logic signed [31:0] left, right,
        input logic left_valid, right_valid
    );
        return left_valid && (!right_valid || left > right) ? left : right;
    endfunction

    // The cutoff cannot exceed the signed score range at its upper end
    // because alpha is unsigned. Below that range every enabled lane hits.
    wire below_minimum = cutoff[33] && !(cutoff[32] && cutoff[31]);
    for (genvar lane = 0; lane < 8; lane++) begin : lanes
        assign hits[lane] = in_lanes[lane] &&
            (below_minimum || $signed(in_scores[lane*32+:32]) > $signed(cutoff[31:0]));
    end
    for (genvar pair_index = 0; pair_index < 4; pair_index++) begin : pairs
        assign pair_valid[pair_index] = |in_lanes[2*pair_index+:2];
        assign pair_max[pair_index] = valid_maximum(
            $signed(in_scores[64*pair_index+:32]), $signed(in_scores[64*pair_index+32+:32]),
            in_lanes[2*pair_index], in_lanes[2*pair_index+1]);
        assign pair_hits[pair_index] = 2'(hits[2*pair_index]) + 2'(hits[2*pair_index+1]);
    end
    assign beat_max = valid_maximum(
        valid_maximum(pair_max[0], pair_max[1], pair_valid[0], pair_valid[1]),
        valid_maximum(pair_max[2], pair_max[3], pair_valid[2], pair_valid[3]),
        (|pair_valid[1:0]), (|pair_valid[3:2]));
    assign updated_max = valid_maximum(row_max, beat_max, 1'b1, (|in_lanes));
    assign beat_hits = (4'(pair_hits[0]) + 4'(pair_hits[1])) + (4'(pair_hits[2]) + 4'(pair_hits[3]));

    assign cfg_ready = state == Idle;
    assign in_ready = state == Sink || state == Inner || state == Recent || state == Drain;
    assign expected_region = state == Sink ? 2'd0 : state == Inner ? 2'd1 : 2'd2;
    assign expected_last = state == Recent && beat_index == 3 && rows_left == 1;
    assign malformed = tag_mismatch || in_region != expected_region || in_last != expected_last;
    assign out_valid = state == Hold;
    if (SHARED_CONFIG) begin : shared_config
        // The scheduler holds these fields through result retirement and
        // marks a bad score tag with an invalid region before dispatch.
        assign alpha = cfg_alpha;
        assign ratio_num = cfg_ratio_num;
        assign ratio_den = cfg_ratio_den;
        assign tag_mismatch = 0;
        assign out_tag = cfg_tag;
    end else begin : local_config
        logic [31:0] tag, saved_alpha;
        logic [7:0] saved_ratio_num, saved_ratio_den;
        always_ff @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                tag <= '0;
                saved_alpha <= '0;
                saved_ratio_num <= '0;
                saved_ratio_den <= '0;
            end else if (cfg_ready && cfg_valid) begin
                tag <= cfg_tag;
                saved_alpha <= cfg_alpha;
                saved_ratio_num <= cfg_ratio_num;
                saved_ratio_den <= cfg_ratio_den;
            end
        end
        assign alpha = saved_alpha;
        assign ratio_num = saved_ratio_num;
        assign ratio_den = saved_ratio_den;
        assign tag_mismatch = in_tag != tag;
        assign out_tag = tag;
    end
    assign out_streaming = !out_error && streaming;
    assign out_inner = out_error ? '0 : total_inner;
    assign out_outer = out_error ? '0 : total_outer;
    if (SERIAL_RATIO) begin : serial_ratio
        logic [2:0] ratio_bit;
        logic signed [26:0] difference;
        wire signed [18:0] inner = ratio_num[ratio_bit] ? $signed({1'b0,total_inner}) : 19'sd0;
        wire signed [18:0] outer = ratio_den[ratio_bit] ? $signed({1'b0,total_outer}) : 19'sd0;
        wire signed [18:0] term = outer - inner;
        // Most significant bit first. The signed product difference fits
        // in 27 bits because each intensity is 18 bits and each ratio is 8.
        wire signed [26:0] next_difference = (difference <<< 1) + 27'(term);
        always_ff @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                ratio_bit <= 7;
                difference <= '0;
            end else if (state != Classify) begin
                ratio_bit <= 7;
                difference <= '0;
            end else if (ratio_bit != 0) begin
                ratio_bit <= ratio_bit - 1'b1;
                difference <= next_difference;
            end
        end
        assign ratio_done = ratio_bit==0;
        assign ratio_streaming = next_difference > 0;
    end else begin : parallel_ratio
        wire [25:0] inner_product = 26'(total_inner) * 26'(ratio_num);
        wire [25:0] outer_product = 26'(total_outer) * 26'(ratio_den);
        assign ratio_done = 1;
        assign ratio_streaming = outer_product > inner_product;
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= Idle;
            rows_left <= '0; beat_index <= '0;
            row_has_sink <= 0; row_max <= MIN_SCORE; cutoff <= '0;
            total_inner <= '0; total_outer <= '0;
            out_error <= 0; streaming <= 0;
        end else case (state)
            Idle: if (cfg_valid) begin
                rows_left <= cfg_rows;
                beat_index <= '0;
                row_has_sink <= 0; row_max <= MIN_SCORE;
                total_inner <= '0; total_outer <= '0; streaming <= 0;
                out_error <= cfg_rows == 0 || cfg_rows > 4096 || cfg_ratio_den == 0;
                if (cfg_rows == 0 || cfg_rows > 4096 || cfg_ratio_den == 0) state <= Hold;
                else state <= Sink;
            end
            Sink, Inner, Recent: if (in_valid) begin
                if (malformed || (state == Sink && beat_index == 3 && !row_has_sink && in_lanes == 0)) begin
                    out_error <= 1;
                    if (in_last) state <= Hold;
                    else state <= Drain;
                end else begin
                    beat_index <= beat_index + 2'd1;
                    case (state)
                        Sink: begin
                            row_has_sink <= row_has_sink || in_lanes != 0;
                            row_max <= updated_max;
                            if (beat_index == 3) begin
                                cutoff <= $signed({{2{updated_max[31]}}, updated_max}) - $signed({2'b00, alpha});
                                state <= Inner;
                            end
                        end
                        Inner: begin
                            total_inner <= total_inner + 18'(beat_hits);
                            if (beat_index == 3) state <= Recent;
                        end
                        Recent: begin
                            total_outer <= total_outer + 18'(beat_hits);
                            if (beat_index == 3) begin
                                if (expected_last) state <= Classify;
                                else begin
                                    rows_left <= rows_left - 13'd1;
                                    row_has_sink <= 0;
                                    row_max <= MIN_SCORE;
                                    state <= Sink;
                                end
                            end
                        end
                        default: begin end
                    endcase
                end
            end
            Classify: if (ratio_done) begin
                streaming <= ratio_streaming;
                state <= Hold;
            end
            Drain: if (in_valid && in_last) state <= Hold;
            Hold: if (out_ready) state <= Idle;
            default: begin out_error <= 1; state <= Hold; end
        endcase
    end
endmodule

/* verilator lint_off DECLFILENAME */
// A configured classifier consumes the selected core's complete score stream.
module tri_oracle_core_head450 (
    input logic clk, rst_n,
    input logic [394:0] request,
    output logic [72:0] response
);
    wire cfg_valid, in_valid, out_ready, in_last;
    wire [31:0] cfg_tag, cfg_alpha, in_tag;
    wire [12:0] cfg_rows;
    wire [7:0] cfg_ratio_num, cfg_ratio_den, in_lanes;
    wire [1:0] in_region;
    wire [255:0] in_scores;
    wire cfg_ready, in_ready, out_valid, out_error, out_streaming;
    wire [31:0] out_tag;
    wire [17:0] out_inner, out_outer;
    assign {cfg_valid, in_valid, out_ready, cfg_tag, cfg_alpha, cfg_rows,
            cfg_ratio_num, cfg_ratio_den, in_last, in_tag, in_region, in_lanes, in_scores} = request;
    assign response = {cfg_ready, in_ready, out_valid, out_error, out_streaming,
                       out_tag, out_inner, out_outer};
    tri_oracle_attention_head_classifier410 #(.SERIAL_RATIO(1), .SHARED_CONFIG(1)) classifier (.*);
endmodule

// Broadcast payload wires, but gate the three handshake controls to one core.
module tri_oracle_cluster_head450 (
    input logic [396:0] request,
    output logic [72:0] response,
    output logic [1579:0] core_requests,
    input logic [291:0] core_responses
);
    wire [1:0] owner = request[396:395];
    wire [72:0] results[4];
    for (genvar core=0; core<4; core++) begin : owners
        assign core_requests[395*core+:395] = {
            owner==2'(core) ? request[394:392] : 3'b0, request[391:0]
        };
        assign results[core] = core_responses[73*core+:73];
    end
    assign response = results[owner];
endmodule
/* verilator lint_on DECLFILENAME */
