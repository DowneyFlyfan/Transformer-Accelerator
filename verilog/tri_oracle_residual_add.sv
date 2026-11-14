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
        // 40 bits cover both signed operands even at the largest shift, plus
        // the rounding bias. Negative sums use floor((sum + 2047) / 4096).
        logic signed [39:0] projected, combined, rounded;
        projected = 40'(projection) <<< shift;
        combined = 40'(residual) + projected;
        rounded = (combined + (combined < 0 ? 40'sd2047 : 40'sd2048)) >>> 12;
        if (rounded > 40'sd32767) return 16'h7fff;
        if (rounded < -40'sd32768) return 16'h8000;
        return rounded[15:0];
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
