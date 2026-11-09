`timescale 1ns/1ps
// Scaled strip-wise small-near-zero-value prediction from Tri-Oracle,
// 2026 IEEE International Solid-State Circuits Conference, Fig. 31.6.5.
// Activations are already root-mean-square normalized.
// The paper discloses 3-sigma outliers, sign-only estimation and the
// intersection of the post-SiLU gate and up near-zero masks. Gate prediction
// is one-sided; up prediction is an interval. Zero/inclusive gate threshold
// and the symmetric up interval here are local, unpublished choices.
module tri_oracle_snzv_predictor #(
    parameter integer ACT_W = 8,
    parameter integer LANES = 8,
    parameter integer OUTPUTS = 4,
    parameter integer THREE_SIGMA = 3,
    parameter integer MARGIN_LIMIT = 0,
    parameter integer GATE_THRESHOLD = 0,
    parameter integer COUNT_W = $clog2(LANES + 1)
) (
    input  wire                                 clk,
    input  wire                                 rst_n,
    input  wire                                 in_valid,
    output wire                                 in_ready,
    input  wire [ACT_W*LANES-1:0]               norm_activations,
    input  wire [LANES*OUTPUTS-1:0]             gate_weight_signs,
    input  wire [LANES*OUTPUTS-1:0]             up_weight_signs,
    output reg                                  out_valid,
    input  wire                                 out_ready,
    output reg [LANES-1:0]                      outlier_mask,
    output reg [OUTPUTS-1:0]                    gate_nearzero_mask,
    output reg [OUTPUTS-1:0]                    up_nearzero_mask,
    output reg [OUTPUTS-1:0]                    skip_mask
);
    reg [LANES-1:0] outliers;
    reg [OUTPUTS-1:0] gate_zero;
    reg [OUTPUTS-1:0] up_zero;
    reg [COUNT_W-1:0] outlier_count;
    reg [COUNT_W-1:0] gate_matches;
    reg [COUNT_W-1:0] up_matches;
    reg signed [COUNT_W+1:0] gate_margin;
    reg signed [COUNT_W+1:0] up_margin;
    reg signed [ACT_W-1:0] activation;
    reg signed [ACT_W:0] absolute_activation;
    localparam integer COMPARE_W = ACT_W+1>32 ? ACT_W+1 : 32;
    localparam signed [COMPARE_W-1:0] THREE_SIGMA_W = COMPARE_W'(THREE_SIGMA);
    localparam signed [COUNT_W+1:0] MARGIN_LIMIT_W =
        MARGIN_LIMIT[COUNT_W+1:0];
    localparam signed [COUNT_W+1:0] GATE_THRESHOLD_W = (COUNT_W+2)'(GATE_THRESHOLD);
    integer lane;
    integer channel;
    always @* begin
        outliers = {LANES{1'b0}};
        outlier_count = {COUNT_W{1'b0}};
        for (lane = 0; lane < LANES; lane = lane + 1) begin
            activation = $signed(norm_activations[lane*ACT_W +: ACT_W]);
            absolute_activation = activation < 0 ? -$signed({activation[ACT_W-1], activation}) :
                                                  $signed({activation[ACT_W-1], activation});
            outliers[lane] = COMPARE_W'(absolute_activation) > THREE_SIGMA_W;
            if (outliers[lane]) outlier_count = outlier_count + 1'b1;
        end
        gate_zero = {OUTPUTS{1'b0}};
        up_zero = {OUTPUTS{1'b0}};
        gate_matches = {COUNT_W{1'b0}};
        up_matches = {COUNT_W{1'b0}};
        gate_margin = 0;
        up_margin = 0;
        for (channel = 0; channel < OUTPUTS; channel = channel + 1) begin
            gate_matches = {COUNT_W{1'b0}};
            up_matches = {COUNT_W{1'b0}};
            for (lane = 0; lane < LANES; lane = lane + 1) begin
                if (outliers[lane]) begin
                    if (norm_activations[(lane+1)*ACT_W-1] ==
                        gate_weight_signs[channel*LANES+lane])
                        gate_matches = gate_matches + 1'b1;
                    if (norm_activations[(lane+1)*ACT_W-1] ==
                        up_weight_signs[channel*LANES+lane])
                        up_matches = up_matches + 1'b1;
                end
            end
            gate_margin = ($signed({2'b00, gate_matches}) <<< 1) -
                          $signed({2'b00, outlier_count});
            up_margin = ($signed({2'b00, up_matches}) <<< 1) -
                        $signed({2'b00, outlier_count});
            gate_zero[channel] = (outlier_count != 0) &&
                                 (gate_margin <= GATE_THRESHOLD_W);
            up_zero[channel] = (outlier_count != 0) &&
                               (up_margin >= -MARGIN_LIMIT_W) &&
                               (up_margin <= MARGIN_LIMIT_W);
        end
    end
    assign in_ready = !out_valid || out_ready;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            out_valid <= 1'b0;
            outlier_mask <= {LANES{1'b0}};
            gate_nearzero_mask <= {OUTPUTS{1'b0}};
            up_nearzero_mask <= {OUTPUTS{1'b0}};
            skip_mask <= {OUTPUTS{1'b0}};
        end else if (in_ready) begin
            out_valid <= in_valid;
            if (in_valid) begin
                outlier_mask <= outliers;
                gate_nearzero_mask <= gate_zero;
                up_nearzero_mask <= up_zero;
                skip_mask <= gate_zero & up_zero;
            end
        end
    end
endmodule
