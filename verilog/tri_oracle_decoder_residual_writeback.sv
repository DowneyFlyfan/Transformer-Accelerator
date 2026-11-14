`timescale 1ns/1ps

// The bypass is signed Q26. down_shift converts a signed 32-bit
// feed-forward accumulator to the same units. Round only the final sum.
module tri_oracle_decoder_residual_writeback (
    input logic [231:0] residual_q26,
    input logic [255:0] down_codes,
    input logic [4:0] down_shift,
    output logic [127:0] result_q13
);
    function automatic logic [15:0] add_lane(
        input logic signed [28:0] residual,
        input logic signed [31:0] down,
        input logic [4:0] shift
    );
        // A signed 32-bit accumulator shifted up to 31 places, plus
        // a signed 29-bit bypass, fits in 64 bits.
        logic signed [63:0] projected, combined;
        logic signed [50:0] floor_code;
        logic round_up;

        projected = 64'(down) <<< shift;
        combined = 64'(residual) + projected;
        floor_code = $signed(combined[63:13]);
        round_up = combined[12] && (!combined[63] || (|combined[11:0]));

        // The rounding increment is at most one. At either saturation
        // boundary, a floor beyond the limit yields the same clipped result.
        if (floor_code >= 51'sd32767) return 16'h7fff;
        if (floor_code < -51'sd32768) return 16'h8000;
        return floor_code[15:0] + 16'(round_up);
    endfunction

    always_comb begin
        for (int lane = 0; lane < 8; lane++) begin
            result_q13[16*lane +: 16] = add_lane(
                $signed(residual_q26[29*lane +: 29]),
                $signed(down_codes[32*lane +: 32]),
                down_shift
            );
        end
    end
endmodule
