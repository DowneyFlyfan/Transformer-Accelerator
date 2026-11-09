`timescale 1ns/1ps
module tri_oracle_predicted_core_tb #(parameter integer GATED=0);
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,cfg_valid=0,in_valid=0,in_last=0,in_group_last=0,out_ready=0;
    reg [31:0] cfg_tag=0;
    reg [63:0] cfg_activation_base=0,cfg_weight_base=0,cfg_up_weight_base=0;
    reg [5:0] cfg_gate_shift=0,cfg_up_shift=1;
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
    integer cycle=0,requests=0,ref_features=0,ref_span=0,mode=0,fault_request=-1;
    integer beat=0,length=0;
    reg model_active=0,model_fault=0;
    reg [63:0] address=0;
    localparam [63:0] ACT_BASE=64'h1000,WEIGHT_BASE=64'h100000,UP_BASE=64'h40000000;
    wire req_ready=!model_active && !rsp_valid && cycle%4!=0;
    tri_oracle_predicted_core #(.GATED(GATED)) dut(.*);
    function automatic bit allowed(input integer channel);
        case(mode)
            0: allowed=channel<64 && ((channel<32 && channel%2==0) || (channel>=32 && channel%2==1));
            1: allowed=0;
            2: allowed=channel==65504 || channel==65535;
            3: allowed=channel<32;
            4: allowed=channel>=64 && channel<96;
            default: allowed=channel==0 || channel==31;
        endcase
    endfunction
    always @(posedge clk) begin: external_memory
        integer lane,channel,feature,value;
        reg [63:0] cursor,matrix_base;
        if(!rst_n) begin cycle<=0;model_active<=0;rsp_valid<=0;end
        else begin
            cycle<=cycle+1;
            if(req_valid && req_ready) begin
                if(req_length==0 || req_length>16 || req_address[2:0]!=0)
                    $fatal(1,"invalid integrated memory request");
                if(req_address>=WEIGHT_BASE) begin
                    matrix_base=req_address>=UP_BASE?UP_BASE:WEIGHT_BASE;
                    channel=int'((req_address-matrix_base)/(64'(ref_features)*8));
                    if(!allowed(channel)) $fatal(1,"fetched a predicted-skipped row %0d",channel);
                end else if(req_address<ACT_BASE || req_address>=ACT_BASE+64'(ref_features)*8)
                    $fatal(1,"configuration changed while tensor was active");
                address<=req_address;length<=int'(req_length);beat<=0;model_active<=1;
                model_fault<=requests==fault_request;requests=requests+1;
            end
            if(model_active && !rsp_valid && cycle%3!=0) begin
                rsp_valid<=1;rsp_last<=beat==length-1;rsp_error<=model_fault && beat==0;
                cursor=address+64'(beat)*8;
                for(lane=0;lane<8;lane=lane+1) begin
                    if(cursor<WEIGHT_BASE) value=1;
                    else begin
                        matrix_base=cursor>=UP_BASE?UP_BASE:WEIGHT_BASE;
                        channel=int'((cursor-matrix_base)/(64'(ref_features)*8));
                        feature=int'((cursor-matrix_base)%(64'(ref_features)*8))+lane;
                        value=allowed(channel)?(cursor>=UP_BASE?(channel%3==0?-7:127):-(channel%5+1)):((feature%2==0)?-2:2);
                    end
                    rsp_data[lane*8+:8]<=8'(value);
                end
            end
            if(rsp_valid && rsp_ready) begin
                rsp_valid<=0;beat<=beat+1;
                if(rsp_last) model_active<=0;
            end
        end
    end
    task automatic configure(input integer features,test_mode,fault,input [31:0] tag,input integer start=0,span=-1);
        integer timeout;
        begin
            @(negedge clk);cfg_valid=1;cfg_tag=tag;cfg_features=10'(features);cfg_span=10'(span<0?features:span);
            cfg_start=9'(start);cfg_activation_base=ACT_BASE;cfg_weight_base=WEIGHT_BASE;
            cfg_up_weight_base=UP_BASE;cfg_gate_shift=0;cfg_up_shift=1;
            ref_features=features;ref_span=span<0?features:span;mode=test_mode;fault_request=fault;requests=0;
            timeout=0;
            @(posedge clk);while(!cfg_ready && timeout<50) begin @(posedge clk);timeout=timeout+1;end
            if(!cfg_ready) $fatal(1,"new tensor configuration did not become ready");
            @(negedge clk);cfg_valid=0;cfg_tag=32'hffffffff;cfg_features=0;cfg_span=0;
            cfg_activation_base=64'hbad;cfg_weight_base=64'hbad;cfg_up_weight_base=64'hbad;cfg_gate_shift=63;cfg_up_shift=63;
        end
    endtask
    task automatic frame(input integer group_id,strips,input bit last);
        integer strip,row,timeout;
        reg [255:0] signs;
        begin
            for(row=0;row<32;row=row+1)
                signs[row*8+:8]=(mode!=4 && allowed(group_id*32+row))?8'hff:8'h55;
            for(strip=0;strip<strips;strip=strip+1) begin
                @(negedge clk);in_valid=1;in_last=strip==strips-1;
                in_group=(strip==0)?11'(group_id):11'd999;
                in_group_last=(strip==0)?last:!last;
                norm_activations={8{16'd1024}};
                gate_weight_signs=signs;up_weight_signs=signs;
                timeout=0;@(posedge clk);
                while(!in_ready && timeout<2000) begin @(posedge clk);timeout=timeout+1;end
                if(!in_ready) $fatal(1,"prediction input was not accepted");
                @(negedge clk);in_valid=0;
            end
        end
    endtask
    task automatic result(input integer count,input bit last,fallback,error,input [31:0] tag);
        integer timeout,row,channel,expected,gate_code,up_code,tolerance,distance;
        real gate_real,value;
        reg [1576:0] held;
        begin
            timeout=0;
            while(!out_valid && timeout<20000) begin @(negedge clk);timeout=timeout+1;end
            if(!out_valid) $fatal(1,"integrated predicted result missing");
            if({out_count,out_last,out_fallback,out_error,out_tag}!=={6'(count),last,fallback,error,tag})
                $fatal(1,"integrated result metadata mismatch count=%0d error=%b fallback=%b",out_count,out_error,out_fallback);
            for(row=0;row<32;row=row+1) begin
                expected=0;tolerance=0;
                if(row<count) begin
                    case(mode)
                        0:channel=(row<16)?2*row:2*row+1;
                        2:channel=row==0?65504:65535;
                        3:channel=row;
                        4:channel=64+row;
                        default:channel=row==0?0:31;
                    endcase
                    if(out_channels[row*16+:16]!==16'(channel)) $fatal(1,"wrong original channel identifier");
                    expected=-8*ref_span*(channel%5+1);
                    if(GATED!=0) begin
                        gate_code=expected < -32768 ? -32768:expected;
                        up_code=(channel%3==0?-7:127)*8*ref_span/2;
                        if(up_code>32767) up_code=32767;
                        if(up_code < -32768) up_code=-32768;
                        gate_real=real'(gate_code)/256.0;
                        value=(gate_real/(1.0+$exp(-gate_real)))*real'(up_code);
                        expected=value>=0.0?$rtoi(value+0.5):-$rtoi(-value+0.5);
                        if(expected>32767) expected=32767;
                        if(expected < -32768) expected=-32768;
                        tolerance=(2*(up_code<0?-up_code:up_code)+255)/256+1;
                    end
                end
                if((^out_data[row*32+:32])===1'bx) $fatal(1,"unknown integrated numerical result");
                distance=$signed(out_data[row*32+:32])-expected;if(distance<0) distance=-distance;
                if(distance>tolerance) $fatal(1,"integrated matrix arithmetic mismatch: got=%0d expected=%0d",$signed(out_data[row*32+:32]),expected);
            end
            held={out_count,out_last,out_fallback,out_error,out_tag,out_channels,out_data};
            // Last input frame was already accepted; never ingest a new tensor
            // under the old configuration while a result is blocked.
            @(negedge clk);in_valid=1;cfg_valid=1;
            repeat(5) begin
                @(posedge clk);#1;
                if(!out_valid || in_ready || cfg_ready ||
                   {out_count,out_last,out_fallback,out_error,out_tag,out_channels,out_data}!==held)
                    $fatal(1,"blocked tensor result or configuration boundary changed");
            end
            @(negedge clk);in_valid=0;cfg_valid=0;out_ready=1;
            @(negedge clk);out_ready=0;
        end
    endtask
    initial begin
        repeat(2) @(negedge clk);rst_n=1;
        configure(19,0,-1,32'h1234);
        frame(0,19,0);frame(1,19,1);
        result(32,0,0,0,32'h1234);result(0,1,0,0,32'h1234);
        if(requests!=(GATED!=0?132:66)) $fatal(1,"cross-group packing did not reduce memory transfers");
        configure(19,1,-1,32'h2222);frame(3,19,1);result(0,1,0,0,32'h2222);
        if(requests!=0) $fatal(1,"all-skipped tensor transferred operands");
        configure(512,2,-1,32'h3333);frame(2047,512,1);result(2,1,0,0,32'h3333);
        if(requests!=(GATED!=0?192:96)) $fatal(1,"4096-feature integrated transfer count mismatch");
        configure(19,3,1,32'h4444);frame(0,19,1);
        result(0,0,0,1,32'h4444);result(0,1,0,1,32'h4444);
        if(requests!=2) $fatal(1,"memory failure did not stop further tensor transfers");
        configure(19,5,-1,32'h5555);frame(0,19,1);result(2,1,0,0,32'h5555);
        configure(19,4,-1,32'h6666);frame(2,1,1);
        result(32,0,1,0,32'h6666);result(0,1,1,0,32'h6666);
        configure(19,4,-1,32'h7777);frame(2,20,1);
        result(32,0,1,0,32'h7777);result(0,1,1,0,32'h7777);
        configure(19,5,-1,32'h7878,7,11);
        if(GATED==0) begin
            frame(0,19,1);result(2,1,0,0,32'h7878);
            if(requests!=3) $fatal(1,"partial feature range transfer count mismatch");
        end else begin
            result(0,1,0,1,32'h7878);
            if(requests!=0) $fatal(1,"partial nonlinear operation issued transfers");
        end
        configure(0,1,-1,32'h8888);result(0,1,0,1,32'h8888);
        if(requests!=0) $fatal(1,"invalid configuration issued transfers");
        configure(19,3,-1,32'h9999);frame(0,19,1);
        wait(model_active);@(negedge clk);rst_n=0;
        repeat(2) @(negedge clk);rst_n=1;
        configure(19,5,-1,32'haaaa);frame(0,19,1);result(2,1,0,0,32'haaaa);
        $display("GATED=%0d",GATED);
        $display("PASS: autonomous predicted core, cross-group packing, skipped transfers, 4096 features, maximum channel ID, tensor boundaries, malformed-frame fallback, transport failure, recovery, reset");
        $finish;
    end
    initial begin #5000000;$fatal(1,"integrated core watchdog");end
endmodule
