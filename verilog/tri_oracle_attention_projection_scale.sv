`timescale 1ns/1ps

// Convert one signed attention accumulator to the projection operand format.
// The softmax probability denominator is 65535. Scale by 2^shift, round to
// nearest and saturate to signed 8 bits.
module tri_oracle_attention_projection_scale (
    input logic signed [31:0] accumulator,
    input logic [4:0] scale_shift,
    output logic signed [7:0] projection_code
);
    logic [31:0] magnitude, largest_unshifted;
    logic [22:0] scaled;
    logic [23:0] biased;
    logic [7:0] high_word;
    logic [16:0] folded;
    logic [7:0] quotient;

    always_comb begin
        magnitude = accumulator[31] ? -$unsigned(accumulator) : $unsigned(accumulator);
        largest_unshifted = 32'd8388607 >> scale_shift;
        scaled = 23'(magnitude) << scale_shift;
        biased = {1'b0, scaled} + 24'd32767;

        // 65536 = 65535 + 1, so folding the high byte into the low word
        // leaves a remainder that needs at most one quotient correction.
        high_word = biased[23:16];
        folded = {1'b0, biased[15:0]} + 17'(high_word);
        quotient = high_word + 8'(folded >= 17'd65535);

        // Any discarded bit implies a scaled magnitude of at least 2^23,
        // already beyond the round-to-128 threshold on either sign.
        if (magnitude > largest_unshifted || quotient >= 8'd128)
            projection_code = accumulator[31] ? 8'sh80 : 8'sh7f;
        else
            projection_code = accumulator[31] ? -$signed(quotient) : $signed(quotient);
    end
endmodule
