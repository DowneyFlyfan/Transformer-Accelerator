`timescale 1ns/1ps
// Eight pre-affine normalized values with eight fractional bits per value.
module tri_oracle_wac_outlier_sign (
    input  logic valid,
    input  logic [127:0] normalized,
    output logic response_valid,
    output logic [7:0] outliers, negative
);
    localparam logic signed [15:0] ThreeSigma = 16'sd768;

    assign response_valid = valid;
    for (genvar lane = 0; lane < 8; lane++) begin : metadata
        wire signed [15:0] value = normalized[16*lane +: 16];
        assign outliers[lane] = valid && (value > ThreeSigma || value < -ThreeSigma);
        assign negative[lane] = valid && value[15];
    end
endmodule
