`timescale 1ns/1ps

// The down-weight exponent can vary among output channels. Each shift
// converts that channel's signed 32-bit sum into the bypass's Q26 units.
module tri_oracle_decoder_residual_writeback_per_lane (
    input logic [231:0] residual_q26,
    input logic [255:0] down_codes,
    input logic [39:0] lane_shifts,
    output logic [127:0] result_q13
);
    for (genvar lane = 0; lane < 8; lane++) begin : writes
        // Use the verified scalar rounding and saturation for the active
        // lane. The other seven lane inputs are constants.
        logic [127:0] lane_result;
        tri_oracle_decoder_residual_writeback scalar (
            .residual_q26({203'd0, residual_q26[29*lane +: 29]}),
            .down_codes({224'd0, down_codes[32*lane +: 32]}),
            .down_shift(lane_shifts[5*lane +: 5]),
            .result_q13(lane_result)
        );
        assign result_q13[16*lane +: 16] = lane_result[15:0];
    end
endmodule
