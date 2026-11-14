`timescale 1ns/1ps
module tri_oracle_attention_score_scale (
    input logic signed [31:0] dot,
    input logic signed [6:0] shift,
    output logic [15:0] score
);
    function automatic logic [15:0] scale_score(input logic signed [31:0] dot, input logic signed [6:0] shift);
        logic [31:0] magnitude;
        logic [63:0] rounded, halfway;
        logic [4:0] amount;
        magnitude = dot[31] ? (~$unsigned(dot) + 32'd1) : $unsigned(dot);
        amount = shift[6] ? 5'(-shift) : shift[4:0];
        if (shift[6]) begin
            halfway = 64'd1 << (amount-1'b1);
            rounded = (64'(magnitude) + halfway - 64'd1 + ((64'(magnitude) >> amount) & 64'd1)) >> amount;
        end else begin
            rounded = 64'(magnitude) << amount;
        end
        if (dot[31]) return rounded >= 64'd32768 ? 16'h8000 : (~16'(rounded) + 16'd1);
        return rounded >= 64'd32767 ? 16'h7fff : 16'(rounded);
    endfunction

    assign score = scale_score(dot, shift);
endmodule
