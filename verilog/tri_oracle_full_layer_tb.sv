`timescale 1ns/1ps
// Complete first-language-layer feed-forward arithmetic:2048 ->5632 ->2048.
// A software driver repeats the gate/up pass for five output ranges because
// the current hardware retains at most480 down-projection output rows.
// This checks all channel/weight addresses and outputs, not model accuracy.
module tri_oracle_full_layer_tb;
    localparam integer HIDDEN=2048,INTERMEDIATE=5632,GROUPS=176,OUTPUTS=2048;
    localparam [63:0] ACT_BASE=64'h1000,GATE_BASE=64'h100000,
        UP_BASE=64'h40000000,DOWN_BASE=64'h80000000;
    string fixture_directory=".cache/model_reference/full_layer_fixture";
    integer fixture_override;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,cfg_valid=0,in_valid=0,in_last=0,in_group_last=0,out_ready=0;
    wire cfg_ready,in_ready,out_valid,out_last,out_fallback,out_error,req_valid,rsp_ready;
    reg [31:0] cfg_tag=32'h46554c4c;
    wire [63:0] cfg_activation_base=ACT_BASE,cfg_weight_base=GATE_BASE,
        cfg_up_weight_base=UP_BASE,cfg_down_weight_base=DOWN_BASE;
    wire [9:0] cfg_features=256;
    wire [16:0] cfg_dense_features=17'(INTERMEDIATE);
    reg [31:0] configuration[0:4];
    wire [5:0] cfg_gate_shift=configuration[0][5:0],
        cfg_up_shift=configuration[1][5:0],cfg_down_shift=configuration[2][5:0];
    reg [15:0] cfg_output_start=0;
    reg [8:0] cfg_output_count=0;
    reg [10:0] in_group=0;
    reg [127:0] norm_activations=0;
    reg [255:0] gate_weight_signs=0,up_weight_signs=0;
    wire [31:0] out_tag;
    wire [5:0] out_count;
    wire [511:0] out_channels;
    wire [1023:0] out_data;
    wire [63:0] req_address;
    wire [4:0] req_length;
    reg rsp_valid=0,rsp_last=0;
    wire rsp_error=0;
    reg [63:0] rsp_data=0;
    integer cycle=0,requests=0,beats=0,length=0,received=0,batch_received=0;
    integer gate_bytes=0,up_bytes=0,activation_bytes=0,down_bytes=0,skipped=0;
    reg model_active=0;
    reg [63:0] address=0;
    wire req_ready=!model_active && !rsp_valid && cycle%4!=0;
    reg [7:0] activation[0:HIDDEN-1];
    reg [7:0] gate_weights[0:INTERMEDIATE*HIDDEN-1],up_weights[0:INTERMEDIATE*HIDDEN-1];
    reg [7:0] down_weights[0:OUTPUTS*INTERMEDIATE-1],skip_channels[0:INTERMEDIATE-1];
    reg [15:0] normalized[0:HIDDEN-1],groups[0:GROUPS-1];
    reg [31:0] expected[0:OUTPUTS-1];
    reg [1576:0] held;
    reg stalled=0;
    tri_oracle_feedforward_core dut(.*);

    always @(posedge clk) begin: memory_model
        integer lane,row,column,index,phase;
        reg [63:0] cursor,offset;
        if(!rst_n) begin cycle<=0;model_active<=0;rsp_valid<=0;end
        else begin
            cycle<=cycle+1;
            if(cycle!=0 && cycle%1000000==0)
                $display("LAYER_PROGRESS: cycles=%0d outputs=%0d requests=%0d",cycle,received,requests);
            if(req_valid && req_ready) begin
                if(req_length==0 || req_length>16 || req_address[2:0]!=0)
                    $fatal(1,"full-layer invalid memory request");
                address<=req_address;length<=int'(req_length);beats<=0;model_active<=1;
                requests=requests+1;
                if(req_address>=DOWN_BASE) down_bytes=down_bytes+int'(req_length)*8;
                else if(req_address>=UP_BASE) up_bytes=up_bytes+int'(req_length)*8;
                else if(req_address>=GATE_BASE) gate_bytes=gate_bytes+int'(req_length)*8;
                else activation_bytes=activation_bytes+int'(req_length)*8;
            end
            if(model_active && !rsp_valid && cycle%3!=0) begin
                rsp_valid<=1;rsp_last<=beats==length-1;
                for(lane=0;lane<8;lane=lane+1) begin
                    cursor=address+64'(beats*8+lane);
                    if(address>=DOWN_BASE) begin
                        offset=cursor-DOWN_BASE;
                        if(offset>=64'(OUTPUTS)*64'(INTERMEDIATE))
                            $fatal(1,"full-layer down address outside matrix");
                        row=int'(offset/INTERMEDIATE);
                        column=int'(offset%INTERMEDIATE);
                        if(row<int'(cfg_output_start) || row>=int'(cfg_output_start)+int'(cfg_output_count))
                            $fatal(1,"full-layer down read outside current output range");
                        rsp_data[lane*8+:8]<=down_weights[row*INTERMEDIATE+column];
                    end else if(address>=GATE_BASE) begin
                        phase=address>=UP_BASE?2:1;
                        offset=cursor-(phase==2?UP_BASE:GATE_BASE);
                        if(offset>=64'(INTERMEDIATE)*64'(HIDDEN))
                            $fatal(1,"full-layer gate/up address outside matrix");
                        row=int'(offset/HIDDEN);column=int'(offset%HIDDEN);
                        if(row<0 || row>=INTERMEDIATE) $fatal(1,"full-layer invalid intermediate channel");
                        if(skip_channels[row]!==8'd0) $fatal(1,"full-layer fetched predicted-skipped channel %0d",row);
                        index=row*HIDDEN+column;
                        rsp_data[lane*8+:8]<=phase==2?up_weights[index]:gate_weights[index];
                    end else begin
                        offset=cursor-ACT_BASE;
                        if(cursor<ACT_BASE || offset>=HIDDEN) $fatal(1,"full-layer activation outside2048 features");
                        rsp_data[lane*8+:8]<=activation[int'(offset)];
                    end
                end
            end
            if(rsp_valid && rsp_ready) begin
                rsp_valid<=0;
                if(rsp_last) model_active<=0;else beats<=beats+1;
            end
        end
    end
    always @(negedge clk) if(rst_n) out_ready=cycle%5!=0;
    always @(posedge clk) if(rst_n) begin: scoreboard
        integer lane,count;
        if(stalled && (!out_valid || {out_count,out_last,out_error,out_fallback,out_tag,out_channels,out_data}!==held))
            $fatal(1,"full-layer output changed under backpressure");
        stalled=out_valid && !out_ready;
        held={out_count,out_last,out_error,out_fallback,out_tag,out_channels,out_data};
        if(out_valid && out_ready) begin
            count=int'(cfg_output_count)-batch_received>32?32:int'(cfg_output_count)-batch_received;
            if(count<=0 || received+count>OUTPUTS || received!=int'(cfg_output_start)+batch_received ||
               out_error!==1'b0 || out_fallback!==1'b0 || out_tag!==cfg_tag ||
               out_count!==6'(count) || out_last!==(batch_received+count==int'(cfg_output_count)))
                $fatal(1,"full-layer metadata or output framing mismatch");
            for(lane=0;lane<32;lane=lane+1) begin
                if(lane<count) begin
                    if(out_channels[lane*16+:16]!==16'(received+lane) || out_data[lane*32+:32]!==expected[received+lane])
                        $fatal(1,"full-layer mismatch row=%0d got=%0d expected=%0d",received+lane,$signed(out_data[lane*32+:32]),$signed(expected[received+lane]));
                end else if(out_data[lane*32+:32]!==32'd0) $fatal(1,"full-layer nonzero output padding");
            end
            received=received+count;batch_received=batch_received+count;
        end
    end
    initial begin: stimulus
        integer group_index,strip,lane,row,timeout,batch,batch_start,expected_bytes;
        fixture_override=$value$plusargs("FIXTURE_DIR=%s",fixture_directory);
        $readmemh({fixture_directory,"/configuration.hex"},configuration);
        $readmemh({fixture_directory,"/activation.hex"},activation);
        $readmemh({fixture_directory,"/gate.hex"},gate_weights);
        $readmemh({fixture_directory,"/up.hex"},up_weights);
        $readmemh({fixture_directory,"/down.hex"},down_weights);
        $readmemh({fixture_directory,"/norm.hex"},normalized);
        $readmemh({fixture_directory,"/expected.hex"},expected);
        $readmemh({fixture_directory,"/skip.hex"},skip_channels);
        $readmemh({fixture_directory,"/groups.hex"},groups);
        if(configuration[3]!==32'd0 || configuration[4]!==32'(OUTPUTS))
            $fatal(1,"full-layer fixture must cover all2048 output rows");
        for(row=0;row<INTERMEDIATE;row=row+1) begin
            if(skip_channels[row]===8'd1) skipped=skipped+1;
            else if(skip_channels[row]!==8'd0) $fatal(1,"invalid full-layer skip mask");
        end
        for(row=0;row<GROUPS;row=row+1)
            if(groups[row]!==16'(row)) $fatal(1,"full-layer groups do not cover all5632 channels");
        repeat(2) @(negedge clk);rst_n=1;
        for(batch=0;batch<5;batch=batch+1) begin
            @(negedge clk);batch_start=batch*480;batch_received=0;
            cfg_output_start=16'(batch_start);
            cfg_output_count=9'(OUTPUTS-batch_start>480?480:OUTPUTS-batch_start);
            cfg_tag=32'h46554c4c+32'(batch);cfg_valid=1;
            timeout=0;@(posedge clk);
            while(!cfg_ready && timeout<100) begin @(posedge clk);timeout=timeout+1;end
            if(!cfg_ready) $fatal(1,"full-layer configuration blocked");
            @(negedge clk);cfg_valid=0;
            for(group_index=0;group_index<GROUPS;group_index=group_index+1) begin
                for(strip=0;strip<256;strip=strip+1) begin
                    @(negedge clk);in_valid=1;in_last=strip==255;
                    in_group=11'(group_index);in_group_last=group_index==GROUPS-1;
                    for(lane=0;lane<8;lane=lane+1) begin
                        norm_activations[lane*16+:16]=normalized[strip*8+lane];
                        for(row=0;row<32;row=row+1) begin
                            gate_weight_signs[row*8+lane]=gate_weights[(group_index*32+row)*HIDDEN+strip*8+lane][7];
                            up_weight_signs[row*8+lane]=up_weights[(group_index*32+row)*HIDDEN+strip*8+lane][7];
                        end
                    end
                    timeout=0;@(posedge clk);
                    while(!in_ready && timeout<300000) begin @(posedge clk);timeout=timeout+1;end
                    if(!in_ready) $fatal(1,"full-layer prediction frame stalled");
                    @(negedge clk);in_valid=0;
                end
            end
            timeout=0;
            while(batch_received<int'(cfg_output_count) && timeout<400000) begin @(negedge clk);timeout=timeout+1;end
            if(batch_received!=int'(cfg_output_count)) $fatal(1,"full-layer batch outputs missing");
            $display("LAYER_BATCH_PASS: batch=%0d first_row=%0d count=%0d total_outputs=%0d cycles=%0d",batch,batch_start,cfg_output_count,received,cycle);
        end
        expected_bytes=5*(INTERMEDIATE-skipped)*HIDDEN;
        if(received!=OUTPUTS || gate_bytes!==expected_bytes || up_bytes!==expected_bytes)
            $fatal(1,"full-layer output coverage or retained-row weight traffic mismatch");
        repeat(10) @(negedge clk);
        $display("PASS: complete TinyLLaVA-v1 layer0 feed-forward integer arithmetic;2048 inputs,5632 intermediate channels,2048 output sums,5 output-range transactions; cycles=%0d requests=%0d skipped_channels=%0d",cycle,requests,skipped);
        $display("LAYER_TRAFFIC: gate_bytes=%0d up_bytes=%0d activation_bytes=%0d down_bytes=%0d",gate_bytes,up_bytes,activation_bytes,down_bytes);
        $finish;
    end
    initial begin #2000000000;$fatal(1,"full-layer watchdog");end
endmodule
