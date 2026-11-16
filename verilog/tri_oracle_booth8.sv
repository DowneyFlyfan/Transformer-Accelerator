module tri_oracle_booth8(
    input logic signed [7:0] a, b,
    output wire signed [15:0] p
);
    wire [8:0] once = {a[7], a};
    wire [8:0] twice = {a, 1'b0};
    wire [8:0] digits = {b, 1'b0};
    wire [15:0] row [0:3];
    wire [3:0] negate;

    for (genvar index = 0; index < 4; index++) begin : booth
        wire low = digits[2*index];
        wire middle = digits[2*index+1];
        wire high = digits[2*index+2];
        wire single = middle ^ low;
        wire double = !single && (high ^ middle);
        wire [8:0] partial = ((once & {9{single}}) | (twice & {9{double}})) ^ {9{high}};
        assign negate[index] = high;
        // Flipping the sign bit adds 256 before shifting each row.
        assign row[index] = {7'b0, ~partial[8], partial[7:0]} << (2*index);
    end

    // Restore the four row sign offsets and add the Booth negate bits.
    wire [15:0] correction = 16'hab00 | {9'b0, negate[3], 1'b0, negate[2], 1'b0, negate[1], 1'b0, negate[0]};
    function automatic [31:0] compress(input [15:0] u, v, w);
        compress = {(((u & v) | ((u | v) & w)) << 1), (u ^ v ^ w)};
    endfunction
    wire [31:0] first = compress(row[0], row[1], row[2]);
    wire [31:0] second = compress(first[15:0], first[31:16], row[3]);
    wire [31:0] third = compress(second[15:0], second[31:16], correction);
    assign p = third[15:0] + third[31:16];
endmodule
