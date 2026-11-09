`timescale 1ns/1ps
// Independent full-grid reference with deterministic input/output stalls.
module tri_oracle_token_merger_random_tb;
    localparam W=6, H=5, N=W*H;
    reg clk=0;
    always #5 clk=~clk;
    reg rst_n=0, in_valid=0, out_ready=0, size_ready=0;
    reg [3:0] in_sign=0;
    wire in_ready, out_valid, size_valid, done;
    wire [4:0] out_index, out_origin, size_origin, size_count;
    wire [1:0] out_merge;
    reg [3:0] sign_vector [0:N-1];
    integer origin [0:N-1];
    integer kind [0:N-1];
    integer sizes [0:N-1];
    integer i, b, matches_up, matches_left;
    integer source_idx, output_idx, size_idx, cycle;
    reg [31:0] random_state;
    tri_oracle_token_merger #(.IMG_W(W),.IMG_H(H),.SIGN_W(4),
                               .MATCH_THRESHOLD(3)) dut (.*);
    initial begin
        random_state=32'hc01212ab;
        for (i=0;i<N;i=i+1) begin
            random_state=random_state*32'd1664525+32'd1013904223;
            sign_vector[i]=random_state[19:16];
            origin[i]=i;
            kind[i]=0;
            sizes[i]=0;
        end
        for (i=0;i<N;i=i+1) begin
            matches_up=0;
            matches_left=0;
            if (i>=W)
                for (b=0;b<4;b=b+1)
                    matches_up=matches_up+(sign_vector[i][b] ==
                                sign_vector[origin[i-W]][b]);
            if ((i%W)!=0)
                for (b=0;b<4;b=b+1)
                    matches_left=matches_left+(sign_vector[i][b] ==
                                  sign_vector[origin[i-1]][b]);
            if (i>=W && matches_up>=3) begin
                origin[i]=origin[i-W]; kind[i]=2;
            end else if ((i%W)!=0 && matches_left>=3) begin
                origin[i]=origin[i-1]; kind[i]=1;
            end
            sizes[origin[i]]=sizes[origin[i]]+1;
        end
        source_idx=0; output_idx=0; size_idx=0;
        repeat (2) @(negedge clk);
        rst_n=1;
        for (cycle=0;cycle<2000 && !done;cycle=cycle+1) begin
            @(negedge clk);
            in_valid=(source_idx<N) && ((cycle%5)!=1);
            if (source_idx<N) in_sign=sign_vector[source_idx];
            out_ready=(cycle%4)!=0;
            size_ready=(cycle%3)!=0;
            @(posedge clk);
            if (out_valid && out_ready) begin
                if (output_idx>=N || out_index !== output_idx ||
                    out_origin !== origin[output_idx] ||
                    out_merge !== kind[output_idx])
                    $fatal(1,"token %0d: got index=%0d origin=%0d kind=%0d, expected origin=%0d kind=%0d",
                           output_idx,out_index,out_origin,out_merge,
                           origin[output_idx],kind[output_idx]);
                output_idx=output_idx+1;
            end
            if (size_valid && size_ready) begin
                while (size_idx<N && origin[size_idx]!=size_idx)
                    size_idx=size_idx+1;
                if (size_idx>=N || size_origin !== size_idx ||
                    size_count !== sizes[size_idx])
                    $fatal(1,"size %0d: got origin=%0d count=%0d, expected count=%0d",
                           size_idx,size_origin,size_count,sizes[size_idx]);
                size_idx=size_idx+1;
            end
            if (in_valid && in_ready) source_idx=source_idx+1;
        end
        if (!done || source_idx!=N || output_idx!=N)
            $fatal(1,"unfinished: done=%0d input=%0d output=%0d",done,source_idx,output_idx);
        while (size_idx<N && origin[size_idx]!=size_idx)
            size_idx=size_idx+1;
        if (size_idx!=N) $fatal(1,"not all sizes emitted: %0d",size_idx);
        $display("PASS: %0d token decisions, all sizes, deterministic stalls",N);
        $finish;
    end
endmodule
