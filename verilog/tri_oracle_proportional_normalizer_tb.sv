`timescale 1ns/1ps
module tri_oracle_proportional_normalizer_tb;
    reg clk=0;
    always #5 clk=~clk;
    reg rst_n=0, in_valid=0, out_ready=1;
    reg [23:0] exp_scores;
    reg [11:0] token_sizes;
    reg [2:0] causal_mask;
    wire in_ready, out_valid;
    wire [23:0] probabilities;
    tri_oracle_proportional_normalizer dut (.*);
    task automatic check(input [2:0] mask, input [23:0] expected);
        begin
            @(negedge clk);
            causal_mask=mask;
            in_valid=1;
            @(posedge clk); #1;
            if (!out_valid || probabilities !== expected)
                $fatal(1,"proportional normalization mask=%b got=%h wanted=%h",
                       mask,probabilities,expected);
            @(negedge clk); in_valid=0;
        end
    endtask
    initial begin
        exp_scores={8'd1,8'd4,8'd4};
        token_sizes={4'd2,4'd3,4'd1};
        causal_mask=0;
        repeat (2) @(negedge clk);
        rst_n=1;
        // Weighted values: [4,12,2], denominator 18.
        check(3'b111,{8'd28,8'd170,8'd57});
        // Causal masking leaves [4,0,2], denominator 6.
        check(3'b101,{8'd85,8'd0,8'd170});
        check(3'b000,24'd0);
        // Hold output under backpressure.
        @(negedge clk); in_valid=1; causal_mask=3'b111;
        @(posedge clk); #1;
        @(negedge clk); in_valid=0; out_ready=0;
        @(posedge clk); #1;
        if (!out_valid || in_ready || probabilities !== {8'd28,8'd170,8'd57})
            $fatal(1,"proportional normalizer backpressure failed");
        $display("PASS: token-size weighting, causal mask, zero denominator, backpressure");
        $finish;
    end
endmodule
