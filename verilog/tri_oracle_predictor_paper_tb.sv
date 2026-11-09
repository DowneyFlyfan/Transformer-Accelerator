`timescale 1ns/1ps
// Fig31.6.5: one-sided post-SiLU gate estimate, interval up estimate, AND.
// Threshold0/inclusive gate and symmetric up window are explicit local choices.
module tri_oracle_predictor_paper_tb;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,in_valid=0,out_ready=0;
    reg [127:0] norm_activations=0;
    reg [31:0] gate_weight_signs=0,up_weight_signs=0;
    wire ready_s,ready_l,ready_c,valid_s,valid_l,valid_c,error_s,error_c;
    wire [3:0] gate_s,up_s,skip_s,gate_l,up_l,skip_l,gate_c,up_c,skip_c;
    wire [7:0] outliers_l;
    wire [4:0] count_s,count_c;
    tri_oracle_strip_predictor #(.OUTPUTS(4),.MAX_STRIPS(2)) streaming (
        .clk(clk),.rst_n(rst_n),.in_valid(in_valid),.in_last(1'b1),.out_ready(out_ready),
        .norm_activations(norm_activations),.gate_weight_signs(gate_weight_signs),.up_weight_signs(up_weight_signs),
        .in_ready(ready_s),.out_valid(valid_s),.out_error(error_s),.outlier_count(count_s),
        .gate_nearzero_mask(gate_s),.up_nearzero_mask(up_s),.skip_mask(skip_s));
    tri_oracle_snzv_predictor #(.ACT_W(16),.OUTPUTS(4),.THREE_SIGMA(768)) legacy (
        .clk(clk),.rst_n(rst_n),.in_valid(in_valid),.out_ready(out_ready),
        .norm_activations(norm_activations),.gate_weight_signs(gate_weight_signs),.up_weight_signs(up_weight_signs),
        .in_ready(ready_l),.out_valid(valid_l),.outlier_mask(outliers_l),
        .gate_nearzero_mask(gate_l),.up_nearzero_mask(up_l),.skip_mask(skip_l));
    tri_oracle_strip_predictor #(.OUTPUTS(4),.MAX_STRIPS(2),.GATE_THRESHOLD(-4)) confident (
        .clk(clk),.rst_n(rst_n),.in_valid(in_valid),.in_last(1'b1),.out_ready(out_ready),
        .norm_activations(norm_activations),.gate_weight_signs(gate_weight_signs),.up_weight_signs(up_weight_signs),
        .in_ready(ready_c),.out_valid(valid_c),.out_error(error_c),.outlier_count(count_c),
        .gate_nearzero_mask(gate_c),.up_nearzero_mask(up_c),.skip_mask(skip_c));
    task automatic check;
        if({valid_s,valid_l,valid_c,error_s,error_c,count_s,count_c,outliers_l}
            !=={3'b111,2'b00,5'd8,5'd8,8'hff}) $fatal(1,"paper predictor result protocol mismatch");
        if({gate_s,up_s,skip_s,gate_l,up_l,skip_l}!=={4'hd,4'h7,4'h5,4'hd,4'h7,4'h5})
            $fatal(1,"gate branch must include negative estimates; up remains an interval; masks must AND");
        if({gate_c,up_c,skip_c}!=={4'h9,4'h7,4'h1}) $fatal(1,"independent signed gate threshold mismatch");
    endtask
    initial begin
        repeat(2) @(negedge clk);rst_n=1;
        norm_activations={8{16'd1024}};
        // Rows: gate negative/positive/zero/negative; up zero/zero/zero/negative.
        gate_weight_signs={8'hff,8'h55,8'h00,8'hff};
        up_weight_signs={8'hff,8'h55,8'h55,8'h55};
        in_valid=1;@(posedge clk);#1;check();
        @(negedge clk);in_valid=0;
        repeat(3) begin @(posedge clk);#1;check();end
        @(negedge clk);out_ready=1;
        @(negedge clk);in_valid=1;norm_activations=0;
        @(posedge clk);#1;
        if({gate_s,up_s,skip_s,gate_l,up_l,skip_l,gate_c,up_c,skip_c}!==36'd0)
            $fatal(1,"no-outlier input must not predict a skip");
        $display("PASS: paper one-sided gate versus interval up tests, signed threshold, mask intersection, no-outlier and stalled results");
        $finish;
    end
    initial begin #10000;$fatal(1,"paper predictor watchdog");end
endmodule
