`timescale 1ns/1ps
module tri_oracle_pe_array_tb;
    parameter integer NO_STALL=0;
    localparam LINES=32, LANES=8, DATA_W=8, SUM_W=19, CASES=300;
    reg clk=0;
    always #5 clk=~clk;
    reg rst_n=0, in_valid=0, out_ready=0;
    wire in_ready, out_valid;
    reg [LINES*LANES*DATA_W-1:0] operand_a=0,operand_b=0;
    reg [LINES*LANES-1:0] lane_enable=0;
    wire [LINES*SUM_W-1:0] out_sums;
    integer expected [0:CASES-1][0:LINES-1];
    integer sent=0,received=0,cycle,lane,line,a,b,value;
    integer last_output_cycle=-1;
    reg [31:0] rng=32'hbc451203;
    reg [LINES*SUM_W-1:0] held_sums;
    reg held=0;
    tri_oracle_pe_array dut (.*);
    function automatic integer next_signed(input integer unused);
        begin
            rng=rng*32'd1664525+32'd1013904223;
            next_signed=integer'(rng[31:24])-128;
        end
    endfunction
    initial begin
        repeat(2) @(negedge clk);
        rst_n=1;
        for(cycle=0;cycle<2000 && received<CASES;cycle=cycle+1) begin
            @(negedge clk);
            in_valid=sent<CASES && (NO_STALL || cycle%7!=3);
            out_ready=NO_STALL || (cycle%5!=0 && cycle%11!=0);
            for(line=0;line<LINES;line=line+1) begin
                value=0;
                for(lane=0;lane<LANES;lane=lane+1) begin
                    a=next_signed(0); b=next_signed(0);
                    if(sent==0) begin a=-128; b=-128; end
                    if(sent==1) begin a=-128; b=127; end
                    operand_a[(line*LANES+lane)*DATA_W +: DATA_W]=DATA_W'(a);
                    operand_b[(line*LANES+lane)*DATA_W +: DATA_W]=DATA_W'(b);
                    lane_enable[line*LANES+lane]=(sent<2) || ((line+lane+sent)%4!=0);
                    if(lane_enable[line*LANES+lane]) value=value+a*b;
                end
                if(sent<CASES) expected[sent][line]=value;
            end
            @(posedge clk);
            if(held && (!out_valid || out_sums !== held_sums))
                $fatal(1,"output changed under backpressure");
            held=out_valid && !out_ready;
            held_sums=out_sums;
            if(out_valid && out_ready) begin
                if(NO_STALL && last_output_cycle>=0 && cycle!=last_output_cycle+1)
                    $fatal(1,"compute array did not sustain one transaction per cycle");
                last_output_cycle=cycle;
                if(received>=sent) $fatal(1,"unexpected output");
                for(line=0;line<LINES;line=line+1)
                    if($signed(out_sums[line*SUM_W +: SUM_W]) !== expected[received][line])
                        $fatal(1,"transaction=%0d line=%0d got=%0d expected=%0d",
                               received,line,$signed(out_sums[line*SUM_W +: SUM_W]),expected[received][line]);
                received=received+1;
            end
            if(in_valid && in_ready) sent=sent+1;
        end
        if(received!=CASES || sent!=CASES) $fatal(1,"timeout sent=%0d received=%0d",sent,received);
        // A reset must discard pending results and release input backpressure.
        @(negedge clk); in_valid=1; out_ready=1;
        @(posedge clk);
        @(negedge clk); rst_n=0; in_valid=0;
        @(posedge clk); #1;
        if(out_valid) $fatal(1,"reset did not clear valid pipeline");
        @(negedge clk); rst_n=1;
        repeat(6) begin
            @(posedge clk); #1;
            if(out_valid) $fatal(1,"pre-reset transaction leaked after reset");
        end
        $display("PASS: 300 full 32x8 signed compute transactions, masks, stalls, reset; NO_STALL=%0d",NO_STALL);
        $finish;
    end
endmodule
