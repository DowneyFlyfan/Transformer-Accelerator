`timescale 1ns/1ps
module mapped_product_tb;
    logic clk = 0;
    logic enable;
    logic signed [7:0] a, b;
    wire signed [15:0] q;
    logic signed [15:0] expected;
    product dut (.clk(clk), .enable(enable), .a(a), .b(b), .q(q));

    initial begin
        for (int mode=0; mode<2; mode++) begin
            enable = mode == 1;
            for (int i=-128; i<128; i++) begin
                for (int j=-128; j<128; j++) begin
                    a = 8'(i);
                    b = 8'(j);
                    expected = enable ? 16'(i * j) : '0;
                    #1 clk = 1;
                    #1;
                    if (q !== expected)
                        $fatal(1, "MAPPED_PRODUCT_MISMATCH %0d * %0d enable=%b got=%0d expected=%0d",
                               i, j, enable, q, expected);
                    clk = 0;
                end
            end
        end
        $display("MAPPED_PRODUCT_EXHAUSTIVE_PASS cases=131072 enabled=65536 disabled=65536");
        $finish;
    end
endmodule
