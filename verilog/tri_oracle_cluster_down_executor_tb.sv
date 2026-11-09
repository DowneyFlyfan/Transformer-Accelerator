`timescale 1ns/1ps
module tri_oracle_cluster_down_executor_tb;
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
    wire cluster_load_valid, cluster_load_error, cluster_cmd_valid, cluster_cmd_ready;
    wire raw_cluster_load_error;
    wire [3:0] raw_cluster_out_output;
    reg inject_load_error=0,inject_bad_slot=0,block_request=0,post_command_fault=0;
    wire cluster_cmd_accumulate, cluster_out_valid, cluster_out_ready, cluster_rst_n;
    wire [1:0] cluster_load_core, cluster_load_kind;
    wire [9:0] cluster_load_address, cluster_cmd_activation;
    wire [2047:0] cluster_load_data;
    wire [31:0] cluster_load_rows;
    wire [4:0] cluster_cmd_weight, cluster_cmd_mask;
    wire [3:0] cluster_cmd_output, cluster_out_output;
    wire [1023:0] cluster_out_data;
    integer core_instances=0,cluster_instances=0;
    integer weight_mask_memories=0,activation_memories=0,result_memories=0;
    integer cases_checked=0,exact_values=0;
    reg request_held=0;
    reg [68:0] held_request=0;
    integer cycle=0,requests=0,commands=0,beat=0,extra_beats=0;
    integer ref_count=0,ref_outputs=0,ref_features=0,ref_start=0,ref_slot=0,ref_shift=0;
    integer fault_request=-1,fault_mode=0;
    reg ref_accumulate=0,model_active=0,model_error=0;
    reg [63:0] ref_base=0,model_address=0;
    reg [511:0] selected_ids=0;
    reg [1023:0] selected_data=0;
    integer golden[0:15][0:31];
    wire req_ready=!model_active && !rsp_valid && cycle%4!=0 && !block_request;
    assign cluster_load_error=raw_cluster_load_error || inject_load_error;
    assign cluster_out_output=raw_cluster_out_output ^ (inject_bad_slot?4'd1:4'd0);
    tri_oracle_cluster_down_executor dut(.*);
    tri_oracle_sram_compute_cluster cluster (
        .clk(clk), .rst_n(cluster_rst_n), .load_valid(cluster_load_valid),
        .load_core(cluster_load_core), .load_kind(cluster_load_kind),
        .load_addr(cluster_load_address), .load_data(cluster_load_data),
        .load_row_enable(cluster_load_rows), .load_error(raw_cluster_load_error),
        .cmd_valid(cluster_cmd_valid), .cmd_ready(cluster_cmd_ready),
        .cmd_weight(cluster_cmd_weight), .cmd_mask(cluster_cmd_mask),
        .cmd_activation(cluster_cmd_activation), .cmd_output(cluster_cmd_output),
        .cmd_accumulate(cluster_cmd_accumulate), .cmd_reduce(2'd0),
        .out_valid(cluster_out_valid), .out_ready(cluster_out_ready),
        .out_output(raw_cluster_out_output), .out_data(cluster_out_data));
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
        if(!rst_n) begin cycle<=0;model_active<=0;rsp_valid<=0;request_held=0;end
        else begin
            cycle<=cycle+1;
            if(!cluster_rst_n && (model_active || rsp_valid || req_valid || request_held))
                $fatal(1,"CLUSTER_RESET_BEFORE_ADVERTISED_OR_ACCEPTED_MEMORY_WORK_DRAINED");
            if(request_held && (req_valid!==1'b1 || {req_address,req_length}!==held_request))
                $fatal(1,"UNSTABLE_SHARED_DOWN_MEMORY_REQUEST");
            request_held=req_valid && !req_ready;
            held_request={req_address,req_length};
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
            if(cluster_cmd_valid && cluster_cmd_ready) begin
                if(cluster_cmd_output!==4'(ref_slot) || cluster_cmd_weight!==0 || cluster_cmd_mask!==0 || cluster_cmd_activation!==0 ||
                   cluster_cmd_accumulate!==(ref_accumulate || commands!=0))
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
            requests=0;commands=0;post_command_fault=0;
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
            if(!out_valid) begin
                $display("DOWN_DEBUG state=%0d child=%0d/%0d/%0d/%0d cmd=%b/%b load=%b/%b mem=%b owner=%0d req=%b/%b issued=%0d awaits=%b aggregate=%b read=%b seen=%b done=%b result=%b childout=%b",
                    dut.state,dut.engines[0].state,dut.engines[1].state,dut.engines[2].state,dut.engines[3].state,
                    dut.child_cmd_valid,dut.child_cmd_ready,dut.child_load_valid,dut.child_load_ready,
                    dut.memory_busy,dut.memory_owner,req_valid,req_ready,commands,dut.await_aggregate,
                    dut.aggregate_valid,dut.child_read_valid,dut.read_seen,dut.done_pulse,dut.result_pulse,dut.child_out_valid);
                $display("DOWN_FLAGS abort=%b metadata=%b cmd=%b read=%b unexpected=%b load_error=%b outvalid=%b loadfound=%b cursor=%b clusterload=%b childfault=%b/%b/%b/%b",
                    dut.abort_now,dut.metadata_mismatch,dut.command_mismatch,dut.read_mismatch,dut.unexpected_result,
                    cluster_load_error,cluster_out_valid,dut.load_found,dut.load_cursor,cluster_load_valid,
                    dut.engines[0].fault,dut.engines[1].fault,dut.engines[2].fault,dut.engines[3].fault);
                $fatal(1,"down projection result missing");
            end
            if({out_error,out_last,out_tag,out_count,out_start,out_slot}!==
               {error,last,tag,6'(error?0:ref_outputs),16'(ref_start),4'(ref_slot)})
                $fatal(1,"down metadata/work mismatch error=%b requests=%0d commands=%0d",out_error,requests,commands);
            if(model_active || rsp_valid) $fatal(1,"DOWN_RETURNED_BEFORE_MEMORY_DRAIN");
            if(reqs==0 && requests!=0) $fatal(1,"EMPTY_OR_INVALID_DOWN_PACKET_READ_MEMORY");
            if(commands!=((error && !post_command_fault)?0:1)) $fatal(1,"WRONG_FOUR_CORE_COMMAND_COUNT commands=%0d",commands);
            for(row=0;row<32;row=row+1) begin
                expected=0;
                if(!error && row<ref_outputs) begin
                    expected=ref_accumulate?golden[ref_slot][row]:0;
                    for(i=0;i<ref_count;i=i+1)
                        expected=expected+activation($signed(selected_data[i*32+:32]),ref_shift)*
                            weight(ref_start+row,int'(selected_ids[i*16+:16]));
                    golden[ref_slot][row]=expected;
                end
                if($test$plusargs("CORRUPT_REFERENCE") && !error && row==0) expected++;
                if(out_data[row*32+:32]!==32'(expected))
                    $fatal(1,"down reference matrix product mismatch row=%0d got=%0d expected=%0d",row,$signed(out_data[row*32+:32]),expected);
            end
            cases_checked++;exact_values+=32;
            $display("CLUSTER_DOWN_CASE_PASS index=%0d error=%0d requests=%0d commands=%0d",cases_checked,error,requests,commands);
            held={out_error,out_last,out_tag,out_count,out_start,out_slot,out_data};
            repeat(4) begin
                @(posedge clk);#1;
                if(!out_valid || in_ready || req_valid || cluster_load_valid || cluster_cmd_valid ||
                   {out_error,out_last,out_tag,out_count,out_start,out_slot,out_data}!==held)
                    $fatal(1,"down blocked result changed or issued work");
            end
            @(negedge clk);out_ready=1;@(negedge clk);out_ready=0;
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
        #1;
        if(core_instances!=4 || cluster_instances!=1 || weight_mask_memories!=72 ||
           activation_memories!=8 || result_memories!=40) $fatal(1,"WRONG_CLUSTER_DOWN_COMPILED_HIERARCHY");
        $display("CLUSTER_DOWN_ACTUAL_HIERARCHY cores=4 clusters=1 compiled_memories=120");
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
        // All four shards contain distinct nonzero selected values.
        selected_ids=0;selected_data=0;
        for(integer n=0;n<32;n++) begin
            selected_ids[n*16+:16]=16'((n*173+97)%5632);
            selected_data[n*32+:32]=32'((n%2==0?1:-1)*(n*5+1));
        end
        submit(32,5632,32,160,7,1,0,0,32'h1000,64'h100000);result(0,0,32'h1000,-1,-1);
        submit(32,5632,32,160,7,1,1,0,32'h1000,64'h100000);result(0,0,32'h1000,-1,-1);
        submit(0,5632,32,160,7,1,1,1,32'h1000,64'h100000);result(0,1,32'h1000,0,1);
        // A frame abort invalidates every retained owner context, not only its destination.
        fixture();
        submit(3,5632,3,31,1,1,0,0,32'h1101,64'h100000);result(0,0,32'h1101,-1,-1);
        submit(10,5632,7,64,15,1,0,0,32'h1115,64'h100000);result(0,0,32'h1115,-1,-1);
        submit(10,5632,3,31,7,1,0,0,32'h1107,64'h100000);result(0,0,32'h1107,-1,-1);
        submit(1,5632,3,31,7,1,1,0,32'hdead,64'h100000);result(1,0,32'hdead,0,0);
        submit(1,5632,3,31,1,1,1,1,32'h1101,64'h100000);result(1,1,32'h1101,0,0);
        submit(1,5632,7,64,15,1,1,1,32'h1115,64'h100000);result(1,1,32'h1115,0,0);
        submit(1,5632,7,64,15,1,0,1,32'h1116,64'h100000);result(0,1,32'h1116,-1,-1);
        selected_ids=0;selected_data=1;
        submit(33,5632,1,0,1,0,0,1,32'h1200,64'h100000);result(1,1,32'h1200,0,0);
        submit(1,5632,0,0,1,0,0,1,32'h1201,64'h100000);result(1,1,32'h1201,0,0);
        submit(1,5632,33,0,1,0,0,1,32'h1202,64'h100000);result(1,1,32'h1202,0,0);
        submit(1,7,1,0,1,0,0,1,32'h1203,64'h100000);result(1,1,32'h1203,0,0);
        submit(1,65544,1,0,1,0,0,1,32'h1204,64'h100000);result(1,1,32'h1204,0,0);
        submit(1,5632,1,0,1,0,0,1,32'h1205,64'h100001);result(1,1,32'h1205,0,0);
        submit(1,5632,2,65535,1,0,0,1,32'h1206,64'h100000);result(1,1,32'h1206,0,0);
        // Empty packets never inspect a weight address, even at the final aligned base.
        selected_ids=7;selected_data=17;
        submit(1,5632,3,31,1,0,0,0,32'h1300,64'h100000);result(0,0,32'h1300,-1,-1);
        submit(0,5632,3,31,1,0,1,1,32'h1300,64'hfffffffffffffff8);result(0,1,32'h1300,0,1);
        submit(0,65536,7,65529,15,0,0,0,32'h1301,64'hfffffffffffffff8);result(0,0,32'h1301,0,1);
        submit(0,65536,7,65529,15,0,1,1,32'h1301,64'hfffffffffffffff8);result(0,1,32'h1301,0,1);
        submit(0,5632,1,0,1,0,0,1,32'h1302,64'hfffffffffffffff9);result(1,1,32'h1302,0,0);
        // Faults at the physical cluster boundary must preserve advertised memory ownership.
        fixture();submit(10,5632,3,31,1,8,0,1,32'h1400,64'h100000);
        block_request=1;
        wait(dut.request_pending);
        @(negedge clk);inject_load_error=1;
        repeat(3) begin
            @(negedge clk);
            if(!req_valid || !cluster_rst_n) $fatal(1,"HELD_REQUEST_CANCELLED_BEFORE_DRAIN");
        end
        block_request=0;result(1,1,32'h1400,-1,0);inject_load_error=0;
        submit(3,5632,3,31,1,8,0,1,32'h1401,64'h100000);result(0,1,32'h1401,-1,1);
        submit(3,5632,3,31,7,8,0,1,32'h1410,64'h100000);post_command_fault=1;
        wait(cluster_out_valid);@(negedge clk);inject_bad_slot=1;
        result(1,1,32'h1410,-1,1);inject_bad_slot=0;
        submit(3,5632,3,31,7,8,0,1,32'h1411,64'h100000);result(0,1,32'h1411,-1,1);
        submit(3,5632,3,31,15,8,0,1,32'h1420,64'h100000);post_command_fault=1;
        wait(cluster_cmd_valid && cluster_cmd_ready);@(posedge clk);@(negedge clk);inject_load_error=1;
        result(1,1,32'h1420,-1,1);inject_load_error=0;
        submit(3,5632,3,31,15,8,0,1,32'h1421,64'h100000);result(0,1,32'h1421,-1,1);
        $display("CLUSTER_DOWN_PHYSICAL_BOUNDARY_FAULTS_PASS cases=3 recoveries=3");
        $display("CLUSTER_DOWN_PASS cases=%0d exact_values=%0d",cases_checked,exact_values);
        $display("PASS: sparse down projection, original-ID column gathers, byte cache, signed requantization, 5632/11008/65536 strides, accumulated packets, reserved slots, empty finalize, zero inputs, faults/framing/address overflow, stalls, reset");
        $finish;
    end
    initial begin #5000000;$fatal(1,"down watchdog");end
endmodule

module tri_oracle_cluster_down_instance_count #(parameter int KIND = 0) ();
  initial begin
    case (KIND)
      0: $root.tri_oracle_cluster_down_executor_tb.core_instances++;
      1: $root.tri_oracle_cluster_down_executor_tb.cluster_instances++;
      2: $root.tri_oracle_cluster_down_executor_tb.weight_mask_memories++;
      3: $root.tri_oracle_cluster_down_executor_tb.activation_memories++;
      4: $root.tri_oracle_cluster_down_executor_tb.result_memories++;
    endcase
  end
endmodule

bind tri_oracle_sram_memory_compute tri_oracle_cluster_down_instance_count
    #(.KIND(0)) count_actual_core ();
bind tri_oracle_sram_compute_cluster tri_oracle_cluster_down_instance_count
    #(.KIND(1)) count_actual_cluster ();
bind TS5N28HPCPSVTA32X128M2FW tri_oracle_cluster_down_instance_count
    #(.KIND(2)) count_actual_weight_mask ();
bind TS5N28HPCPSVTA512X64M4F tri_oracle_cluster_down_instance_count
    #(.KIND(3)) count_actual_activation ();
bind TS6N28HPCPSVTA16X128M2F tri_oracle_cluster_down_instance_count
    #(.KIND(4)) count_actual_result ();
