`timescale 1ns/1ps
// Scaled proportional-softmax normalization for Tri-Oracle, Fig. 31.6.3.
// exp_scores are quantized exp(attention score) values from an upstream
// exponential stage. Multiplying each by merged token size implements
// exp(score + ln(size)) without an explicit logarithm unit.
module tri_oracle_proportional_normalizer #(
    parameter integer N = 3,
    parameter integer EXP_W = 8,
    parameter integer SIZE_W = 4,
    parameter integer PROB_W = 8,
    parameter integer PRODUCT_W = EXP_W + SIZE_W,
    parameter integer SUM_W = PRODUCT_W + $clog2(N+1)
) (
    input  wire                            clk,
    input  wire                            rst_n,
    input  wire                            in_valid,
    output wire                            in_ready,
    input  wire [N*EXP_W-1:0]              exp_scores,
    input  wire [N*SIZE_W-1:0]             token_sizes,
    input  wire [N-1:0]                    causal_mask,
    output reg                             out_valid,
    input  wire                            out_ready,
    output reg [N*PROB_W-1:0]             probabilities
);
    localparam [PROB_W-1:0] PROB_MAX = {PROB_W{1'b1}};
    reg [PRODUCT_W-1:0] weighted [0:N-1];
    reg [SUM_W-1:0] denominator;
    reg [N*PROB_W-1:0] next_probabilities;
    reg [SUM_W+PROB_W-1:0] numerator;
    reg [SUM_W+PROB_W-1:0] denominator_ext;
    integer i;
    always @* begin
        denominator = {SUM_W{1'b0}};
        next_probabilities = {(N*PROB_W){1'b0}};
        numerator = {(SUM_W+PROB_W){1'b0}};
        denominator_ext = {(SUM_W+PROB_W){1'b0}};
        for (i=0; i<N; i=i+1) begin
            weighted[i] = causal_mask[i] ?
                exp_scores[i*EXP_W +: EXP_W] * token_sizes[i*SIZE_W +: SIZE_W] :
                {PRODUCT_W{1'b0}};
            denominator = denominator + {{(SUM_W-PRODUCT_W){1'b0}},weighted[i]};
        end
        if (denominator != 0) begin
            denominator_ext = {{PROB_W{1'b0}},denominator};
            for (i=0; i<N; i=i+1) begin
                numerator = weighted[i] * PROB_MAX + (denominator_ext >> 1);
                next_probabilities[i*PROB_W +: PROB_W] =
                    PROB_W'(numerator / denominator_ext);
            end
        end
    end
    assign in_ready = !out_valid || out_ready;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            out_valid <= 1'b0;
            probabilities <= {(N*PROB_W){1'b0}};
        end else if (in_ready) begin
            out_valid <= in_valid;
            if (in_valid) probabilities <= next_probabilities;
        end
    end
endmodule
