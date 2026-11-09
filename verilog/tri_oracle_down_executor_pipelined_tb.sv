`timescale 1ns/1ps
module tri_oracle_down_executor_pipelined_tb;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,in_valid=0,in_last=0,in_accumulate=0,out_ready=0;
    reg [31:0] in_tag=0;
    reg [5:0] in_count=0,in_output_count=0,in_shift=0;
    reg [511:0] in_channels=0;
    reg [1023:0] in_data=0;
    reg [63:0] in_weight_base=0;
    reg [16:0] in_dense_features=0;
    reg [15:0] in_output_start=0;
    reg [3:0] in_slot=0;
    wire in_ready,out_valid,out_last,out_error,req_valid,rsp_ready;
    wire [31:0] out_tag;
    wire [5:0] out_count;
    wire [15:0] out_start;
    wire [3:0] out_slot;
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
    integer cycle=0,requests=0,commands=0,beat=0,extra_beats=0,cases_checked=0;
    reg force_request_hold=0;
    integer ref_count=0,ref_outputs=0,ref_features=0,ref_start=0,ref_slot=0,ref_shift=0;
    integer fault_request=-1,fault_mode=0;
    reg ref_accumulate=0,model_active=0,model_error=0;
    reg [63:0] ref_base=0,model_address=0;
    reg [511:0] selected_ids=0;
    reg [1023:0] selected_data=0;
    integer golden[0:15][0:31];
    wire req_ready=!force_request_hold && !model_active && !rsp_valid && cycle%4!=0;
    wire core_load_ready=cycle%5!=1;
    wire cmd_grant=cycle%4!=2;
    wire core_cmd_ready=actual_cmd_ready && cmd_grant;
    tri_oracle_down_executor_pipelined dut(.*);
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
    function automatic integer weight(input integer row,column);
        weight=(row*3+column*7)%255-127;
    endfunction
    function automatic integer activation(input integer raw,shift);
        real value;
        integer rounded;
        begin
            value=real'(raw)/$pow(2.0,real'(shift));
            rounded=value>=0.0?$rtoi(value+0.5):-$rtoi(-value+0.5);
            activation=rounded>127?127:(rounded < -128 ? -128:rounded);
        end
    endfunction
    always @(posedge clk) begin: memory_model
        integer row,column,lane,i;
        reg matched;
        reg [63:0] offset;
        if(!rst_n) begin cycle<=0;model_active<=0;rsp_valid<=0;end
        else begin
            cycle<=cycle+1;
            if(req_valid && req_ready) begin
                if(req_length!==5'd1 || req_address[2:0]!=0 || req_address<ref_base)
                    $fatal(1,"invalid down gather request");
                offset=req_address-ref_base;
                row=int'(offset/64'(ref_features));column=int'(offset%64'(ref_features));
                matched=0;
                for(i=0;i<ref_count && i<32;i=i+1)
                    if(int'(selected_ids[i*16+:16])/8==column/8 &&
                       activation($signed(selected_data[i*32+:32]),ref_shift)!=0) matched=1;
                if(row<ref_start || row>=ref_start+ref_outputs || !matched)
                    $fatal(1,"gather requested an unused weight column or wrong output row");
                model_address<=req_address;model_active<=1;beat<=0;
                extra_beats<=(requests==fault_request && fault_mode==2)?1:0;
                model_error<=requests==fault_request && fault_mode==1;
                requests=requests+1;
            end
            if(model_active && !rsp_valid && cycle%3!=0) begin
                offset=model_address-ref_base;
                row=int'(offset/64'(ref_features));column=int'(offset%64'(ref_features));
                rsp_valid<=1;rsp_last<=beat==extra_beats;rsp_error<=model_error;
                for(lane=0;lane<8;lane=lane+1) rsp_data[lane*8+:8]<=8'(weight(row,column+lane));
            end
            if(rsp_valid && rsp_ready) begin
                rsp_valid<=0;beat<=beat+1;if(rsp_last) model_active<=0;
            end
            if(core_cmd_valid && core_cmd_ready) begin
                if(core_cmd_output!==4'(ref_slot) || core_cmd_weight!==0 || core_cmd_mask!==0 || core_cmd_activation!==0 ||
                   core_cmd_accumulate!==(ref_accumulate || commands!=0))
                    $fatal(1,"down command destination/accumulation mismatch");
                commands=commands+1;
            end
        end
    end
    task automatic submit(input integer count,features,outputs,start,slot,shift,input bit accumulate,last,
        input [31:0] tag,input [63:0] base,input integer fault=-1,mode=0);
        begin
            ref_count=count;ref_features=features;ref_outputs=outputs;ref_start=start;ref_slot=slot;
            ref_shift=shift;ref_accumulate=accumulate;ref_base=base;fault_request=fault;fault_mode=mode;
            requests=0;commands=0;
            @(negedge clk);in_valid=1;in_count=6'(count);in_dense_features=17'(features);
            in_output_count=6'(outputs);in_output_start=16'(start);in_slot=4'(slot);in_shift=6'(shift);
            in_accumulate=accumulate;in_last=last;in_tag=tag;in_weight_base=base;
            in_channels=selected_ids;in_data=selected_data;
            @(posedge clk);if(!in_ready) $fatal(1,"down executor not ready");
            @(negedge clk);in_valid=0;in_channels=0;in_data=0;in_weight_base=0;in_shift=63;
        end
    endtask
    task automatic result(input bit error,last,input [31:0] tag,input integer reqs,cmds);
        integer timeout,row,i,expected;
        reg [1083:0] held;
        begin
            timeout=0;
            while(!out_valid && timeout<30000) begin @(negedge clk);timeout=timeout+1;end
            if(!out_valid) $fatal(1,"down projection result missing");
            if({out_error,out_last,out_tag,out_count,out_start,out_slot}!==
               {error,last,tag,6'(error?0:ref_outputs),16'(ref_start),4'(ref_slot)} || requests!=reqs || commands!=cmds)
                $fatal(1,"down metadata/work mismatch error=%b requests=%0d commands=%0d",out_error,requests,commands);
            for(row=0;row<32;row=row+1) begin
                expected=0;
                if(!error && row<ref_outputs) begin
                    expected=ref_accumulate?golden[ref_slot][row]:0;
                    for(i=0;i<ref_count;i=i+1)
                        expected=expected+activation($signed(selected_data[i*32+:32]),ref_shift)*
                            weight(ref_start+row,int'(selected_ids[i*16+:16]));
                    golden[ref_slot][row]=expected;
                end
                if($test$plusargs("CORRUPT_DOWN_REFERENCE") && row==0 && !error) expected++;
                if(out_data[row*32+:32]!==32'(expected))
                    $fatal(1,"down reference matrix product mismatch row=%0d got=%0d expected=%0d",row,$signed(out_data[row*32+:32]),expected);
            end
            held={out_error,out_last,out_tag,out_count,out_start,out_slot,out_data};
            repeat(4) begin
                @(posedge clk);#1;
                if(!out_valid || in_ready || req_valid || core_load_valid || core_cmd_valid ||
                   {out_error,out_last,out_tag,out_count,out_start,out_slot,out_data}!==held)
                    $fatal(1,"down blocked result changed or issued work");
            end
            @(negedge clk);out_ready=1;@(negedge clk);out_ready=0;cases_checked++;
        end
    endtask
    task automatic fixture;
        integer i;
        begin
            selected_ids=0;selected_data=0;
            for(i=0;i<10;i=i+1) begin
                case(i)
                    0:begin selected_ids[i*16+:16]=0;selected_data[i*32+:32]=128;end
                    1:begin selected_ids[i*16+:16]=1;selected_data[i*32+:32]=256;end
                    2:begin selected_ids[i*16+:16]=7;selected_data[i*32+:32]=-384;end
                    3:begin selected_ids[i*16+:16]=8;selected_data[i*32+:32]=32767;end
                    4:begin selected_ids[i*16+:16]=9;selected_data[i*32+:32]=-32768;end
                    5:begin selected_ids[i*16+:16]=15;selected_data[i*32+:32]=0;end
                    6:begin selected_ids[i*16+:16]=16;selected_data[i*32+:32]=511;end
                    7:begin selected_ids[i*16+:16]=17;selected_data[i*32+:32]=-511;end
                    8:begin selected_ids[i*16+:16]=63;selected_data[i*32+:32]=640;end
                    default:begin selected_ids[i*16+:16]=64;selected_data[i*32+:32]=-640;end
                endcase
            end
        end
    endtask
    initial begin
        repeat(2) @(negedge clk);rst_n=1;fixture();
        submit(10,5632,3,31,1,8,0,0,32'h100,64'h100000);result(0,0,32'h100,15,2);
        selected_ids=0;selected_data=0;selected_ids[15:0]=7;selected_ids[31:16]=63;selected_ids[47:32]=4001;
        selected_data[31:0]=-128;selected_data[63:32]=1024;selected_data[95:64]=25600;
        submit(3,5632,3,31,1,8,1,0,32'h100,64'h100000);result(0,0,32'h100,9,1);
        submit(0,5632,3,31,1,8,1,1,32'h100,64'h100000);result(0,1,32'h100,0,0);
        submit(1,5632,3,31,1,8,1,1,32'h100,64'h100000);result(1,1,32'h100,0,0);
        selected_ids=0;selected_data=0;selected_ids[15:0]=65535;selected_ids[31:16]=65528;selected_ids[47:32]=65535;
        selected_data[31:0]=-127;selected_data[63:32]=23;selected_data[95:64]=101;
        submit(3,65536,1,65535,15,0,0,1,32'h200,64'h100000);result(0,1,32'h200,1,1);
        submit(0,5632,32,0,2,8,0,0,32'h300,64'h100000);result(0,0,32'h300,0,1);
        selected_ids=0;selected_data=32'd256;
        submit(1,5632,32,0,2,8,1,1,32'h300,64'h100000);result(0,1,32'h300,32,1);
        fixture();submit(10,5632,3,31,3,8,0,0,32'h400,64'h100000,10,1);result(1,0,32'h400,11,1);
        submit(1,5632,3,31,3,8,1,1,32'h400,64'h100000);result(1,1,32'h400,0,0);
        submit(10,5632,3,31,3,8,0,1,32'h401,64'h100000);result(0,1,32'h401,15,2);
        submit(10,5632,3,31,4,8,0,1,32'h500,64'h100000,0,2);result(1,1,32'h500,1,0);
        submit(1,5632,3,31,0,8,0,1,32'h600,64'h100000);result(1,1,32'h600,0,0);
        selected_ids[15:0]=6000;
        submit(1,5632,3,31,1,8,0,1,32'h601,64'h100000);result(1,1,32'h601,0,0);
        selected_ids=16'd7;selected_data=32'd256;
        submit(1,8,1,0,1,8,0,1,32'h700,64'hfffffffffffffff8);result(0,1,32'h700,1,1);
        submit(1,8,1,1,1,8,0,1,32'h701,64'hfffffffffffffff8);result(1,1,32'h701,0,0);
        fixture();submit(10,11008,32,10,5,63,0,1,32'h800,64'h100000);result(0,1,32'h800,0,2);
        submit(10,5632,3,31,1,8,0,0,32'h900,64'h100000);wait(model_active);
        @(negedge clk);rst_n=0;repeat(2) @(negedge clk);rst_n=1;
        submit(1,5632,3,31,1,8,1,1,32'h900,64'h100000);result(1,1,32'h900,0,0);
        fixture();submit(10,5632,3,31,1,8,0,1,32'h901,64'h100000);result(0,1,32'h901,15,2);
        // Cross the32-bit row-stride boundary and the last64-bit byte.
        selected_ids=16'd65535;selected_data=32'd127;
        submit(1,65536,2,65534,14,0,0,1,32'ha00,64'h00000000fffffff8);result(0,1,32'ha00,2,1);
        selected_ids=16'd7;selected_data=32'd256;
        submit(1,8,1,65535,14,8,0,1,32'ha01,64'hfffffffffff80000);result(0,1,32'ha01,1,1);
        submit(1,8,1,65535,14,8,0,1,32'ha02,64'hfffffffffff80008);result(1,1,32'ha02,0,0);
        selected_ids=16'd8;selected_data=32'd256;
        submit(1,16,1,0,14,8,0,1,32'ha05,64'h00000000fffffff8);result(0,1,32'ha05,1,1);
        submit(1,16,1,0,14,8,0,1,32'ha06,64'hfffffffffffffff8);result(1,1,32'ha06,0,0);
        selected_data=0;
        submit(1,16,1,0,14,8,0,1,32'ha07,64'hfffffffffffffff8);result(1,1,32'ha07,0,0);
        selected_data=32'd256;
        // A stalled advertised request must be stable and may be canceled only
        // by coordinated external reset of this controller and memory peer.
        force_request_hold=1;
        submit(1,5632,3,31,1,8,0,0,32'ha03,64'h100000);
        wait(req_valid);
        begin
            reg [68:0] offered;
            offered={req_address,req_length};
            repeat(6) begin @(negedge clk);if(!req_valid || {req_address,req_length}!==offered) $fatal(1,"PIPELINED_DOWN_STALLED_REQUEST_CHANGED");end
        end
        @(negedge clk);rst_n=0;repeat(2) @(negedge clk);rst_n=1;force_request_hold=0;
        fixture();submit(10,5632,3,31,1,8,0,1,32'ha04,64'h100000);result(0,1,32'ha04,15,2);
        if(cases_checked!=25) $fatal(1,"PIPELINED_DOWN_CASE_INVENTORY got=%0d",cases_checked);
        $display("PIPELINED_DOWN_PASS cases=25");
        $finish;
    end
    initial begin #5000000;$fatal(1,"down watchdog");end
endmodule
