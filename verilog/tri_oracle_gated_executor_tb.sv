`timescale 1ns/1ps
module tri_oracle_gated_executor_tb;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,in_valid=0,in_last=0,in_fallback=0,out_ready=0;
    reg [31:0] in_tag=0;
    reg [511:0] in_channels=0;
    reg [5:0] in_count=0;
    reg [63:0] in_activation_base=0,in_weight_base=0,in_up_weight_base=0;
    reg [5:0] in_gate_shift=0,in_up_shift=0;
    reg [9:0] in_features=0,in_span=0;
    reg [8:0] in_start=0;
    wire in_ready,out_valid,out_last,out_fallback,out_error,req_valid,rsp_ready;
    wire [31:0] out_tag;
    wire [5:0] out_count;
    wire [511:0] out_channels;
    wire [1023:0] out_data;
    wire [63:0] req_address;
    wire [4:0] req_length;
    reg rsp_valid=0,rsp_last=0,rsp_error=0;
    reg [63:0] rsp_data=0;
    wire core_load_valid,core_cmd_valid,core_cmd_accumulate,core_read_valid;
    wire [1:0] core_load_kind;
    wire [9:0] core_load_address,core_cmd_activation;
    wire [2047:0] core_load_data;
    wire [31:0] core_load_rows;
    wire [4:0] core_cmd_weight,core_cmd_mask;
    wire [3:0] core_cmd_output,core_read_output,core_done_output;
    wire core_load_error,core_done_valid,core_result_valid,actual_cmd_ready;
    wire [1023:0] core_result_data;
    integer cycle=0,requests=0,commands=0,model_beat=0,model_length=0,model_kind=0,model_channel=0,model_start=0,model_projection=0;
    integer ref_count=0,ref_features=0,ref_start=0,ref_span=0,fault_request=-1,ref_gate_shift=0,ref_up_shift=0;
    reg model_active=0,model_fault=0;
    reg [511:0] ref_channels=0;
    reg [63:0] ref_act=0,ref_weight=0,ref_up=64'h40000000;
    wire req_ready=!model_active && !rsp_valid && cycle%4!=0;
    wire core_load_ready=cycle%5!=1;
    wire cmd_grant=cycle%4!=2;
    wire core_cmd_ready=actual_cmd_ready && cmd_grant;
    tri_oracle_gated_executor dut(.*);
    tri_oracle_memory_compute core (
        .clk(clk),.rst_n(rst_n),.load_valid(core_load_valid && core_load_ready),
        .load_kind(core_load_kind),.load_addr(core_load_address),.load_data(core_load_data),
        .load_row_enable(core_load_rows),.load_error(core_load_error),
        .cmd_valid(core_cmd_valid && cmd_grant),.cmd_ready(actual_cmd_ready),
        .cmd_weight(core_cmd_weight),.cmd_activation(core_cmd_activation),.cmd_mask(core_cmd_mask),
        .cmd_output(core_cmd_output),.cmd_accumulate(core_cmd_accumulate),
        .done_valid(core_done_valid),.done_output(core_done_output),
        .read_valid(core_read_valid),.read_output(core_read_output),
        .result_valid(core_result_valid),.result_data(core_result_data)
    );
    function automatic integer activation(input integer feature);
        activation=(feature%4==0)?-1:2;
    endfunction
    function automatic integer weight(input integer channel,feature,projection);
        begin
            if(projection==0) begin
                case(channel%5)
                    0:weight=-127;1:weight=-2;2:weight=0;3:weight=2;default:weight=127;
                endcase
            end else begin
                case(channel%3)
                    0:weight=-7;1:weight=3;default:weight=127;
                endcase
            end
        end
    endfunction
    function automatic integer scaled(input integer value,shift);
        real x;
        integer rounded;
        begin
            x=real'(value)/$pow(2.0,real'(shift));
            rounded=x>=0.0?$rtoi(x+0.5):-$rtoi(-x+0.5);
            scaled=rounded>32767?32767:(rounded < -32768 ? -32768:rounded);
        end
    endfunction
    always @(posedge clk) begin: memory_model
        integer position,tile,global_start,length,index,lane,value,pass_requests,pass_index,projection,command_index;
        reg [63:0] expected_address;
        if(!rst_n) begin cycle<=0;model_active<=0;rsp_valid<=0;end
        else begin
            cycle<=cycle+1;
            if(req_valid && req_ready) begin
                pass_requests=(ref_count+1)*((ref_span+15)/16);
                projection=requests>=pass_requests;
                pass_index=requests%pass_requests;
                position=pass_index%(ref_count+1);tile=pass_index/(ref_count+1);
                global_start=ref_start+tile*16;
                length=(ref_span-tile*16>16)?16:ref_span-tile*16;
                index=(position==0)?0:int'(ref_channels[(position-1)*16+:16]);
                expected_address=position==0?ref_act+64'(global_start)*8:
                    (projection==0?ref_weight:ref_up)+(64'(index)*64'(ref_features)+64'(global_start))*8;
                if(length<=0 || req_address!==expected_address || req_length!==5'(length))
                    $fatal(1,"executor transfer order/address/length mismatch request=%0d",requests);
                model_kind<=position;model_channel<=index;model_projection<=projection;model_start<=global_start;
                model_length<=length;model_beat<=0;model_active<=1;model_fault<=(requests==fault_request);
                requests=requests+1;
            end
            if(model_active && !rsp_valid && cycle%3!=0) begin
                rsp_valid<=1;rsp_last<=(model_beat==model_length-1);
                rsp_error<=model_fault && model_beat==0;
                for(lane=0;lane<8;lane=lane+1) begin
                    value=(model_kind==0)?activation((model_start+model_beat)*8+lane):
                        weight(model_channel,(model_start+model_beat)*8+lane,model_projection);
                    rsp_data[lane*8+:8]<=8'(value);
                end
            end
            if(rsp_valid && rsp_ready) begin
                rsp_valid<=0;model_beat<=model_beat+1;
                if(rsp_last) model_active<=0;
            end
            if(core_cmd_valid && core_cmd_ready) begin
                command_index=commands%ref_span;
                if(core_cmd_weight!=={1'((command_index/16)%2),4'(command_index%16)} ||
                   core_cmd_activation!==10'(ref_start+command_index) || core_cmd_output!==0 ||
                   core_cmd_mask!==0 || core_cmd_accumulate!==(command_index!=0))
                    $fatal(1,"executor command/accumulation sequence mismatch at %0d",commands);
                commands=commands+1;
            end
        end
    end
    task automatic submit(input integer count,features,start,span,input bit last,fallback,input [31:0] tag,
        input [63:0] act_base,weight_base,input integer fault,gate_shift=0,up_shift=0,
        input [63:0] up_base=64'h40000000);
        integer row;
        begin
            ref_count=count;ref_features=features;ref_start=start;ref_span=span;
            ref_act=act_base;ref_weight=weight_base;ref_up=up_base;ref_gate_shift=gate_shift;ref_up_shift=up_shift;fault_request=fault;requests=0;commands=0;
            for(row=0;row<32;row=row+1) ref_channels[row*16+:16]=16'(2*row);
            if(count==3) begin ref_channels[15:0]=3;ref_channels[31:16]=34;ref_channels[47:32]=65535;end
            @(negedge clk);in_valid=1;in_count=6'(count);in_channels=ref_channels;
            in_features=10'(features);in_start=9'(start);in_span=10'(span);
            in_up_weight_base=up_base;in_gate_shift=6'(gate_shift);in_up_shift=6'(up_shift);
            in_last=last;in_fallback=fallback;in_tag=tag;in_activation_base=act_base;in_weight_base=weight_base;
            @(posedge clk);if(!in_ready) $fatal(1,"executor refused a new packet");
            @(negedge clk);in_valid=0;in_tag=0;in_channels=0;in_activation_base=0;in_weight_base=0;in_up_weight_base=0;in_gate_shift=63;in_up_shift=63;
        end
    endtask
    task automatic result(input bit error,last,fallback,input [31:0] tag,input integer expected_requests,expected_commands);
        integer timeout,row,feature,expected,gate_sum,up_sum,gate_code,up_code,tolerance,error_distance;
        real gate_real,value;
        reg [1576:0] held;
        begin
            timeout=0;
            while(!out_valid && timeout<20000) begin @(negedge clk);timeout=timeout+1;end
            if(!out_valid) $fatal(1,"hardware tile result missing");
            if(out_error!==error || out_last!==last || out_fallback!==fallback || out_tag!==tag ||
               out_count!==6'(error?0:ref_count) || out_channels!==ref_channels ||
               requests!=expected_requests || commands!=expected_commands)
                $fatal(1,"executor result metadata/work mismatch: req=%0d cmd=%0d error=%b",requests,commands,out_error);
            for(row=0;row<32;row=row+1) begin
                expected=0;tolerance=0;gate_sum=0;up_sum=0;
                if(!error && row<ref_count) begin
                    for(feature=ref_start*8;feature<(ref_start+ref_span)*8;feature=feature+1) begin
                        gate_sum=gate_sum+activation(feature)*weight(int'(ref_channels[row*16+:16]),feature,0);
                        up_sum=up_sum+activation(feature)*weight(int'(ref_channels[row*16+:16]),feature,1);
                    end
                    gate_code=scaled(gate_sum,ref_gate_shift);up_code=scaled(up_sum,ref_up_shift);
                    gate_real=real'(gate_code)/256.0;
                    value=(gate_real/(1.0+$exp(-gate_real)))*real'(up_code);
                    expected=value>=0.0?$rtoi(value+0.5):-$rtoi(-value+0.5);
                    if(expected>32767) expected=32767;
                    if(expected < -32768) expected=-32768;
                    tolerance=(2*(up_code<0?-up_code:up_code)+255)/256+1;
                end
                if((^out_data[row*32+:32])===1'bx) $fatal(1,"unknown gated numerical result");
                error_distance=$signed(out_data[row*32+:32])-expected;
                if(error_distance<0) error_distance=-error_distance;
                if(error_distance>tolerance ||
                   out_data[row*32+16+:16]!=={16{out_data[row*32+15]}})
                    $fatal(1,"gated executor arithmetic mismatch row=%0d got=%0d expected=%0d",row,
                        $signed(out_data[row*32+:32]),expected);

            end
            held={out_error,out_last,out_fallback,out_tag,out_count,out_channels,out_data};
            repeat(4) begin
                @(posedge clk);#1;
                if(!out_valid || in_ready || req_valid || core_load_valid || core_cmd_valid ||
                   {out_error,out_last,out_fallback,out_tag,out_count,out_channels,out_data}!==held)
                    $fatal(1,"blocked executor result changed or issued work");
            end
            @(negedge clk);out_ready=1;
            @(negedge clk);out_ready=0;
        end
    endtask
    initial begin
        repeat(2) @(negedge clk);rst_n=1;
        submit(3,19,0,19,0,0,32'h1234,64'h1000,64'h100000,-1);
        result(0,0,0,32'h1234,16,38);
        submit(32,32,0,32,1,1,32'h9876,64'h2000,64'h200000,-1,1,2);
        result(0,1,1,32'h9876,132,64);
        submit(2,512,0,512,1,0,32'h5678,64'h3000,64'h300000,-1,8,9);
        result(0,1,0,32'h5678,192,1024);
        submit(3,19,0,19,1,0,32'hbad,64'h1000,64'h100000,4);
        result(1,1,0,32'hbad,5,16);
        submit(3,19,0,19,1,0,32'hbad2,64'h1000,64'h100000,9);
        result(1,1,0,32'hbad2,10,19);
        submit(3,19,0,19,1,0,32'hface,64'h1000,64'h100000,-1);
        result(0,1,0,32'hface,16,38);
        submit(3,19,0,19,1,0,32'h3232,64'h1000,64'h100000,-1,32,63);
        result(0,1,0,32'h3232,16,38);
        submit(0,0,0,0,1,0,32'h100,0,0,-1);result(0,1,0,32'h100,0,0);
        submit(33,19,0,19,0,0,32'h101,0,0,-1);result(1,0,0,32'h101,0,0);
        // Nonlinear activation must not be applied to a partial dot product.
        submit(3,19,1,18,0,0,32'h102,0,0,-1);result(1,0,0,32'h102,0,0);
        submit(3,19,0,19,0,0,32'h103,64'h1000,64'h100000,-1,0,0,64'h40000001);
        result(1,0,0,32'h103,0,0);
        submit(2,19,0,19,0,0,32'h105,64'h1000,64'h100000,-1);
        wait(model_active);@(negedge clk);rst_n=0;
        repeat(2) @(negedge clk);rst_n=1;
        submit(3,19,0,19,1,0,32'h106,64'h1000,64'h100000,-1);
        result(0,1,0,32'h106,16,38);
        $display("PASS: two-projection gated executor, actual gate/up weight addresses, complete sums before SiLU, independent shifts, signed nonlinear products, saturation, metadata, stalls, phase faults, recovery, reset");
        $finish;
    end
    initial begin #5000000;$fatal(1,"watchdog timeout");end
endmodule
