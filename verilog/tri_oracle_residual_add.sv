`timescale 1ns/1ps

// Add eight residual values to signed 8-bit projection codes with a shared
// binary scale. The shift expresses each projection code in Q25 units.
// Round the sum to Q13 with ties away from zero, then saturate to signed 16 bits.
module tri_oracle_residual_add (
    input logic [215:0] residual_q25,
    input logic [63:0] projection_codes,
    input logic [4:0] projection_shift,
    output logic [127:0] result_q13
);
    function automatic logic [15:0] add_lane(
        input logic signed [26:0] residual,
        input logic signed [7:0] projection,
        input logic [4:0] shift
    );
        // At shift 31, the negative projection alone can be -2^38.
        // The signed 40-bit sum also covers the residual in that case.
        logic signed [39:0] projected, combined;
        logic signed [27:0] floor_code;
        logic [15:0] rounded;
        logic round_up;

        projected = 40'(projection) <<< shift;
        combined = 40'(residual) + projected;
        floor_code = $signed(combined[39:12]);
        // The low 12 bits are the nonnegative remainder after flooring.
        // Round up above half, or at a tie when the sum is nonnegative.
        round_up = combined[11] && (!combined[39] || (|combined[10:0]));
        rounded = floor_code[15:0] + 16'(round_up);
        // Rounding can increase the floor by at most one, so values beyond
        // these bounds still saturate to the same endpoint.
        if (floor_code >= 28'sd32767) return 16'h7fff;
        if (floor_code < -28'sd32768) return 16'h8000;
        return rounded;
    endfunction

    always_comb begin
        for (int lane = 0; lane < 8; lane++) begin
            result_q13[16*lane +: 16] = add_lane(
                $signed(residual_q25[27*lane +: 27]),
                $signed(projection_codes[8*lane +: 8]),
                projection_shift
            );
        end
    end
endmodule
