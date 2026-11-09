`timescale 1ns/1ps
module tri_oracle_head_predictor_tb;
    reg clk = 0;
    always #5 clk = ~clk;
    reg rst_n = 0, in_valid = 0, out_ready = 1;
    reg signed [31:0] sink_scores, inner_scores, outer_scores;
    wire in_ready, out_valid, streaming_head;
    wire [2:0] inner_intensity, outer_intensity;
    tri_oracle_head_predictor #(.TILE_N(4), .ALPHA(2)) dut (.*);
    task automatic run_case(input [31:0] inner, input [31:0] outer,
                            input [2:0] want_inner, input [2:0] want_outer,
                            input want_streaming);
        begin
            @(negedge clk);
            sink_scores = {8'd7,8'd8,8'd9,8'd10};
            inner_scores = inner;
            outer_scores = outer;
            in_valid = 1;
            @(posedge clk); #1;
            if (!out_valid || inner_intensity !== want_inner ||
                outer_intensity !== want_outer || streaming_head !== want_streaming)
                $fatal(1, "head prediction mismatch: inner=%0d outer=%0d SH=%0d",
                       inner_intensity, outer_intensity, streaming_head);
            @(negedge clk);
            in_valid = 0;
        end
    endtask
    initial begin
        sink_scores = 0; inner_scores = 0; outer_scores = 0;
        repeat (2) @(negedge clk);
        rst_n = 1;
        run_case({8'd0,8'd0,8'd10,8'd9}, 32'd0, 2, 0, 0);
        run_case({8'd0,8'd0,8'd0,8'd9}, {8'd0,8'd9,8'd10,8'd9}, 1, 3, 1);
        run_case({8'd0,8'd0,8'd0,8'd9}, {8'd0,8'd0,8'd0,8'd9}, 1, 1, 0);
        // Hold a new valid result under output backpressure.
        @(negedge clk); in_valid = 1;
        @(posedge clk); #1;
        if (!out_valid) $fatal(1, "head predictor did not accept held output");
        @(negedge clk); in_valid = 0; out_ready = 0;
        @(posedge clk); #1;
        if (!out_valid || in_ready || inner_intensity !== 1 || outer_intensity !== 1)
            $fatal(1, "head predictor backpressure failed");
        @(negedge clk); out_ready = 1;
        @(posedge clk); #1;
        if (out_valid) $fatal(1, "head predictor did not retire output");
        $display("PASS: head predictor retrieval, streaming, tie, backpressure");
        $finish;
    end
endmodule
