`timescale 1ns/1ps
// Independent real-valued SiLU oracle; catches sign, scaling, rounding,
// saturation, lookup indexing, payload/tag skew, and lost elastic handshakes.
module tri_oracle_silu_gate_tb;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,in_valid=0;
    reg signed [15:0] in_gate=0,in_up=0;
    reg [15:0] in_tag=0;
    wire in_ready,out_valid;
    wire signed [15:0] out_data;
    wire [15:0] out_tag;
    integer cycle=0,head=0,tail=0,n,u,k,max_error=0,err;
    integer expected[0:66000],tolerance[0:66000];
    reg [15:0] tags[0:66000];
    reg previous_stall;
    reg [31:0] held;
    wire out_ready=cycle%7!=2 && cycle%7!=3;
    tri_oracle_silu_gate dut(.*);
    function automatic integer reference(input integer gate,up);
        real x,y;
        integer rounded;
        begin
            x=real'(gate)/256.0;
            y=(x/(1.0+$exp(-x)))*real'(up);
            rounded=y>=0.0?$rtoi(y+0.5):-$rtoi(-y+0.5);
            reference=rounded>32767?32767:(rounded < -32768 ? -32768:rounded);
        end
    endfunction
    always @(posedge clk) begin
        if(!rst_n) begin head=0;tail=0;cycle<=0;previous_stall=0;end
        else begin
            cycle<=cycle+1;
            if(in_valid && in_ready) begin
                expected[tail]=reference(int'($signed(in_gate)),int'($signed(in_up)));
                tolerance[tail]=(2*(in_up<0?-int'(in_up):int'(in_up))+255)/256+1;
                tags[tail]=in_tag;tail=tail+1;
            end
            if(out_valid && out_ready) begin
                if(head>=tail || out_tag!==tags[head]) $fatal(1,"SiLU result order/tag mismatch");
                if((^out_data)===1'bx) $fatal(1,"unknown SiLU numerical result");
                err=int'($signed(out_data))-expected[head];if(err<0) err=-err;
                if(err>tolerance[head]) $fatal(1,"SiLU mathematical error got=%0d expected=%0d error=%0d",out_data,expected[head],err);
                if(tolerance[head]==3 && err>max_error) max_error=err;
                head=head+1;
            end
            previous_stall=out_valid && !out_ready;held={out_tag,out_data};
            #1;
            if(previous_stall && (!out_valid || {out_tag,out_data}!==held))
                $fatal(1,"SiLU blocked result changed");
        end
    end
    task automatic send(input integer gate,up,tag);
        begin
            in_valid=1;in_gate=16'(gate);in_up=16'(up);in_tag=16'(tag);
            @(posedge clk);while(!in_ready) @(posedge clk);
            @(negedge clk);
        end
    endtask
    task automatic drain;
        integer timeout;
        begin
            in_valid=0;timeout=0;
            while(head!=tail && timeout<100) begin @(negedge clk);timeout=timeout+1;end
            if(head!=tail || out_valid) $fatal(1,"SiLU drain timeout");
        end
    endtask
    initial begin
        repeat(2) @(negedge clk);rst_n=1;
        send(1024,256,0);
        // Every possible signed16-bit Q8 gate value with up=1.0.
        for(n=-32768;n<32768;n=n+1) send(n,256,n+32768);
        for(k=0;k<7;k=k+1) begin
            case(k)
                0:u=-32768;1:u=32767;2:u=-256;3:u=0;4:u=1;5:u=-1;default:u=4096;
            endcase
            for(n=-2048;n<=2048;n=n+64) send(n,u,n+2048);
        end
        drain();
        $display("SiLU exhaustive Q8 gate maximum observed error: %0d output-code units",max_error);
        send(2048,32767,1);send(-256,-32768,2);
        rst_n=0;in_valid=0;repeat(2) @(negedge clk);
        if(out_valid) $fatal(1,"SiLU reset leaked valid data");
        rst_n=1;send(0,32767,3);send(32767,-32768,4);drain();
        $display("PASS: exhaustive 65536 gate codes, signed gated multiplication, real-valued oracle, quantization error bound, saturation, elastic stalls, tags, reset");
        $finish;
    end
    initial begin #5000000;$fatal(1,"SiLU watchdog");end
endmodule
