`timescale 1ns/1ps
module tri_oracle_channel_compactor_tb;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,in_valid=0,in_last=0,in_error=0,out_ready=0;
    reg [10:0] in_group=0;
    reg [31:0] in_skip=0;
    wire in_ready,out_valid,out_last,out_error;
    wire [5:0] out_count;
    wire [511:0] out_channels;
    wire [255:0] out_lane_enable;
    tri_oracle_channel_compactor dut(.*);
    task automatic send(input [10:0] group_id,input [31:0] skip,input bit last,error);
        begin
            @(negedge clk);in_valid=1;in_group=group_id;in_skip=skip;in_last=last;in_error=error;
            @(posedge clk);
            while(!in_ready) @(posedge clk);
            @(negedge clk);in_valid=0;
        end
    endtask
    task automatic expect_batch(input integer count,input bit last,error,input integer mode,base);
        integer cycles,row,expected_id;
        reg [775:0] held;
        begin
            cycles=0;
            while(!out_valid && cycles<200) begin @(negedge clk);cycles=cycles+1;end
            if(!out_valid) $fatal(1,"dispatch batch missing");
            if(out_count!==6'(count) || out_last!==last || out_error!==error)
                $fatal(1,"dispatch metadata mismatch: count=%0d last=%b error=%b",out_count,out_last,out_error);
            for(row=0;row<32;row=row+1) begin
                expected_id=0;
                if(row<count) begin
                    case(mode)
                        1:expected_id=(row<16)?2*row:2*row+1;
                        2:expected_id=(row==0)?64:95;
                        default:expected_id=base+row;
                    endcase
                end
                if(out_channels[row*16+:16]!==16'(expected_id) ||
                   out_lane_enable[row*8+:8]!==((row<count)?8'hff:8'h00))
                    $fatal(1,"packed channel/lane mismatch at row %0d",row);
            end
            held={out_count,out_last,out_error,out_channels,out_lane_enable};
            repeat(4) begin
                @(posedge clk);#1;
                if(!out_valid || {out_count,out_last,out_error,out_channels,out_lane_enable}!==held)
                    $fatal(1,"stalled dispatch output changed");
            end
            @(negedge clk);out_ready=1;
            @(negedge clk);out_ready=0;
        end
    endtask
    initial begin
        repeat(2) @(negedge clk);rst_n=1;
        send(0,32'haaaaaaaa,0,0);
        send(1,32'h55555555,1,0);
        expect_batch(32,0,0,1,0); // Two half-dense groups become one full batch.
        expect_batch(0,1,0,0,0); // A terminal empty batch marks exact multiples.
        send(7,32'hffffffff,1,0);
        expect_batch(0,1,0,0,0); // All skipped: no weight or compute rows.
        send(2,32'h7ffffffe,1,0);
        expect_batch(2,1,0,2,0);
        send(3,32'hffffffff,1,1); // Bad prediction must preserve every channel.
        expect_batch(32,0,1,0,96);
        expect_batch(0,1,1,0,0);
        fork
            begin
                send(0,0,0,0);
                send(1,0,0,0);
                send(2,32'hffffffff,1,1);
            end
            begin
                repeat(80) @(negedge clk);
                if(in_ready) $fatal(1,"full descriptor queue did not backpressure input");
                expect_batch(32,0,0,0,0);
                // The later error/end packet must not change the stalled
                // second batch's error or last metadata.
                repeat(50) @(negedge clk);
                expect_batch(32,0,0,0,32);
                expect_batch(32,0,1,0,64);
                expect_batch(0,1,1,0,0);
            end
        join
        send(5,0,0,0);
        repeat(10) @(negedge clk);
        rst_n=0;
        @(negedge clk);rst_n=1;
        send(0,32'hffffffff,1,0);
        expect_batch(0,1,0,0,0);
        $display("PASS: cross-group channel packing, fetch/lane masks, partial/empty batches, bounded queue, output stability, error fallback, reset");
        $finish;
    end
    initial begin #1000000;$fatal(1,"watchdog timeout");end
endmodule
