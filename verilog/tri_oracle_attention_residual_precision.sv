`timescale 1ns/1ps

// Preserve the incoming residual until after adding the attention projection.
// projection_shift expresses the signed projection in units of 2^-26.
module tri_oracle_attention_residual_precision (
    input logic [279:0] residual_q32,
    input logic [63:0] projection_codes,
    input logic [4:0] projection_shift,
    output logic [231:0] bypass_q26,
    output logic [127:0] result_q13
);
    for (genvar lane = 0; lane < 8; lane++) begin : lanes
        wire signed [34:0] residual = residual_q32[35*lane +: 35];
        wire signed [7:0] projection = projection_codes[8*lane +: 8];
        // The largest shift is 37. The signed 46-bit sum also covers
        // the residual at both projection extremes.
        wire signed [45:0] projected = (46'(projection) <<< projection_shift) <<< 6;
        wire signed [45:0] sum_q32 = 46'(residual) + projected;
        wire signed [39:0] floor_q26 = $signed(sum_q32[45:6]);
        wire signed [26:0] floor_q13 = $signed(sum_q32[45:19]);
        wire round_q26 = sum_q32[5] && (!sum_q32[45] || (|sum_q32[4:0]));
        wire round_q13 = sum_q32[18] && (!sum_q32[45] || (|sum_q32[17:0]));

        assign bypass_q26[29*lane +: 29] =
            floor_q26 >= 40'sd268435455 ? 29'h0fffffff :
            floor_q26 < -40'sd268435456 ? 29'h10000000 : floor_q26[28:0] + 29'(round_q26);
        assign result_q13[16*lane +: 16] =
            floor_q13 >= 27'sd32767 ? 16'h7fff :
            floor_q13 < -27'sd32768 ? 16'h8000 : floor_q13[15:0] + 16'(round_q13);
    end
endmodule
