module tb;
    logic signed [7:0] a, b;
    wire signed [15:0] result;
    logic signed [15:0] expected;
    tri_oracle_booth8 dut(a, b, result);

    initial begin
        for (int i=-128; i<128; i++) begin
            for (int j=-128; j<128; j++) begin
                a = 8'(i);
                b = 8'(j);
                expected = 16'(i * j);
                #1;
                if (result !== expected)
                    $fatal(1, "BOOTH8_MISMATCH %0d * %0d got=%0d expected=%0d", i, j, result, expected);
            end
        end
        $display("BOOTH8_EXHAUSTIVE_PASS cases=65536");
        $finish;
    end
endmodule
