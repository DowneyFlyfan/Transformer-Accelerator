`timescale 1ns/1ps
// Sustained resident-operand rate across all20 cores, not whole-model throughput.
// Catches slot wrap, missing/duplicate/stalled commands, result ordering and
// arithmetic errors after fill. No memory-transfer or routed-clock claim.
module tri_oracle_fabric_stream_tb;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,load_valid=0,cmd_valid=0;
    reg [4:0] load_core=0;
    reg [1:0] load_kind=0;
    reg [9:0] load_addr=0,cmd_activation=0;
    reg [2047:0] load_data=0;
    wire [31:0] load_row_enable=32'hffffffff;
    wire load_error,cmd_ready;
    wire [4:0] cmd_clusters=31,cmd_weight=0,cmd_mask=0;
    reg [3:0] cmd_output=0;
    wire cmd_accumulate=0;
    wire [1:0] cmd_reduce=0;
    wire [4:0] out_ready=31,out_valid;
    wire [19:0] out_output;
    wire [5119:0] out_data;
    integer cycle=0,issued=0,first_issue=-1,last_issue=-1;
    integer received[0:4],first_result[0:4],last_result[0:4];
    integer reference[0:31][0:4][0:31];
    localparam integer COMMANDS=256;
    tri_oracle_compute_fabric dut(.merge_sign_data('0), .merge_sign_control('0), .merge_sign_counts(), .*);
    task automatic load(input [1:0] kind,input [9:0] address,input [2047:0] data);
        @(negedge clk);load_valid=1;load_kind=kind;load_addr=address;load_data=data;
        @(posedge clk);#1;
        if(load_error!==1'b0) $fatal(1,"resident operand load rejected");
        @(negedge clk);load_valid=0;
    endtask
    always @(posedge clk) if(rst_n) begin: monitor
        integer cluster,row,address;
        cycle=cycle+1;
        if(cmd_valid) begin
            if(cmd_ready!==1'b1) $fatal(1,"fabric cannot sustain one command/cycle: command=%0d",issued);
            if(first_issue<0) first_issue=cycle;
            if(issued!=0 && cycle!=last_issue+1) $fatal(1,"issue stream has a gap");
            last_issue=cycle;issued=issued+1;
        end
        for(cluster=0;cluster<5;cluster=cluster+1) if(out_valid[cluster]===1'b1) begin
            if(received[cluster]>=COMMANDS || out_output[cluster*4+:4]!==4'(received[cluster]%16))
                $fatal(1,"stream result count/slot order mismatch cluster=%0d",cluster);
            if(first_result[cluster]<0) first_result[cluster]=cycle;
            if(received[cluster]!=0 && cycle!=last_result[cluster]+1)
                $fatal(1,"cluster result throughput has a bubble");
            last_result[cluster]=cycle;
            address=(received[cluster]*7)%32;
            for(row=0;row<32;row=row+1)
                if(out_data[cluster*1024+row*32+:32]!==32'(reference[address][cluster][row]))
                    $fatal(1,"stream arithmetic mismatch command=%0d cluster=%0d row=%0d",received[cluster],cluster,row);
            received[cluster]=received[cluster]+1;
        end else if(out_valid[cluster]!==1'b0) $fatal(1,"unknown result valid");
    end
    initial begin: stimulus
        integer core,row,lane,address,cluster,part,n,total,weight,value,timeout;
        for(cluster=0;cluster<5;cluster=cluster+1) begin
            received[cluster]=0;first_result[cluster]=-1;last_result[cluster]=-1;
        end
        // Independent integer dot/reduction reference over all four cores.
        for(address=0;address<32;address=address+1)
            for(cluster=0;cluster<5;cluster=cluster+1)
                for(row=0;row<32;row=row+1) begin
                    total=0;
                    for(part=0;part<4;part=part+1)
                        for(lane=0;lane<8;lane=lane+1) begin
                            weight=((cluster*4+part)*3+row*5+lane*7)%255-127;
                            value=(address*11+lane*3)%31-15;
                            total=total+weight*value;
                        end
                    reference[address][cluster][row]=total;
                end
        repeat(2) @(negedge clk);rst_n=1;
        for(core=0;core<20;core=core+1) begin
            load_core=5'(core);
            for(row=0;row<32;row=row+1)
                for(lane=0;lane<8;lane=lane+1)
                    load_data[(row*8+lane)*8+:8]=8'((core*3+row*5+lane*7)%255-127);
            load(0,0,load_data);
            for(address=0;address<32;address=address+1) begin
                load_data=0;
                for(lane=0;lane<8;lane=lane+1)
                    load_data[lane*8+:8]=8'((address*11+lane*3)%31-15);
                load(1,10'(address),load_data);
            end
            load(2,0,{{1792{1'b0}},{256{1'b1}}});
        end
        for(n=0;n<COMMANDS;n=n+1) begin
            @(negedge clk);cmd_valid=1;cmd_output=4'(n%16);cmd_activation=10'((n*7)%32);
        end
        @(negedge clk);cmd_valid=0;
        timeout=0;
        while((received[0]<COMMANDS || received[1]<COMMANDS || received[2]<COMMANDS ||
               received[3]<COMMANDS || received[4]<COMMANDS) && timeout<100) begin
            @(negedge clk);timeout=timeout+1;
        end
        if(issued!=COMMANDS || last_issue-first_issue+1!=COMMANDS)
            $fatal(1,"wrong sustained issue rate");
        for(cluster=0;cluster<5;cluster=cluster+1)
            if(received[cluster]!=COMMANDS || last_result[cluster]-first_result[cluster]+1!=COMMANDS)
                $fatal(1,"stream output drain or sustained result rate mismatch");
        repeat(4) @(negedge clk);
        $display("PASS: 20 real cores;256 consecutive broadcasts;one command/cycle and one result/cycle/cluster after fill;40960 aggregate values;16 destination wraps;resident operands only");
        $display("METRIC: issue_cycles=%0d commands=%0d first_result_latency_cycles=%0d multiplier_operations=%0d arithmetic_operations=%0d assumed_580MHz_dense_TOPS=5.9392",last_issue-first_issue+1,issued,first_result[0]-first_issue,COMMANDS*20*32*8,COMMANDS*20*32*8*2);
        $finish;
    end
    initial begin #500000;$fatal(1,"fabric streaming watchdog");end
endmodule
