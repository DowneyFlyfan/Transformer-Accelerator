`timescale 1ns/1ps
module tri_oracle_sparse_weight_dma_tb;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,in_valid=0,in_bank=0,done_ready=0;
    reg [511:0] in_channels=0;
    reg [5:0] in_count=0;
    reg [63:0] in_base=0;
    reg [9:0] in_features=0;
    reg [8:0] in_start=0;
    reg [4:0] in_length=0;
    wire in_ready,done_valid,done_error,req_valid,rsp_ready,load_valid;
    wire [63:0] req_address;
    wire [4:0] req_length,load_address;
    wire [31:0] load_row_enable;
    wire [2047:0] load_data;
    reg rsp_valid=0,rsp_last=0,rsp_error=0;
    reg [63:0] rsp_data=0;
    integer cycle=0,requests=0,writes=0,model_row=0,model_beat=0,model_length=0;
    integer ref_count=0,ref_features=0,ref_start=0,ref_length=0,error_mode=0;
    reg ref_bank=0,model_active=0;
    reg [63:0] ref_base=0;
    reg [511:0] ref_channels=0;
    wire req_ready=!model_active && !rsp_valid && cycle%4!=0;
    wire load_ready=cycle%5!=1;
    reg setup_valid=0;
    reg [4:0] setup_address=0;
    wire core_load_valid=setup_valid || (load_valid && load_ready);
    wire [9:0] core_load_address=setup_valid?{5'd0,setup_address}:{5'd0,load_address};
    wire [2047:0] core_load_data=setup_valid?{256{8'd2}}:load_data;
    wire [31:0] core_load_rows=setup_valid?32'hffffffff:load_row_enable;
    wire core_load_error,cmd_ready,done,result_valid;
    wire [3:0] done_output;
    wire [1023:0] result_data;
    reg cmd_valid=0,cmd_accumulate=0,read_valid=0;
    reg [4:0] cmd_weight=0;
    reg auxiliary_load=0,activation_load=0;
    wire [1:0] core_kind=auxiliary_load?2'd2:(activation_load?2'd1:2'd0);
    wire [2047:0] core_data=auxiliary_load?{{1792{1'b0}},{256{1'b1}}}:
        (activation_load?{{1984{1'b0}},{8{8'd1}}}:core_load_data);
    wire actual_load=auxiliary_load || activation_load || core_load_valid;
    integer done_count=0;
    tri_oracle_sparse_weight_dma dut(.*);
    tri_oracle_memory_compute core (
        .clk(clk),.rst_n(rst_n),.load_valid(actual_load),.load_kind(core_kind),
        .load_addr(core_load_address),.load_data(core_data),.load_row_enable(core_load_rows),
        .load_error(core_load_error),.cmd_valid(cmd_valid),.cmd_ready(cmd_ready),
        .cmd_weight(cmd_weight),.cmd_activation(10'd0),.cmd_mask(5'd0),.cmd_output(4'd0),
        .cmd_accumulate(cmd_accumulate),.done_valid(done),.done_output(done_output),
        .read_valid(read_valid),.read_output(4'd0),.result_valid(result_valid),.result_data(result_data)
    );
    function automatic [63:0] memory_word(input integer channel,feature_strip);
        integer lane,value;
        begin
            for(lane=0;lane<8;lane=lane+1) begin
                value=(channel*7+(feature_strip*8+lane)*3)%251-125;
                memory_word[lane*8+:8]=8'(value);
            end
        end
    endfunction
    always @(posedge clk) begin
        if(!rst_n) begin cycle<=0;model_active<=0;rsp_valid<=0;end
        else begin
            cycle<=cycle+1;
            if(core_load_error) $fatal(1,"DMA generated an illegal core write");
            if(done) begin
                if(done_output!==0) $fatal(1,"wrong DMA compute destination");
                done_count=done_count+1;
            end
            if(req_valid && req_ready) begin
                if(requests>=ref_count || req_length!==5'(ref_length) ||
                   req_address!==ref_base+64'(ref_channels[requests*16+:16])*64'(ref_features)*64'd8+
                                 64'(ref_start)*64'd8)
                    $fatal(1,"sparse burst address/order/length mismatch");
                model_row<=requests;model_length<=ref_length;model_beat<=0;model_active<=1;
                requests=requests+1;
            end
            if(model_active && !rsp_valid && cycle%3!=0) begin
                rsp_valid<=1;
                rsp_data<=memory_word(int'(ref_channels[model_row*16+:16]),ref_start+model_beat);
                rsp_error<=(error_mode==2 && model_beat==1);
                if(error_mode==1) rsp_last<=(model_beat==0);
                else if(error_mode==3) rsp_last<=(model_beat==model_length);
                else rsp_last<=(model_beat==model_length-1);
            end
            if(rsp_valid && rsp_ready) begin
                rsp_valid<=0;model_beat<=model_beat+1;
                if(rsp_last) model_active<=0;
            end
            if(load_valid && load_ready) begin
                if(!rsp_valid || rsp_error || rsp_last!=(model_beat==model_length-1) ||
                   load_address!=={ref_bank,4'(model_beat)} ||
                   load_row_enable!==(32'd1<<model_row) ||
                   load_data[model_row*64+:64]!==rsp_data)
                    $fatal(1,"burst beat mapped to the wrong row/word");
                writes=writes+1;
            end
        end
    end
    task automatic compute_sums;
        integer s,r,l,expected,n;
        reg [63:0] word_value;
        begin
            done_count=0;
            for(s=0;s<ref_length;s=s+1) begin
                @(negedge clk);cmd_valid=1;cmd_weight=5'((ref_bank?16:0)+s);cmd_accumulate=(s!=0);
                @(posedge clk);if(!cmd_ready) $fatal(1,"DMA-loaded compute issue stalled");
            end
            @(negedge clk);cmd_valid=0;n=0;
            while(done_count<ref_length && n<30) begin @(negedge clk);n=n+1;end
            if(done_count!=ref_length) $fatal(1,"DMA-loaded compute completion missing");
            read_valid=1;
            @(posedge clk);#1;
            if(!result_valid) $fatal(1,"DMA-loaded readback missing");
            for(r=0;r<32;r=r+1) begin
                expected=0;
                if(r<ref_count) begin
                    for(s=0;s<ref_length;s=s+1) begin
                        word_value=memory_word(int'(ref_channels[r*16+:16]),ref_start+s);
                        for(l=0;l<8;l=l+1) expected=expected+int'($signed(word_value[l*8+:8]));
                    end
                end else expected=16*ref_length;
                if($signed(result_data[r*32+:32])!==expected)
                    $fatal(1,"DMA-loaded arithmetic/isolation mismatch row=%0d got=%0d expected=%0d",
                        r,$signed(result_data[r*32+:32]),expected);
            end
            @(negedge clk);read_valid=0;
        end
    endtask
    task automatic run_case(input integer count,length,start,features,input bit bank,
        input integer mode,input [63:0] base,input bit expect_error,input integer expect_requests,
        input bit check_compute);
        integer r,s,timeout;
        reg [96:0] held_request;
        begin
            ref_count=count;ref_length=length;ref_start=start;ref_features=features;
            ref_bank=bank;ref_base=base;error_mode=mode;requests=0;writes=0;
            for(r=0;r<32;r=r+1) ref_channels[r*16+:16]=16'(2*r);
            if(count==3) begin ref_channels[15:0]=2;ref_channels[31:16]=35;ref_channels[47:32]=65535;end
            if(check_compute) begin
                for(s=0;s<length;s=s+1) begin
                    @(negedge clk);setup_valid=1;setup_address=5'((bank?16:0)+s);
                end
                @(negedge clk);setup_valid=0;
            end
            @(negedge clk);in_valid=1;in_channels=ref_channels;in_count=6'(count);
            in_base=base;in_features=10'(features);in_start=9'(start);in_length=5'(length);in_bank=bank;
            @(posedge clk);if(!in_ready) $fatal(1,"DMA not ready for next tile");
            @(negedge clk);in_valid=0;in_base=0;in_channels=0;in_features=0;timeout=0;
            while(!done_valid && timeout<5000) begin
                @(negedge clk);timeout=timeout+1;
                if(req_valid && !req_ready) begin
                    held_request={req_address,req_length,28'd0};
                    @(negedge clk);timeout=timeout+1;
                    if(!req_valid || {req_address,req_length,28'd0}!==held_request)
                        $fatal(1,"blocked burst request changed");
                end
            end
            if(!done_valid || done_error!==expect_error || requests!=expect_requests)
                $fatal(1,"DMA completion mismatch: error=%b requests=%0d expected=%0d",done_error,requests,expect_requests);
            if(!expect_error && writes!=count*length) $fatal(1,"DMA dropped or duplicated data beats");
            repeat(4) begin
                @(negedge clk);
                if(!done_valid || done_error!==expect_error || in_ready || req_valid || load_valid)
                    $fatal(1,"blocked DMA completion changed or issued work");
            end
            @(negedge clk);done_ready=1;
            @(negedge clk);done_ready=0;
            if(check_compute) compute_sums();
        end
    endtask
    initial begin
        repeat(2) @(negedge clk);rst_n=1;
        @(negedge clk);activation_load=1;
        @(negedge clk);activation_load=0;auxiliary_load=1;
        @(negedge clk);auxiliary_load=0;
        run_case(3,3,16,19,1,0,64'h1000,0,3,1);
        run_case(32,16,0,19,0,0,64'h8000,0,32,1);
        run_case(0,0,0,0,0,0,0,0,0,0);
        run_case(33,3,0,19,0,0,64'h1000,1,0,0);
        run_case(3,0,0,19,0,0,64'h1000,1,0,0);
        run_case(3,4,16,19,0,0,64'h1000,1,0,0);
        run_case(3,3,0,19,0,0,64'h1001,1,0,0);
        run_case(3,3,0,19,0,0,64'hfffffffffffffff8,1,0,0);
        run_case(3,3,0,19,0,1,64'h1000,1,1,0);
        run_case(3,3,0,19,0,2,64'h1000,1,1,0);
        run_case(3,3,0,19,0,3,64'h1000,1,1,0);
        run_case(3,3,16,19,1,0,64'h1000,0,3,1);
        $display("PASS: sparse burst addresses, row writes, two banks, 32-row tiles, signed compute sums, stalls, shape/address faults, memory errors, early/late last, recovery");
        $finish;
    end
    initial begin #1000000;$fatal(1,"watchdog timeout");end
endmodule
