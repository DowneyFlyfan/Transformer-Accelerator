`timescale 1ns/1ps
module tri_oracle_predicted_dispatch_tb;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,in_valid=0,in_last=0,in_group_last=0,in_frame_error=0,out_ready=0;
    reg [10:0] in_group=0;
    reg [127:0] norm_activations=0;
    reg [255:0] gate_weight_signs=0,up_weight_signs=0;
    wire in_ready,out_valid,out_last,out_error;
    wire [5:0] out_count;
    wire [511:0] out_channels;
    wire [255:0] out_lane_enable;
    reg [511:0] saved_channels;
    reg [255:0] saved_lanes;
    integer channel,strip,row,lane;
    reg [255:0] signs;
    reg load_valid=0,cmd_valid=0,cmd_accumulate=0,read_valid=0;
    reg [1:0] load_kind=0;
    reg [9:0] load_addr=0;
    reg [2047:0] load_data=0;
    wire load_error,cmd_ready,done_valid,result_valid;
    wire [3:0] done_output;
    wire [1023:0] result_data;
    integer done_count=0,fetch_rows=0,compute_batches=0;
    tri_oracle_predicted_dispatch dut(.*);
    tri_oracle_memory_compute compute (
        .clk(clk),.rst_n(rst_n),.load_valid(load_valid),.load_kind(load_kind),
        .load_addr(load_addr),.load_data(load_data),.load_row_enable(32'hffffffff),.load_error(load_error),
        .cmd_valid(cmd_valid),.cmd_ready(cmd_ready),.cmd_weight(5'd0),
        .cmd_activation(10'd0),.cmd_mask(5'd0),.cmd_output(4'd0),
        .cmd_accumulate(cmd_accumulate),.done_valid(done_valid),.done_output(done_output),
        .read_valid(read_valid),.read_output(4'd0),.result_valid(result_valid),.result_data(result_data)
    );
    always @(posedge clk) if(rst_n && done_valid) begin
        if(done_output!==0) $fatal(1,"wrong compute destination");
        done_count=done_count+1;
    end
    always @(posedge clk) if(rst_n && out_valid && out_ready && out_count!=0) begin
        fetch_rows=fetch_rows+int'(out_count);
        compute_batches=compute_batches+1;
    end
    task automatic send(input bit last,input [10:0] group_id,input bit group_last,input [255:0] weight_signs);
        begin
            @(negedge clk);in_valid=1;in_last=last;in_group=group_id;in_group_last=group_last;
            norm_activations={8{16'd1024}};
            gate_weight_signs=weight_signs;up_weight_signs=weight_signs;
            @(posedge clk);while(!in_ready) @(posedge clk);
            @(negedge clk);in_valid=0;
        end
    endtask
    task automatic batch(input integer count,input bit last,error,input integer mode);
        integer cycles,r,expected;
        reg [775:0] held;
        begin
            cycles=0;
            while(!out_valid && cycles<200) begin @(negedge clk);cycles=cycles+1;end
            if(!out_valid) $fatal(1,"predicted dispatch batch missing");
            if({out_count,out_last,out_error}!=={6'(count),last,error})
                $fatal(1,"prediction metadata did not follow its frame");
            for(r=0;r<32;r=r+1) begin
                expected=0;
                if(r<count) begin
                    case(mode)
                        0:expected=(r<16)?2*r:2*r+1;
                        2:expected=(r==0)?0:33;
                        default:expected=64+r;
                    endcase
                end
                if(out_channels[r*16+:16]!==16'(expected) ||
                   out_lane_enable[r*8+:8]!==((r<count)?8'hff:8'h00))
                    $fatal(1,"prediction/dispatch row mismatch %0d",r);
            end
            if(count!=0 && mode==0) begin saved_channels=out_channels;saved_lanes=out_lane_enable;end
            held={out_count,out_last,out_error,out_channels,out_lane_enable};
            repeat(5) begin
                @(posedge clk);#1;
                if(!out_valid || {out_count,out_last,out_error,out_channels,out_lane_enable}!==held)
                    $fatal(1,"prediction dispatch changed while stalled");
            end
            @(negedge clk);out_ready=1;
            @(negedge clk);out_ready=0;
        end
    endtask
    task automatic load(input [1:0] kind,input [2047:0] data);
        begin
            @(negedge clk);load_valid=1;load_kind=kind;load_data=data;
            @(posedge clk);#1;
            if(load_error || cmd_ready) $fatal(1,"compute configuration failed");
            @(negedge clk);load_valid=0;
        end
    endtask
    initial begin
        repeat(2) @(negedge clk);rst_n=1;
        for(channel=0;channel<32;channel=channel+1)
            signs[channel*8+:8]=(channel%2==0)?8'h00:8'h55;
        send(0,0,0,signs);send(1,11'd999,1,signs);
        for(channel=0;channel<32;channel=channel+1)
            signs[channel*8+:8]=(channel%2!=0)?8'h00:8'h55;
        send(0,1,1,signs);send(1,11'd998,0,signs);
        batch(32,0,0,0);batch(0,1,0,0);
        // Model an external weight fetch using the emitted original IDs.
        // Only 32 of the original 64 rows are fetched. Their INT8 weights
        // are +2; skipped rows would have balanced +/-2 weights and zero sums.
        // In this fixture normalized 4.0 uses INT8 code 1 with scale 4.0.
        load_data=0;
        for(row=0;row<32;row=row+1) begin
            if(!((saved_channels[row*16+:16]<32 && !saved_channels[row*16]) ||
                 (saved_channels[row*16+:16]>=32 && saved_channels[row*16])))
                $fatal(1,"fetch requested a skipped channel");
            for(lane=0;lane<8;lane=lane+1) load_data[(row*8+lane)*8+:8]=8'd2;
        end
        load(0,load_data);load(1,{{1984{1'b0}},{8{8'd1}}});
        load(2,{{1792{1'b0}},saved_lanes});
        for(strip=0;strip<2;strip=strip+1) begin
            @(negedge clk);cmd_valid=1;cmd_accumulate=(strip!=0);
            @(posedge clk);if(!cmd_ready) $fatal(1,"packed compute issue stalled");
        end
        @(negedge clk);cmd_valid=0;
        wait(done_count==2);
        @(negedge clk);read_valid=1;
        @(posedge clk);#1;
        if(!result_valid) $fatal(1,"packed compute result missing");
        for(row=0;row<32;row=row+1)
            if($signed(result_data[row*32+:32])!==32'sd32)
                $fatal(1,"packed compute sum mismatch at channel %0d",saved_channels[row*16+:16]);
        @(negedge clk);read_valid=0;
        if(fetch_rows!=32 || compute_batches!=1) $fatal(1,"compaction did not reduce row/batch work");
        send(0,3,1,{32{8'h55}});send(1,0,0,{32{8'h55}});
        batch(0,1,0,0);
        // One-strip frames arrive consecutively: the second frame's first
        // strip coincides with retirement of the first prediction result.
        @(negedge clk);in_valid=1;in_last=1;in_group=0;in_group_last=0;
        gate_weight_signs={32{8'h55}};gate_weight_signs[7:0]=0;
        up_weight_signs=gate_weight_signs;
        @(posedge clk);if(!in_ready) $fatal(1,"first short frame stalled");
        @(negedge clk);in_group=1;in_group_last=1;
        gate_weight_signs={32{8'h55}};gate_weight_signs[15:8]=0;
        up_weight_signs=gate_weight_signs;
        @(posedge clk);if(!in_ready) $fatal(1,"second short frame stalled");
        @(negedge clk);in_valid=0;in_last=0;
        batch(2,1,0,2);
        for(strip=0;strip<513;strip=strip+1)
            send(strip==512,strip==0?11'd2:11'd100,strip==0,{32{8'h55}});
        batch(32,0,1,1);batch(0,1,1,1);
        // Upstream framing faults must keep all rows, even if this final
        // strip itself is valid and prediction would otherwise skip them.
        in_frame_error=1;
        send(0,11'd2,1,{32{8'h55}});
        in_frame_error=0;
        send(1,11'd999,0,{32{8'h55}});
        batch(32,0,1,1);batch(0,1,1,1);
        $display("PASS: full-vector prediction-to-dispatch, first-strip tags, packed IDs/masks, skipped fetches, packed memory-core sums, stalls, overlong fallback");
        $finish;
    end
    initial begin #1000000;$fatal(1,"watchdog timeout");end
endmodule
