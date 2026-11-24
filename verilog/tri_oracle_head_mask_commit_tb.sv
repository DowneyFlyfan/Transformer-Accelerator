`timescale 1ns/1ps
module tri_oracle_head_mask_commit_tb;
    logic clk=0, rst_n=0, cancel=0;
    always #5 clk=~clk;
    logic cfg_valid=0, cfg_ready;
    logic [31:0] cfg_heads=0, cfg_tag=0;
    logic [15:0] cfg_epoch=0;
    logic result_valid=0, result_ready, result_error=0, result_streaming=0;
    logic [4:0] result_head=0;
    logic [31:0] result_tag=0;
    logic mask_valid, mask_ready=0, mask_error;
    logic [31:0] mask_heads, mask_streaming, mask_tag;
    logic [15:0] mask_epoch;
    int checks=0;
    tri_oracle_head_mask_commit dut(.*);

    task automatic begin_frame(input logic [31:0] heads, tag,
                               input logic [15:0] epoch);
        @(negedge clk);
        if(cfg_ready!==1'b1 || mask_valid!==1'b0)$fatal(1,"MASK_BEGIN_NOT_IDLE");
        cfg_heads=heads;cfg_tag=tag;cfg_epoch=epoch;cfg_valid=1;
        @(negedge clk);cfg_valid=0;cfg_heads='x;cfg_tag='x;cfg_epoch='x;
    endtask
    task automatic put(input int head, input logic [31:0] tag,
                       input bit streaming, error);
        @(negedge clk);
        if(result_ready!==1'b1)$fatal(1,"MASK_RESULT_NOT_READY");
        result_valid=1;result_head=5'(head);result_tag=tag;
        result_streaming=streaming;result_error=error;
        @(negedge clk);result_valid=0;result_head='x;result_tag='x;
        result_streaming='x;result_error='x;
    endtask
    task automatic expect_held(input logic [31:0] heads, streaming, tag,
                               input logic [15:0] epoch, input bit error);
        repeat(4)begin
            @(negedge clk);
            if(mask_valid!==1'b1 || mask_error!==error || mask_heads!==heads ||
               mask_streaming!==streaming || mask_tag!==tag || mask_epoch!==epoch ||
               cfg_ready!==1'b0 || result_ready!==1'b0)
                $fatal(1,"MASK_COMPLETION_WRONG heads=%08h streaming=%08h valid=%b error=%b",mask_heads,mask_streaming,mask_valid,mask_error);
        end
        checks++;
        mask_ready=1;@(negedge clk);mask_ready=0;
        if(mask_valid!==1'b0 || cfg_ready!==1'b1 || mask_heads!==0 || mask_streaming!==0)
            $fatal(1,"MASK_COMPLETION_NOT_RELEASED");
    endtask
    initial begin
        repeat(2)@(negedge clk);rst_n=1;
        begin_frame(32'h80000001,32'h71000000,16'h14);
        put(31,32'h7100001f,1,0);
        repeat(3)begin
            @(negedge clk);
            if(mask_valid!==0 || mask_heads!==0 || mask_streaming!==0)
                $fatal(1,"MASK_PARTIAL_EXPOSED");
        end
        put(0,32'h71000000,0,0);
        expect_held(32'h80000001,32'h80000000,32'h71000000,16'h14,0);

        // Duplicate, unrequested, old transaction tag and classifier error
        // must each invalidate the entire mask, including earlier decisions.
        begin_frame(3,32'h72000000,16'h15);
        put(0,32'h72000000,1,0);put(0,32'h72000000,0,0);
        expect_held(0,0,32'h72000000,16'h15,1);
        begin_frame(1,32'h73000000,16'h16);put(1,32'h73000001,1,0);
        expect_held(0,0,32'h73000000,16'h16,1);
        begin_frame(1,32'h74000000,16'h17);put(0,32'h73000000,1,0);
        expect_held(0,0,32'h74000000,16'h17,1);
        begin_frame(3,32'h75000000,16'h18);
        put(0,32'h75000000,1,0);put(1,32'h75000001,1,1);
        expect_held(0,0,32'h75000000,16'h18,1);
        begin_frame(3,32'h76000000,16'h19);
        put(0,32'h76000000,1,0);
        @(negedge clk);cancel=1;
        @(negedge clk);cancel=0;
        expect_held(0,0,32'h76000000,16'h19,1);

        begin_frame(0,32'h77000000,16'h20);
        expect_held(0,0,32'h77000000,16'h20,1);
        begin_frame(1,32'h77000001,16'h21);
        expect_held(0,0,32'h77000001,16'h21,1);
        begin_frame(3,32'h78000000,16'h22);put(0,32'h78000000,1,0);
        @(negedge clk);rst_n=0;@(negedge clk);rst_n=1;
        if(mask_valid!==0 || mask_streaming!==0 || cfg_ready!==1)
            $fatal(1,"MASK_RESET_RETAINED_PARTIAL");
        begin_frame(32'hffffffff,32'h79000000,16'h23);
        for(int head=31;head>=0;head--)put(head,32'h79000000+32'(head),head%2==0,0);
        expect_held(32'hffffffff,32'h55555555,32'h79000000,16'h23,0);
        $display("HEAD_MASK_COMMIT_PASS completions=%0d",checks);
        $finish;
    end
    initial begin #20000;$fatal(1,"HEAD_MASK_COMMIT_WATCHDOG");end
endmodule
