`timescale 1ns/1ps
// Head max/intensity and type decision from the paper's Fig. 31.6.4.
// A row has four eight-score beats per sink, inner, and recent tile.
// Lane masks exclude causal padding. Alpha is expressed in integer score
// units. The ratio is configurable because the paper does not publish it.
// Error retires only after the malformed packet's LAST. If configuration
// fails before input starts, cancel any held input on the tagged error.
module tri_oracle_attention_head_classifier410 (
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
    logic [31:0] tag, alpha;
    logic [12:0] rows, row_index;
    logic [7:0] ratio_num, ratio_den;
    logic [1:0] beat_index, expected_region;
    logic row_has_sink, expected_last, malformed, streaming;
    logic signed [31:0] row_max, lane_max [0:7], pair_max [0:3], beat_max, updated_max;
    logic signed [33:0] cutoff;
    logic [7:0] hits;
    logic [1:0] pair_hits [0:3];
    logic [3:0] beat_hits;
    logic [17:0] total_inner, total_outer;
    logic [25:0] inner_product, outer_product;

    function automatic logic signed [31:0] maximum(
        input logic signed [31:0] left, right
    );
        return left > right ? left : right;
    endfunction

    for (genvar lane = 0; lane < 8; lane++) begin : lanes
        assign lane_max[lane] = in_lanes[lane] ? $signed(in_scores[lane*32 +: 32]) : MIN_SCORE;
        assign hits[lane] = in_lanes[lane] &&
            $signed({{2{in_scores[lane*32+31]}}, in_scores[lane*32 +: 32]}) > cutoff;
    end
    for (genvar pair_index = 0; pair_index < 4; pair_index++) begin : pairs
        assign pair_max[pair_index] = maximum(lane_max[2*pair_index], lane_max[2*pair_index+1]);
        assign pair_hits[pair_index] = 2'(hits[2*pair_index]) + 2'(hits[2*pair_index+1]);
    end
    assign beat_max = maximum(maximum(pair_max[0], pair_max[1]), maximum(pair_max[2], pair_max[3]));
    assign updated_max = maximum(row_max, beat_max);
    assign beat_hits = (4'(pair_hits[0]) + 4'(pair_hits[1])) + (4'(pair_hits[2]) + 4'(pair_hits[3]));

    assign cfg_ready = state == Idle;
    assign in_ready = state == Sink || state == Inner || state == Recent || state == Drain;
    assign expected_region = state == Sink ? 2'd0 : state == Inner ? 2'd1 : 2'd2;
    assign expected_last = state == Recent && beat_index == 3 && row_index + 13'd1 == rows;
    assign malformed = in_tag != tag || in_region != expected_region || in_last != expected_last;
    assign out_valid = state == Hold;
    assign out_tag = tag;
    assign out_streaming = !out_error && streaming;
    assign out_inner = out_error ? '0 : total_inner;
    assign out_outer = out_error ? '0 : total_outer;
    assign inner_product = 26'(total_inner) * 26'(ratio_num);
    assign outer_product = 26'(total_outer) * 26'(ratio_den);

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= Idle;
            tag <= '0; alpha <= '0; rows <= '0; row_index <= '0;
            ratio_num <= '0; ratio_den <= '0; beat_index <= '0;
            row_has_sink <= 0; row_max <= MIN_SCORE; cutoff <= '0;
            total_inner <= '0; total_outer <= '0;
            out_error <= 0; streaming <= 0;
        end else case (state)
            Idle: if (cfg_valid) begin
                tag <= cfg_tag; alpha <= cfg_alpha; rows <= cfg_rows;
                ratio_num <= cfg_ratio_num; ratio_den <= cfg_ratio_den;
                row_index <= '0; beat_index <= '0;
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
                                    row_index <= row_index + 13'd1;
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
            Classify: begin
                streaming <= outer_product > inner_product;
                state <= Hold;
            end
            Drain: if (in_valid && in_last) state <= Hold;
            Hold: if (out_ready) state <= Idle;
            default: begin out_error <= 1; state <= Hold; end
        endcase
    end
endmodule
