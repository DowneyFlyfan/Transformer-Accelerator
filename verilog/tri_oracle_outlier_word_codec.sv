`timescale 1ns/1ps

// Each strip stores eight outlier flags and eight signs. A lane is inactive,
// positive, or negative, so five lanes fit in one byte (3^5 = 243).
// Eight bytes hold five strips without depending on the outlier rate.
module tri_oracle_outlier_word_codec (
    input logic [79:0] encode_metadata,
    output logic [63:0] encoded,
    input logic [63:0] decode_word,
    input logic [2:0] decode_strip,
    output logic [15:0] decoded_metadata
);
    function automatic logic [7:0] digit(input logic [79:0] metadata, input int lane);
        int offset;
        offset = 16*(lane/8) + lane%8;
        return !metadata[offset] ? 8'd0 : metadata[offset+8] ? 8'd2 : 8'd1;
    endfunction

    function automatic logic [255:0] digit_mask(input int place, input bit negative);
        logic [255:0] mask;
        int trit;
        mask = '0;
        for (int code = 0; code < 243; code++) begin
            trit = (code/place) % 3;
            mask[code] = negative ? trit == 2 : trit != 0;
        end
        return mask;
    endfunction

    for (genvar byte_index = 0; byte_index < 8; byte_index++) begin : encode_bytes
        localparam int Lane = 5*byte_index;
        assign encoded[8*byte_index+:8] =
            digit(encode_metadata, Lane) + 8'd3 * digit(encode_metadata, Lane+1) +
            8'd9 * digit(encode_metadata, Lane+2) + 8'd27 * digit(encode_metadata, Lane+3) +
            8'd81 * digit(encode_metadata, Lane+4);
    end

    logic [2:0] first_byte, first_lane;
    logic [71:0] padded_word;
    logic [23:0] selected_bytes;
    logic [14:0] outliers, signs;
    always_comb begin
        case (decode_strip)
            3'd0: {first_byte, first_lane} = {3'd0, 3'd0};
            3'd1: {first_byte, first_lane} = {3'd1, 3'd3};
            3'd2: {first_byte, first_lane} = {3'd3, 3'd1};
            3'd3: {first_byte, first_lane} = {3'd4, 3'd4};
            default: {first_byte, first_lane} = {3'd6, 3'd2};
        endcase
    end
    assign padded_word = {8'd0, decode_word};
    assign selected_bytes = padded_word[8*first_byte+:24];
    for (genvar lane = 0; lane < 15; lane++) begin : decode_lanes
        localparam int Place = 3**(lane%5);
        localparam logic [255:0] Active = digit_mask(Place, 0);
        localparam logic [255:0] Negative = digit_mask(Place, 1);
        logic [7:0] code;
        assign code = selected_bytes[8*(lane/5)+:8];
        assign outliers[lane] = Active[code];
        assign signs[lane] = Negative[code];
    end
    assign decoded_metadata = decode_strip < 3'd5 ?
        {signs[4'(first_lane)+:8], outliers[4'(first_lane)+:8]} : 16'd0;
endmodule
