`timescale 1ns/1ps
module tri_oracle_snzv_predictor_tb;
    reg clk = 0;
    always #5 clk = ~clk;
    reg rst_n = 0, in_valid = 0, out_ready = 1;
    reg [31:0] norm_activations;
    reg [11:0] gate_weight_signs, up_weight_signs;
    wire in_ready, out_valid;
    wire [3:0] outlier_mask;
    wire [2:0] gate_nearzero_mask, up_nearzero_mask, skip_mask;
    tri_oracle_snzv_predictor #(.LANES(4), .OUTPUTS(3)) dut (.*);
    initial begin
        norm_activations = 0;
        gate_weight_signs = 0;
        up_weight_signs = 0;
        repeat (2) @(negedge clk);
        rst_n = 1;
        norm_activations[0 +: 8] = 8'sd4;
        norm_activations[8 +: 8] = -8'sd4;
        norm_activations[16 +: 8] = 8'sd5;
        norm_activations[24 +: 8] = -8'sd5;
        gate_weight_signs = {4'b0110,4'b1010,4'b0110};
        up_weight_signs = {4'b0101,4'b0110,4'b0110};
        in_valid = 1;
        @(posedge clk); #1;
        if (!out_valid || outlier_mask !== 4'b1111 ||
            gate_nearzero_mask !== 3'b101 ||
            up_nearzero_mask !== 3'b011 || skip_mask !== 3'b001)
            $fatal(1, "small-near-zero-value prediction mismatch: outlier=%b gate=%b up=%b skip=%b",
                   outlier_mask, gate_nearzero_mask, up_nearzero_mask, skip_mask);
        @(negedge clk); in_valid = 0; out_ready = 0;
        @(posedge clk); #1;
        if (!out_valid || in_ready || skip_mask !== 3'b001)
            $fatal(1, "small-near-zero-value predictor backpressure failed");
        @(negedge clk); out_ready = 1;
        norm_activations = 0; in_valid = 1;
        @(posedge clk); #1;
        if (!out_valid || outlier_mask !== 0 || skip_mask !== 0)
            $fatal(1, "no-outlier case must not predict skips");
        $display("PASS: outlier signs, gate/up intersection, no-outlier, backpressure");
        $finish;
    end
endmodule
