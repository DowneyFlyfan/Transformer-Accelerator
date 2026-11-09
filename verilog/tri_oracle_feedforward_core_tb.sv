`timescale 1ns/1ps
module tri_oracle_feedforward_core_tb;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,cfg_valid=0,in_valid=0,in_last=0,in_group_last=0,out_ready=0;
    reg [31:0] cfg_tag=0;
    reg [63:0] cfg_activation_base=0,cfg_weight_base=0,cfg_up_weight_base=0;
    reg [5:0] cfg_gate_shift=0,cfg_up_shift=0,cfg_down_shift=4;
    reg [63:0] cfg_down_weight_base=0;
    reg [16:0] cfg_dense_features=0;
    reg [15:0] cfg_output_start=0;
    reg [8:0] cfg_output_count=0;
    reg [9:0] cfg_features=0,cfg_span=0;
    reg [8:0] cfg_start=0;
    reg [10:0] in_group=0;
    reg [127:0] norm_activations=0;
    reg [255:0] gate_weight_signs=0,up_weight_signs=0;
    wire cfg_ready,in_ready,out_valid,out_last,out_fallback,out_error,req_valid,rsp_ready;
    wire [31:0] out_tag;
    wire [5:0] out_count;
    wire [511:0] out_channels;
    wire [1023:0] out_data;
    wire [63:0] req_address;
    wire [4:0] req_length;
    reg rsp_valid=0,rsp_last=0,rsp_error=0;
    reg [63:0] rsp_data=0;
    integer cycle=0,requests=0,ref_features=0,ref_span=0,mode=0,ref_dense=0,ref_outputs=0,ref_output_start=0,fault_mode=0,down_requests=0,fault_after=0;
    integer beat=0,length=0;
    reg model_active=0,model_fault=0,fault_done=0;
    integer model_extra=0;
    reg [63:0] address=0;
    localparam [63:0] ACT_BASE=64'h1000,WEIGHT_BASE=64'h100000,UP_BASE=64'h40000000,DOWN_BASE=64'h80000000;
    wire req_ready=!model_active && !rsp_valid && cycle%4!=0;
    tri_oracle_feedforward_core dut(.*);
    function automatic bit allowed(input integer channel);
        if(mode==1) allowed=0;
        else if(mode==0) allowed=(channel<32)?channel%2==0:channel%2==1;
        else allowed=channel<ref_dense;
    endfunction
    function automatic integer down_weight(input integer row,column);
        down_weight=(row*3+column*7)%255-127;
    endfunction
    always @(posedge clk) begin: external_memory
        integer lane,channel,feature,value,phase;
        reg [63:0] cursor,offset,request_bytes,matrix_bytes,first_byte,last_byte;
        reg inject;
        if(!rst_n) begin cycle<=0;model_active<=0;rsp_valid<=0;end
        else begin
            cycle<=cycle+1;
            if(cycle%256==0) begin
                $display("FEEDFORWARD_PROGRESS cycles=%0d requests=%0d down_requests=%0d",
                    cycle,requests,down_requests);
                $fflush();
            end
            if(cycle<16 || cycle%256==0) begin
                $display("FEEDFORWARD_HANDSHAKE cycles=%0d cfg_valid=%b cfg_ready=%b in_valid=%b in_ready=%b in_last=%b group_last=%b req_valid=%b req_ready=%b out_valid=%b out_error=%b",
                    cycle,cfg_valid,cfg_ready,in_valid,in_ready,in_last,in_group_last,
                    req_valid,req_ready,out_valid,out_error);
                $fflush();
            end
            if(req_valid && req_ready) begin
                if(fault_done) $fatal(1,"feed-forward issued a request after transport failure");
                phase=req_address>=DOWN_BASE?3:(req_address>=UP_BASE?2:(req_address>=WEIGHT_BASE?1:0));
                if($isunknown({req_address,req_length}) || req_length==0 || req_length>16 ||
                   req_address[2:0]!=0 || (phase==3 && req_length!=1))
                    $fatal(1,"invalid feed-forward memory request");
                request_bytes=64'(req_length)*8;
                if(phase==1 || phase==2) begin
                    offset=req_address-(phase==1?WEIGHT_BASE:UP_BASE);
                    matrix_bytes=64'(ref_dense)*64'(ref_features)*8;
                    if(ref_dense<=0 || ref_features<=0 || offset>=matrix_bytes ||
                       request_bytes>matrix_bytes-offset)
                        $fatal(1,"gate/up request outside full-width matrix range");
                    channel=int'(offset/(64'(ref_features)*8));
                    if(channel>=ref_dense || !allowed(channel)) $fatal(1,"fetched a skipped gate/up row");
                end else if(phase==3) begin
                    offset=req_address-DOWN_BASE;
                    first_byte=64'(ref_output_start)*64'(ref_dense);
                    last_byte=(64'(ref_output_start)+64'(ref_outputs))*64'(ref_dense);
                    if(ref_dense<=0 || offset<first_byte || offset>=last_byte ||
                       request_bytes>last_byte-offset)
                        $fatal(1,"down request outside full-width output range");
                    channel=int'(offset/64'(ref_dense));
                    if(channel<ref_output_start || channel>=ref_output_start+ref_outputs)
                        $fatal(1,"wrong down-projection output row");
                end else begin
                    offset=req_address-ACT_BASE;
                    matrix_bytes=64'(ref_features)*8;
                    if(req_address<ACT_BASE || offset>=matrix_bytes ||
                       request_bytes>matrix_bytes-offset)
                        $fatal(1,"wrong latched activation base or full-width burst range");
                end
                inject=(fault_mode==phase && phase!=0) ||
                    (fault_mode==4 && phase==3 && down_requests>=fault_after);
                if(inject) fault_done<=1;
                address<=req_address;length<=int'(req_length)+(inject && fault_mode==4?1:0);
                beat<=0;model_active<=1;model_fault<=inject && fault_mode!=4;
                model_extra<=inject && fault_mode==4;
                if(phase==3) down_requests=down_requests+1;
                requests=requests+1;
            end
            if(model_active && !rsp_valid && cycle%3!=0) begin
                rsp_valid<=1;rsp_last<=beat==length-1;rsp_error<=model_fault && beat==0;
                cursor=address+64'(beat)*8;
                for(lane=0;lane<8;lane=lane+1) begin
                    if(address>=DOWN_BASE) begin
                        offset=address-DOWN_BASE;
                        channel=int'(offset/64'(ref_dense));feature=int'(offset%64'(ref_dense))+lane;
                        value=down_weight(channel,feature);
                    end else if(address>=UP_BASE) begin
                        offset=cursor-UP_BASE;
                        channel=int'(offset/(64'(ref_features)*8));
                        value=(channel%3==0)?-1:(channel%3==1?1:2);
                    end else if(address>=WEIGHT_BASE) value=16;
                    else value=1;
                    rsp_data[lane*8+:8]<=8'(value);
                end
            end
            if(rsp_valid && rsp_ready) begin
                rsp_valid<=0;beat<=beat+1;if(rsp_last) model_active<=0;
            end
        end
    end
    task automatic configure(input integer features,dense,outputs,start,test_mode,fault,input [31:0] tag,
        input integer after_requests=0);
        integer timeout;
        begin
            @(negedge clk);cfg_valid=1;cfg_tag=tag;cfg_features=10'(features);
            cfg_activation_base=ACT_BASE;cfg_weight_base=WEIGHT_BASE;cfg_up_weight_base=UP_BASE;
            cfg_down_weight_base=DOWN_BASE;cfg_dense_features=17'(dense);
            cfg_output_start=16'(start);cfg_output_count=9'(outputs);
            cfg_gate_shift=0;cfg_up_shift=0;cfg_down_shift=4;
            ref_features=features;ref_dense=dense;ref_outputs=outputs;ref_output_start=start;
            mode=test_mode;fault_mode=fault;fault_after=after_requests;fault_done=0;requests=0;down_requests=0;
            timeout=0;@(posedge clk);
            while(!cfg_ready && timeout<50) begin @(posedge clk);timeout=timeout+1;end
            if(!cfg_ready) $fatal(1,"feed-forward configuration blocked");
            @(negedge clk);cfg_valid=0;cfg_tag=0;cfg_features=0;cfg_dense_features=0;cfg_output_count=0;
            cfg_activation_base=0;cfg_weight_base=0;cfg_up_weight_base=0;cfg_down_weight_base=0;
        end
    endtask
    task automatic frame(input integer group_id,strips,input bit last);
        integer strip,row,timeout;
        reg [255:0] signs;
        begin
            for(row=0;row<32;row=row+1)
                signs[row*8+:8]=allowed(group_id*32+row)?8'h00:8'haa;
            for(strip=0;strip<strips;strip=strip+1) begin
                @(negedge clk);in_valid=1;in_last=strip==strips-1;
                in_group=(strip==0)?11'(group_id):11'd999;
                in_group_last=(strip==0)?last:!last;
                norm_activations={8{16'd1024}};
                gate_weight_signs=signs;up_weight_signs=signs;
                for(row=0;row<32;row=row+1)
                    if(allowed(group_id*32+row) && (group_id*32+row)%3==0) up_weight_signs[row*8+:8]=8'hff;
                timeout=0;@(posedge clk);
                while(!in_ready && timeout<100000) begin @(posedge clk);timeout=timeout+1;end
                if(!in_ready) $fatal(1,"prediction input was not accepted");
                @(negedge clk);in_valid=0;
            end
        end
    endtask
    task automatic result(input bit error,fallback,input [31:0] tag);
        integer offset,count,timeout,row,column,expected,value;
        bit last;
        reg [1576:0] held;
        begin
            offset=0;
            do begin
                count=error?0:((ref_outputs-offset>32)?32:ref_outputs-offset);
                last=error || offset+count==ref_outputs;
                timeout=0;
                while(!out_valid && timeout<250000) begin @(negedge clk);timeout=timeout+1;end
                if(!out_valid)
                    $fatal(1,"feed-forward result timeout tag=%h req=%b rsp=%b input_ready=%b",
                        tag,req_valid,rsp_valid,in_ready);
                if({out_count,out_last,out_error,out_fallback,out_tag}!=={6'(count),last,error,fallback,tag})
                    $fatal(1,"feed-forward result metadata mismatch count=%0d error=%b",out_count,out_error);
                for(row=0;row<32;row=row+1) begin
                    expected=0;
                    if(row<count) begin
                        if(out_channels[row*16+:16]!==16'(ref_output_start+offset+row))
                            $fatal(1,"feed-forward output identifier mismatch");
                        for(column=0;column<ref_dense;column=column+1) begin
                            if(allowed(column)) begin
                                // Fixture: gate=2432 Q8; SiLU tail returns gate.
                                // up=-152,152,304 gives -1444,1444,2888 Q8.
                                // Round/shift4 and saturate: -90,90,127 INT8.
                                if(ref_features==19) value=column%3==0?-90:(column%3==1?90:127);
                                else value=column%3==0?-128:127;
                                expected=expected+value*down_weight(ref_output_start+offset+row,column);
                            end
                        end
                    end
                    if(out_data[row*32+:32]!==32'(expected))
                        $fatal(1,"full gated/down reference mismatch row=%0d got=%0d expected=%0d",row,$signed(out_data[row*32+:32]),expected);
                end
                held={out_count,out_last,out_error,out_fallback,out_tag,out_channels,out_data};
                @(negedge clk);in_valid=1;cfg_valid=1;
                repeat(5) begin
                    @(posedge clk);#1;
                    if(!out_valid || in_ready || cfg_ready ||
                       {out_count,out_last,out_error,out_fallback,out_tag,out_channels,out_data}!==held)
                        $fatal(1,"feed-forward output or tensor boundary changed under stall");
                end
                @(negedge clk);in_valid=0;cfg_valid=0;out_ready=1;
                @(negedge clk);out_ready=0;
                offset=error?ref_outputs:offset+count;
            end while(!error && offset<ref_outputs);
            $display("FEEDFORWARD_CASE_PASS tag=%h error=%b fallback=%b cycles=%0d",
                tag,error,fallback,cycle);
            $fflush();
        end
    endtask
    task automatic tensor(input integer groups,strips);
        integer group_id;
        begin for(group_id=0;group_id<groups;group_id=group_id+1) frame(group_id,strips,group_id==groups-1);end
    endtask
    initial begin
        repeat(2) @(negedge clk);rst_n=1;
        configure(19,64,35,17,0,0,32'h100);tensor(2,19);result(0,0,32'h100);
        configure(19,192,65,31,2,0,32'h200);tensor(6,19);result(0,0,32'h200);
        configure(19,32,480,0,2,0,32'h300);tensor(1,19);result(0,0,32'h300);
        configure(19,64,33,0,1,0,32'h400);tensor(2,19);result(0,0,32'h400);
        if(requests!=0) $fatal(1,"all-skipped feed-forward tensor transferred operands");
        configure(19,64,35,17,0,1,32'h501);tensor(2,19);result(1,0,32'h501);
        configure(19,64,35,17,0,2,32'h502);tensor(2,19);result(1,0,32'h502);
        configure(19,64,35,17,0,3,32'h503);tensor(2,19);result(1,0,32'h503);
        configure(19,32,35,17,2,4,32'h504,128);tensor(1,19);result(1,0,32'h504);
        configure(19,32,3,0,2,0,32'h600);tensor(1,1);result(0,1,32'h600);
        configure(512,32,1,65535,2,0,32'h700);tensor(1,512);result(0,0,32'h700);
        configure(19,32,481,0,2,0,32'h800);result(1,0,32'h800);
        configure(19,32,3,0,2,0,32'h900);tensor(1,19);wait(model_active);
        @(negedge clk);rst_n=0;repeat(2) @(negedge clk);rst_n=1;
        configure(19,32,3,0,2,0,32'h901);tensor(1,19);result(0,0,32'h901);
        $display("PASS: prediction-to-gate/up-to-sparse-down on one shared core, dense reference sums, all15 partial-sum slots, multiple input batches/output tiles, empty tensor, faults in all matrices, late failure withholding outputs, stalls, reset");
        $finish;
    end
    initial begin #15000000;$fatal(1,"feed-forward watchdog");end
endmodule
