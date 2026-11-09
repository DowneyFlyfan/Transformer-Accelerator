`timescale 1ns/1ps
module tri_oracle_strip_predictor_width_tb;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,in_valid=0;
    reg [7:0] a8=0;
    reg [31:0] a32=0;
    wire ready8,ready32,valid8,valid32,error8,error32;
    wire gate8,gate32,up8,up32,skip8,skip32;
    wire [1:0] count8,count32;
    wire legacy_ready8,legacy_ready32,legacy_valid8,legacy_valid32;
    wire legacy_out8,legacy_out32,legacy_gate8,legacy_gate32,legacy_up8,legacy_up32,legacy_skip8,legacy_skip32;
    tri_oracle_snzv_predictor #(.ACT_W(8),.LANES(1),.OUTPUTS(1),.THREE_SIGMA(768)) legacy_narrow (
        .clk(clk),.rst_n(rst_n),.in_valid(in_valid),.out_ready(1'b1),
        .norm_activations(a8),.gate_weight_signs(1'b0),.up_weight_signs(1'b0),
        .in_ready(legacy_ready8),.out_valid(legacy_valid8),.outlier_mask(legacy_out8),
        .gate_nearzero_mask(legacy_gate8),.up_nearzero_mask(legacy_up8),.skip_mask(legacy_skip8));
    tri_oracle_snzv_predictor #(.ACT_W(32),.LANES(1),.OUTPUTS(1),.THREE_SIGMA(768)) legacy_wide (
        .clk(clk),.rst_n(rst_n),.in_valid(in_valid),.out_ready(1'b1),
        .norm_activations(a32),.gate_weight_signs(1'b0),.up_weight_signs(1'b0),
        .in_ready(legacy_ready32),.out_valid(legacy_valid32),.outlier_mask(legacy_out32),
        .gate_nearzero_mask(legacy_gate32),.up_nearzero_mask(legacy_up32),.skip_mask(legacy_skip32));
    tri_oracle_strip_predictor #(.ACT_W(8),.LANES(1),.OUTPUTS(1),.MAX_STRIPS(2)) narrow (
        .clk(clk),.rst_n(rst_n),.in_valid(in_valid),.in_last(1'b1),.out_ready(1'b1),
        .norm_activations(a8),.gate_weight_signs(1'b0),.up_weight_signs(1'b0),
        .in_ready(ready8),.out_valid(valid8),.out_error(error8),
        .gate_nearzero_mask(gate8),.up_nearzero_mask(up8),.skip_mask(skip8),.outlier_count(count8)
    );
    tri_oracle_strip_predictor #(.ACT_W(32),.LANES(1),.OUTPUTS(1),.MAX_STRIPS(2)) wide (
        .clk(clk),.rst_n(rst_n),.in_valid(in_valid),.in_last(1'b1),.out_ready(1'b1),
        .norm_activations(a32),.gate_weight_signs(1'b0),.up_weight_signs(1'b0),
        .in_ready(ready32),.out_valid(valid32),.out_error(error32),
        .gate_nearzero_mask(gate32),.up_nearzero_mask(up32),.skip_mask(skip32),.outlier_count(count32)
    );
    task automatic check(input [1:0] expected_wide,input bit expected_gate);
        begin
            @(posedge clk);#1;
            if(!ready8 || !ready32 || !valid8 || !valid32 || error8 || error32 ||
               gate8 || gate32!==expected_gate || up8 || up32 || skip8 || skip32)
                $fatal(1,"width-parameter result protocol failed");
            if({legacy_ready8,legacy_ready32,legacy_valid8,legacy_valid32,legacy_out8,legacy_out32,
                legacy_gate8,legacy_gate32,legacy_up8,legacy_up32,legacy_skip8,legacy_skip32}
                !=={4'b1111,1'b0,expected_wide[0],1'b0,expected_gate,4'b0000})
                $fatal(1,"legacy threshold-width or signed gate result mismatch");
            // Neither 8-bit magnitude can exceed raw threshold 768. A
            // 32-bit minimum needs a 33-bit absolute value before comparison.
            if(count8!==2'd0 || count32!==expected_wide)
                $fatal(1,"threshold/absolute-value width mismatch: narrow=%0d wide=%0d",count8,count32);
        end
    endtask
    initial begin
        repeat(2) @(negedge clk);rst_n=1;in_valid=1;
        a8=8'h80;a32=32'h80000000;check(1,1);
        @(negedge clk);a8=8'h7f;a32=32'd769;check(1,0);
        @(negedge clk);a32=32'd768;check(0,0);
        $display("PASS: streaming and legacy8/32-bit threshold comparison and minimum signed absolute value");
        $finish;
    end
    initial begin #1000;$fatal(1,"watchdog timeout");end
endmodule
