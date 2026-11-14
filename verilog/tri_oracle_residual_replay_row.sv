`timescale 1ns/1ps

// A 256-bit bank row holds eight 29-bit bypass values and their two-bit
// rounding corrections. The producer supplies the direct 16-bit rounding.
module tri_oracle_residual_replay_row (
    input logic [231:0] write_bypass,
    input logic [127:0] write_normalization,
    output logic [23:0] write_padding,
    input logic [231:0] read_bypass,
    input logic [23:0] read_padding,
    output logic [127:0] read_normalization
);
    function automatic logic signed [15:0] round_to_q13(input logic signed [28:0] value);
        logic signed [15:0] floor_code;
        logic round_up;
        floor_code = $signed(value[28:13]);
        round_up = value[12] && (!value[28] || (|value[11:0]));
        return floor_code + 16'(round_up && floor_code != 16'sd32767);
    endfunction

    assign write_padding[23:16] = 8'd0;
    for (genvar lane=0; lane<8; lane++) begin : lanes
        wire signed [15:0] write_rounded = round_to_q13($signed(write_bypass[29*lane +: 29]));
        wire signed [15:0] read_rounded = round_to_q13($signed(read_bypass[29*lane +: 29]));
        wire signed [15:0] direct = write_normalization[16*lane +: 16];
        wire signed [1:0] correction = read_padding[2*lane +: 2];
        // The coarser rounded value differs from the direct value by at
        // most one code, including when either result saturates.
        assign write_padding[2*lane +: 2] = direct > write_rounded ? 2'b01 :
                                             direct < write_rounded ? 2'b11 : 2'b00;
        assign read_normalization[16*lane +: 16] = read_rounded + 16'(correction);
    end
endmodule
