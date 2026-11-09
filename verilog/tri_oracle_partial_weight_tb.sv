`timescale 1ns/1ps
// Word and row isolation must survive sparse burst writes. Poison values in
// disabled rows catch an implementation that overwrites the complete word.
module tri_oracle_partial_weight_tb;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,load_valid=0,cmd_valid=0,cmd_accumulate=0,read_valid=0;
    reg [1:0] load_kind=0;
    reg [9:0] load_addr=0,cmd_activation=0;
    reg [2047:0] load_data=0;
    reg [31:0] load_row_enable=32'hffffffff;
    reg [4:0] cmd_weight=0,cmd_mask=0;
    reg [3:0] cmd_output=0,read_output=0;
    wire load_error,cmd_ready,done_valid,result_valid;
    wire [3:0] done_output;
    wire [1023:0] result_data;
    integer row;
    tri_oracle_memory_compute dut(.*);
    task automatic load(input [1:0] kind,input [9:0] address,input [31:0] enable,input [2047:0] data);
        begin
            @(negedge clk);load_valid=1;load_kind=kind;load_addr=address;
            load_row_enable=enable;load_data=data;
            @(posedge clk);#1;
            if(load_error!==1'b0) $fatal(1,"legal partial weight load rejected");
            @(negedge clk);load_valid=0;
        end
    endtask
    task automatic run(input [4:0] word_address);
        integer cycles,r,expected;
        begin
            @(negedge clk);cmd_valid=1;cmd_weight=word_address;
            @(posedge clk);if(cmd_ready!==1'b1) $fatal(1,"compute issue stalled");
            @(negedge clk);cmd_valid=0;cycles=0;
            while(done_valid!==1'b1 && cycles<20) begin @(negedge clk);cycles=cycles+1;end
            if(done_valid!==1'b1 || done_output!==4'd0) $fatal(1,"partial-load completion missing");
            read_valid=1;
            @(posedge clk);#1;
            if(result_valid!==1'b1) $fatal(1,"partial-load result missing");
            for(r=0;r<32;r=r+1) begin
                if(word_address==0) expected=(r==5)?-24:((r==31)?1016:16);
                else expected=(r==0)?-1024:-16;
                if($signed(result_data[r*32+:32])!==expected)
                    $fatal(1,"partial row/word isolation failed: word=%0d row=%0d got=%0d expected=%0d",
                        word_address,r,$signed(result_data[r*32+:32]),expected);
            end
            @(negedge clk);read_valid=0;
        end
    endtask
    initial begin
        repeat(2) @(negedge clk);rst_n=1;
        load(1,0,0,{{1984{1'b0}},{8{8'd1}}}); // Row enables apply only to weights.
        load(2,0,0,{{1792{1'b0}},{256{1'b1}}});
        load(0,0,32'hffffffff,{256{8'd2}});
        load(0,31,32'hffffffff,{256{8'hfe}});
        load_data={256{8'h80}};load_data[5*64+:64]={8{8'hfd}};
        load(0,0,32'h00000020,load_data);
        load_data={256{8'h80}};load_data[31*64+:64]={8{8'h7f}};
        load(0,0,32'h80000000,load_data);
        load_data={256{8'h7f}};load_data[0+:64]={8{8'h80}};
        load(0,31,32'h00000001,load_data);
        run(0);run(31);
        load(0,0,0,0);run(0); // Zero write enables leave the complete word intact.
        $display("PASS: sparse weight row writes, disabled-row poison, word isolation, signed extrema, zero enables, independent activation/mask loads");
        $finish;
    end
    initial begin #100000;$fatal(1,"watchdog timeout");end
endmodule
