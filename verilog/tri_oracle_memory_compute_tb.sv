`timescale 1ns/1ps
module tri_oracle_memory_compute_tb;
    reg clk=0; always #5 clk=~clk;
    reg rst_n=0,load_valid=0,cmd_valid=0,cmd_accumulate=0,read_valid=0;
    reg [1:0] load_kind=0;
    reg [9:0] load_addr=0,cmd_activation=0;
    reg [2047:0] load_data=0;
    reg [31:0] load_row_enable=32'hffffffff;
    reg [4:0] cmd_weight=0,cmd_mask=0;
    reg [3:0] cmd_output=0,read_output=0;
    wire cmd_ready,load_error,done_valid,result_valid;
    wire [3:0] done_output;
    wire [1023:0] result_data;
    integer expected[0:15][0:31];
    integer dot[0:31],line,lane,slot,a,w,total,n,done_count=0;
    tri_oracle_memory_compute dut(.*);
    always @(posedge clk) if(rst_n && done_valid) begin
        if(done_output !== 4'(done_count<32 ? done_count%16 : 0))
            $fatal(1,"completion address mismatch %0d got %0d",done_count,done_output);
        done_count=done_count+1;
    end
    task automatic load(input [1:0] kind,input [9:0] address,input [2047:0] data);
        begin
            @(negedge clk); load_valid=1;load_kind=kind;load_addr=address;load_data=data;
            @(posedge clk); #1;
            if(cmd_ready) $fatal(1,"command accepted during configuration write");
            if(load_error) $fatal(1,"legal load rejected");
            @(negedge clk); load_valid=0;
        end
    endtask
    initial begin
        repeat(2) @(negedge clk); rst_n=1;
        // Load both ends with different data. A collapsed address decoder
        // must not pass merely because the test writes and reads one word.
        load_data={256{8'd2}};
        load(0,0,load_data);
        load_data=0;
        load_data[63:0]={8{8'd1}};
        load(1,0,load_data);
        load_data=0;
        load_data[255:0]={256{1'b1}};
        load(2,0,load_data);
        for(line=0;line<32;line=line+1) begin
            total=0;
            for(lane=0;lane<8;lane=lane+1) begin
                a=lane*31-128; w=(line*17+lane*13)%256-128;
                load_data[(line*8+lane)*8+:8]=8'(w);
                if((line+lane)%3!=0) total=total+a*w;
            end
            dot[line]=total;
        end
        load(0,31,load_data);
        load_data=0;
        for(lane=0;lane<8;lane=lane+1) load_data[lane*8+:8]=8'(lane*31-128);
        load(1,1023,load_data);
        load_data=0;
        for(line=0;line<32;line=line+1)
            for(lane=0;lane<8;lane=lane+1) load_data[line*8+lane]=(line+lane)%3!=0;
        load(2,31,load_data);
        // An out-of-range weight address must report an error.
        @(negedge clk);load_valid=1;load_kind=0;load_addr=1023;
        @(posedge clk);#1;
        if(!load_error) $fatal(1,"invalid address was accepted");
        @(negedge clk);load_valid=0;
        // Two continuous passes: overwrite all slots, then accumulate.
        for(n=0;n<40;n=n+1) begin
            @(negedge clk);
            cmd_valid=1;
            cmd_weight=(n<32 && n%2!=0)?31:0;
            cmd_activation=(n<32 && n%2!=0)?1023:0;
            cmd_mask=(n<32 && n%2!=0)?31:0;
            cmd_output=4'(n<32 ? n%16 : 0);cmd_accumulate=n>=16;
            @(posedge clk);
            if(!cmd_ready) $fatal(1,"command throughput stalled");
            for(line=0;line<32;line=line+1) begin
                total=(n<32 && n%2!=0)?dot[line]:16;
                if(n<32) expected[n%16][line]=(n<16?1:2)*total;
                else expected[0][line]=(n-29)*total;
            end
        end
        @(negedge clk);cmd_valid=0;
        for(n=0;n<20 && done_count<40;n=n+1) @(negedge clk);
        if(done_count!=40) $fatal(1,"completion timeout: %0d",done_count);
        for(slot=0;slot<16;slot=slot+1) begin
            @(negedge clk);read_valid=1;read_output=4'(slot);
            @(posedge clk);#1;
            if(!result_valid) $fatal(1,"readback missing");
            for(line=0;line<32;line=line+1)
                if($signed(result_data[line*32+:32]) !== expected[slot][line])
                    $fatal(1,"slot %0d line %0d got %0d expected %0d",slot,line,
                           $signed(result_data[line*32+:32]),expected[slot][line]);
        end
        @(negedge clk);read_valid=0;rst_n=0;
        @(posedge clk);#1;
        if(done_valid || result_valid) $fatal(1,"reset leaked valid outputs");
        $display("PASS: full-size core memory loading, independent low/high addresses, 40 compute commands, consecutive accumulation, 512 output sums, bounds, reset");
        $finish;
    end
    initial begin #100000; $fatal(1,"watchdog timeout"); end
endmodule
