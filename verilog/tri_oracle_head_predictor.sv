`timescale 1ns/1ps
// Scaled attention head prediction from Tri-Oracle, 2026 IEEE International
// Solid-State Circuits Conference, Fig. 31.6.4.
// Scores for one row's inner/outer attention-sink tiles arrive together.
// Alpha and ratio threshold are parameters because the paper omits their values.
module tri_oracle_head_predictor #(
    parameter integer SCORE_W = 8,
    parameter integer TILE_N = 4,
    parameter integer ALPHA = 4,
    parameter integer RATIO_NUM = 1,
    parameter integer RATIO_DEN = 1,
    parameter integer COUNT_W = $clog2(TILE_N + 1)
) (
    input  wire                         clk,
    input  wire                         rst_n,
    input  wire                         in_valid,
    output wire                         in_ready,
    input  wire signed [SCORE_W*TILE_N-1:0] sink_scores,
    input  wire signed [SCORE_W*TILE_N-1:0] inner_scores,
    input  wire signed [SCORE_W*TILE_N-1:0] outer_scores,
    output reg                          out_valid,
    input  wire                         out_ready,
    output reg                          streaming_head,
    output reg [COUNT_W-1:0]            inner_intensity,
    output reg [COUNT_W-1:0]            outer_intensity
);
    reg signed [SCORE_W-1:0] row_max;
    reg signed [SCORE_W:0] cutoff;
    localparam signed [SCORE_W:0] ALPHA_W = ALPHA[SCORE_W:0];
    reg [COUNT_W-1:0] inner_count;
    reg [COUNT_W-1:0] outer_count;
    integer i;
    always @* begin
        row_max = $signed(sink_scores[0 +: SCORE_W]);
        for (i = 1; i < TILE_N; i = i + 1)
            if ($signed(sink_scores[i*SCORE_W +: SCORE_W]) > row_max)
                row_max = $signed(sink_scores[i*SCORE_W +: SCORE_W]);
        cutoff = $signed({row_max[SCORE_W-1], row_max}) - ALPHA_W;
        inner_count = {COUNT_W{1'b0}};
        outer_count = {COUNT_W{1'b0}};
        for (i = 0; i < TILE_N; i = i + 1) begin
            if ($signed({inner_scores[(i+1)*SCORE_W-1],
                         inner_scores[i*SCORE_W +: SCORE_W]}) > cutoff)
                inner_count = inner_count + 1'b1;
            if ($signed({outer_scores[(i+1)*SCORE_W-1],
                         outer_scores[i*SCORE_W +: SCORE_W]}) > cutoff)
                outer_count = outer_count + 1'b1;
        end
    end
    assign in_ready = !out_valid || out_ready;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            out_valid <= 1'b0;
            streaming_head <= 1'b0;
            inner_intensity <= {COUNT_W{1'b0}};
            outer_intensity <= {COUNT_W{1'b0}};
        end else if (in_ready) begin
            out_valid <= in_valid;
            if (in_valid) begin
                inner_intensity <= inner_count;
                outer_intensity <= outer_count;
                // outer/inner > RATIO_NUM/RATIO_DEN. Avoid division and
                // define the zero-inner case via the same cross product.
                streaming_head <= (outer_count * RATIO_DEN) >
                                  (inner_count * RATIO_NUM);
            end
        end
    end
endmodule
