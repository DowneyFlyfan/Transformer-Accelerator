`timescale 1ns/1ps
module score_scale_tb;
    logic signed [31:0] dot;
    logic signed [6:0] shift;
    logic [15:0] score;
    logic [54:0] vectors [5000];
    logic [31:0] random_bits=32'h583184a7;
    int trained_count, checked=0;
    string vectors_path;
    tri_oracle_attention_score_scale dut (.*);

    function automatic logic [15:0] reference_score(input longint signed value, input int signed exponent);
        longint signed numerator, denominator, rounded, remainder, sign;
        sign = value < 0 ? -1 : 1;
        numerator = sign * value;
        denominator = 1;
        if (exponent >= 0) numerator *= (64'sd1 << exponent);
        else denominator = 64'sd1 << -exponent;
        rounded = numerator / denominator;
        remainder = numerator % denominator;
        if (2*remainder > denominator || (2*remainder == denominator && rounded%2 == 1))
            rounded++;
        rounded *= sign;
        if (rounded < -32768) return 16'h8000;
        if (rounded > 32767) return 16'h7fff;
        return 16'(rounded);
    endfunction

    task automatic check(input logic signed [31:0] value, input int exponent, input logic [15:0] expected);
        dot=value;
        shift=7'(exponent);
        #1;
        if (score !== expected)
            $fatal(1,"GROUPED_SCORE_SCALE dot=%0d shift=%0d actual=%h expected=%h",dot,shift,score,expected);
        checked++;
    endtask

    initial begin
        if (!$value$plusargs("VECTORS=%s",vectors_path) ||
            !$value$plusargs("COUNT=%d",trained_count) || trained_count<=0 || trained_count>$size(vectors))
            $fatal(1,"GROUPED_SCORE_SCALE_FIXTURE");
        $readmemh(vectors_path,vectors,0,trained_count-1);
        for (int index=0; index<trained_count; index++)
            check($signed(vectors[index][47:16]), int'($signed(vectors[index][54:48])), vectors[index][15:0]);
        for (int exponent=-31; exponent<=31; exponent++) begin
            for (int value=-128; value<=128; value++)
                check(32'(value),exponent,reference_score(longint'(value),exponent));
            for (int offset=-4; offset<=4; offset++) begin
                int signed edge_value;
                edge_value = 32768 + offset;
                check(edge_value,exponent,reference_score(longint'(edge_value),exponent));
                check(-edge_value,exponent,reference_score(-longint'(edge_value),exponent));
            end
            check(32'sh80000000,exponent,reference_score(-64'sd2147483648,exponent));
            check(32'sh7fffffff,exponent,reference_score(64'sd2147483647,exponent));
            for (int index=0; index<50; index++) begin
                random_bits ^= random_bits << 13;
                random_bits ^= random_bits >> 17;
                random_bits ^= random_bits << 5;
                check($signed(random_bits),exponent,reference_score(longint'($signed(random_bits)),exponent));
            end
        end
        $display("GROUPED_SCORE_SCALE_PASS trained=%0d total=%0d",trained_count,checked);
        $finish;
    end
endmodule
