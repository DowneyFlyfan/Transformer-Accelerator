`timescale 1ns/1ps

// Extend the legacy converter without changing its nonnegative-shift interface.
// right=1 scales by 2^-shift, otherwise by 2^shift; both round ties away.
module tri_oracle_attention_projection_scale_bidirectional (
    input logic signed [31:0] accumulator,
    input logic scale_right,
    input logic [4:0] scale_shift,
    output logic signed [7:0] projection_code
);
    logic [31:0] magnitude, rounded_magnitude;
    logic signed [31:0] legacy_accumulator;
    logic [4:0] legacy_shift;

    always_comb begin
        magnitude = accumulator[31] ? -$unsigned(accumulator) : $unsigned(accumulator);
        rounded_magnitude = magnitude;
        legacy_accumulator = accumulator;
        legacy_shift = scale_shift;
        if (scale_right && scale_shift != 0) begin
            // Division by odd 65535 has half-integer decision thresholds.
            // Rounding magnitude/2^r to an integer first therefore preserves
            // every final nearest/ties-away decision, without double rounding.
            rounded_magnitude = (magnitude >> scale_shift) +
                                32'(magnitude[scale_shift - 5'd1]);
            legacy_accumulator = accumulator[31] ? -$signed(rounded_magnitude) :
                                                   $signed(rounded_magnitude);
            legacy_shift = '0;
        end
    end

    tri_oracle_attention_projection_scale legacy (
        .accumulator(legacy_accumulator), .scale_shift(legacy_shift), .projection_code
    );
endmodule
