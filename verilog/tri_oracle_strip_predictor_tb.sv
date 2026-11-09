`timescale 1ns/1ps
// Literal full-vector results catch loss of partial counts, counter overflow,
// incorrect gate/up intersection, signed absolute-value overflow and stalls.
module tri_oracle_strip_predictor_tb;
    reg clk=0; always #5 clk=~clk;
    reg rst_n=0,in_valid=0,in_last=0,out_ready=0;
    reg [127:0] norm_activations=0;
    reg [255:0] gate_weight_signs=0,up_weight_signs=0;
    wire in_ready,out_valid,out_error;
    wire [31:0] gate_nearzero_mask,up_nearzero_mask,skip_mask;
    wire [12:0] outlier_count;
    integer strip,channel;
    tri_oracle_strip_predictor dut(.*);
    task automatic send(input bit last,input [127:0] a,input [255:0] g,u);
        begin
            @(negedge clk);in_valid=1;in_last=last;
            norm_activations=a;gate_weight_signs=g;up_weight_signs=u;
            @(posedge clk);
            if(!in_ready) $fatal(1,"unexpected input stall within a frame");
            @(negedge clk);in_valid=0;in_last=0;
        end
    endtask
    task automatic result(input [31:0] g,u,s,input [12:0] count,input bit error);
        begin
            if(!out_valid) $fatal(1,"full-vector prediction missing");
            if({gate_nearzero_mask,up_nearzero_mask,skip_mask,outlier_count,out_error}
                !== {g,u,s,count,error})
                $fatal(1,"wrong full-vector prediction: g=%h u=%h skip=%h count=%0d error=%b",
                       gate_nearzero_mask,up_nearzero_mask,skip_mask,outlier_count,out_error);
            // A producer may present a following frame while the result stalls.
            in_valid=1;in_last=1;norm_activations=0;
            repeat(3) begin
                @(posedge clk);#1;
                if(in_ready || !out_valid ||
                    {gate_nearzero_mask,up_nearzero_mask,skip_mask,outlier_count,out_error}
                    !== {g,u,s,count,error}) $fatal(1,"blocked result changed");
            end
            @(negedge clk);in_valid=0;in_last=0;out_ready=1;
            @(negedge clk);out_ready=0;
            if(out_valid) $fatal(1,"result did not retire");
        end
    endtask
    task automatic long_frame(input integer length);
        begin
            for(strip=0;strip<length;strip=strip+1) begin
                @(negedge clk);in_valid=1;in_last=(strip==length-1);
                norm_activations={8{16'd1024}};
                gate_weight_signs={32{8'ha5}};up_weight_signs={32{8'h5a}};
                @(posedge clk);
                if(!in_ready) $fatal(1,"one-strip-per-cycle throughput lost");
            end
            @(negedge clk);in_valid=0;in_last=0;
        end
    endtask
    initial begin
        repeat(2) @(negedge clk);rst_n=1;
        send(0,{8{16'd1024}},256'd0,256'd0);
        repeat(2) @(negedge clk);
        send(1,{8{16'd1024}},{256{1'b1}},{256{1'b1}});
        result(32'hffffffff,32'hffffffff,32'hffffffff,13'd16,0);
        send(0,{8{16'd1024}},256'd0,256'd0);
        send(1,{8{16'd1024}},{256{1'b1}},256'd0);
        result(32'hffffffff,32'd0,32'd0,13'd16,0);
        send(1,{8{16'd768}},256'd0,256'd0);
        result(0,0,0,0,0); // Exactly three sigma is not an outlier.
        send(1,{{3{16'hfd00}},{3{16'd768}},16'hfcff,16'd769},256'd0,{256{1'b1}});
        result(32'hffffffff,32'hffffffff,32'hffffffff,13'd2,0);
        send(1,{8{16'h8000}},{256{1'b1}},{32{8'h55}});
        result(0,32'hffffffff,0,13'd8,0);
        @(negedge clk);
        for(channel=0;channel<32;channel=channel+1)
            up_weight_signs[channel*8+:8]=(channel%2)?8'h55:8'h00;
        send(1,{8{16'd1024}},{32{8'h55}},up_weight_signs);
        result(32'hffffffff,32'haaaaaaaa,32'haaaaaaaa,13'd8,0);
        send(0,{8{16'd1024}},256'd0,256'd0);
        @(negedge clk);rst_n=0;
        @(negedge clk);rst_n=1;
        send(1,{8{16'd1024}},{32{8'h55}},{32{8'haa}});
        result(32'hffffffff,32'hffffffff,32'hffffffff,13'd8,0);
        // Retiring a result and accepting the next frame in the same cycle
        // must neither lose that frame nor carry over its predecessor's counts.
        @(negedge clk);out_ready=1;in_valid=1;in_last=1;
        norm_activations={8{16'd1024}};
        gate_weight_signs={32{8'h55}};up_weight_signs={32{8'haa}};
        @(posedge clk);#1;
        if(!out_valid || skip_mask!==32'hffffffff || outlier_count!==13'd8 || out_error)
            $fatal(1,"first consecutive frame failed");
        @(negedge clk);norm_activations=0;
        @(posedge clk);#1;
        if(!out_valid || skip_mask!==32'd0 || outlier_count!==13'd0 || out_error)
            $fatal(1,"consecutive frame lost or inherited old counts");
        @(negedge clk);in_valid=0;in_last=0;
        @(posedge clk);#1;
        if(out_valid) $fatal(1,"phantom consecutive-frame result");
        @(negedge clk);out_ready=0;
        long_frame(512); // 4096 outliers: no narrow partial-count wraparound.
        result(32'hffffffff,32'hffffffff,32'hffffffff,13'd4096,0);
        long_frame(513); // Overlong frames report an error and skip nothing.
        result(0,0,0,13'd4096,1);
        send(1,{8{16'd1024}},{32{8'h55}},{32{8'haa}});
        result(32'hffffffff,32'hffffffff,32'hffffffff,13'd8,0);
        $display("PASS: full-vector strip prediction, 4096 features, continuous strips, signed extrema, gate/up intersection, backpressure, reset, overlong-frame recovery");
        $finish;
    end
    initial begin #1000000;$fatal(1,"watchdog timeout");end
endmodule
