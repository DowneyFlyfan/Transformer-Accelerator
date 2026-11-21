`timescale 1ns/1ps

// Exact right conversion: floor(abs(a)/65535), then nearest binary division.
// The original left/zero-shift converter remains an independent unchanged path.
module tri_oracle_attention_projection_scale_quotient_first (
    input logic signed [31:0] accumulator,
    input logic scale_right,
    input logic [4:0] scale_shift,
    output logic signed [7:0] projection_code
);
    logic [31:0] magnitude;
    logic [16:0] folded, floor_quotient, rounded_right;
    logic signed [7:0] legacy_code, right_code;

    tri_oracle_attention_projection_scale legacy (
        .accumulator, .scale_shift, .projection_code(legacy_code)
    );

    always_comb begin
        magnitude = accumulator[31] ? -$unsigned(accumulator) : $unsigned(accumulator);
        folded = {1'b0, magnitude[31:16]} + {1'b0, magnitude[15:0]};
        floor_quotient = {1'b0, magnitude[31:16]} + 17'(folded >= 17'd65535);
        rounded_right = floor_quotient >> scale_shift;
        if (scale_shift != 0 && scale_shift <= 17)
            rounded_right = rounded_right + 17'(floor_quotient[scale_shift - 5'd1]);
        if (rounded_right >= 17'd128)
            right_code = accumulator[31] ? 8'sh80 : 8'sh7f;
        else
            right_code = accumulator[31] ? -$signed(rounded_right[7:0]) : $signed(rounded_right[7:0]);
        projection_code = scale_right && scale_shift != 0 ? right_code : legacy_code;
    end
endmodule
