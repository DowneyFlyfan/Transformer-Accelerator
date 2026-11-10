`timescale 1ns/1ps
module tri_oracle_compute_fabric_tb;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,load_valid=0,cmd_valid=0,cmd_accumulate=0;
    reg [4:0] load_core=0,cmd_clusters=31,cmd_weight=0,cmd_mask=0;
    reg [1:0] load_kind=0,cmd_reduce=0;
    reg [9:0] load_addr=0,cmd_activation=0;
    reg [2047:0] load_data=0;
    reg [31:0] load_row_enable=32'hffffffff;
    reg [3:0] cmd_output=0;
    reg [4:0] out_ready=0;
    wire cmd_ready,load_error;
    wire [4:0] out_valid;
    wire [19:0] out_output;
    wire [5119:0] out_data;
    integer core,lane,line,n,g,cycle,expected;
    integer received[0:4];
    reg held[0:4];
    reg [1023:0] held_data[0:4];
    reg [3:0] held_tag[0:4];
    tri_oracle_compute_fabric dut(.merge_sign_data('0), .merge_sign_control('0), .merge_sign_counts(), .strip_rst_n(1'b0), .strip_request('0), .strip_response(), .head_request('0), .head_response(), .*);
    task automatic load(input [1:0] kind,input [2047:0] data);
        begin
            @(negedge clk);load_valid=1;load_kind=kind;load_data=data;
            @(posedge clk);#1;
            if(load_error) $fatal(1,"load error core=%0d",load_core);
            @(negedge clk);load_valid=0;
        end
    endtask
    initial begin
        for(g=0;g<5;g=g+1) begin received[g]=0;held[g]=0;end
        repeat(2) @(negedge clk);rst_n=1;
        for(core=0;core<20;core=core+1) begin
            load_core=5'(core);
            for(lane=0;lane<256;lane=lane+1)load_data[lane*8+:8]=8'(core+1);
            load(0,load_data);
            load_data=0;
            for(lane=0;lane<8;lane=lane+1)load_data[lane*8+:8]=8'(lane+1);
            load(1,load_data);
            load(2,{{1792{1'b0}},{256{1'b1}}});
        end
        // Broadcast three commands to all five clusters. Modes: sum, maximum, mean.
        for(n=0;n<3;n=n+1) begin
            @(negedge clk);cmd_valid=1;cmd_reduce=2'(n);cmd_output=4'(n);
            @(posedge clk);
            if(!cmd_ready) $fatal(1,"broadcast command not accepted");
        end
        @(negedge clk);cmd_valid=0;
        // An in-flight destination cannot be overwritten before consumption.
        cmd_output=0;
        #1;
        if(cmd_ready) $fatal(1,"reserved destination accepted");
        for(cycle=0;cycle<80;cycle=cycle+1) begin
            @(negedge clk);
            for(g=0;g<5;g=g+1)out_ready[g]=(cycle+g)%4!=0 && cycle>12;
            @(posedge clk);
            for(g=0;g<5;g=g+1) begin
                if(held[g] && (!out_valid[g] || out_data[g*1024+:1024]!==held_data[g] ||
                               out_output[g*4+:4]!==held_tag[g]))
                    $fatal(1,"cluster %0d changed stalled output",g);
                held[g]=out_valid[g] && !out_ready[g];
                held_data[g]=out_data[g*1024+:1024];held_tag[g]=out_output[g*4+:4];
                if(out_valid[g] && out_ready[g]) begin
                    if(received[g]>=3 || out_output[g*4+:4]!==4'(received[g]))
                        $fatal(1,"cluster %0d out-of-order output",g);
                    case(received[g])
                        0:expected=36*(16*g+10);
                        1:expected=36*(4*g+4);
                        2:expected=9*(16*g+10);
                    endcase
                    for(line=0;line<32;line=line+1)
                        if($signed(out_data[g*1024+line*32+:32])!==expected)
                            $fatal(1,"cluster=%0d mode=%0d line=%0d got=%0d expected=%0d",
                                g,received[g],line,$signed(out_data[g*1024+line*32+:32]),expected);
                    received[g]=received[g]+1;
                end
            end
        end
        for(g=0;g<5;g=g+1)if(received[g]!=3)$fatal(1,"cluster %0d timed out",g);
        // Fill and wrap the 16-entry queues of clusters 0 and 2 only.
        @(negedge clk);out_ready=0;cmd_clusters=5'b00101;cmd_reduce=0;
        for(n=0;n<16;n=n+1)begin
            @(negedge clk);cmd_valid=1;cmd_output=4'(n);
            @(posedge clk);
            if(!cmd_ready)$fatal(1,"queue rejected legal command %0d",n);
        end
        @(negedge clk);cmd_valid=0;
        #1;if(cmd_ready)$fatal(1,"full queue failed to apply backpressure");
        // Cluster 1 remains independently available while 0 and 2 are full.
        cmd_clusters=5'b00010;cmd_output=9;cmd_valid=1;
        @(posedge clk);
        if(!cmd_ready)$fatal(1,"unselected full queues blocked cluster 1");
        @(negedge clk);cmd_valid=0;
        for(g=0;g<5;g=g+1)received[g]=0;
        for(cycle=0;cycle<100;cycle=cycle+1)begin
            @(negedge clk);out_ready=cycle<30?5'b11011:5'b11111;
            @(posedge clk);
            for(g=0;g<5;g=g+1)if(out_valid[g] && out_ready[g])begin
                if(g==0 || g==2)begin
                    if(received[g]>=16 || out_output[g*4+:4]!==4'(received[g]))
                        $fatal(1,"wrapped queue order failed cluster %0d",g);
                end else if(g==1)begin
                    if(received[g]!=0 || out_output[g*4+:4]!==9)
                        $fatal(1,"selected cluster 1 result failed");
                end else $fatal(1,"unselected cluster %0d produced output",g);
                expected=36*(16*g+10);
                for(line=0;line<32;line=line+1)
                    if($signed(out_data[g*1024+line*32+:32])!==expected)
                        $fatal(1,"wrapped queue value failed cluster %0d",g);
                received[g]=received[g]+1;
            end
        end
        if(received[0]!=16 || received[2]!=16 || received[1]!=1)
            $fatal(1,"queue drain timeout %0d %0d %0d",received[0],received[1],received[2]);
        @(negedge clk);load_core=31;load_valid=1;
        @(posedge clk);#1;
        if(!load_error)$fatal(1,"invalid core index not rejected");
        @(negedge clk);load_valid=0;rst_n=0;
        @(posedge clk);#1;
        if(out_valid!==0)$fatal(1,"reset leaked results");
        $display("PASS: all 20 cores, five clusters, sum/max/mean, 1536 aggregate values, destination protection, queue wrap/full, selected issue, independent stalls, reset");
        $finish;
    end
    initial begin #100000;$fatal(1,"watchdog timeout");end
endmodule
