`timescale 1ns/1ps
module tri_oracle_token_merger_tb;
    localparam IMG_W = 4;
    localparam IMG_H = 3;
    localparam TOTAL = IMG_W * IMG_H;
    localparam INDEX_W = $clog2(TOTAL+1);
    localparam SIZE_W = $clog2(TOTAL+1);
    reg clk = 0;
    always #5 clk = ~clk;
    reg rst_n = 0;
    reg in_valid = 0;
    wire in_ready;
    reg [3:0] in_sign = 0;
    wire out_valid;
    reg out_ready = 1;
    wire [INDEX_W-1:0] out_index, out_origin;
    wire [1:0] out_merge;
    wire size_valid;
    reg size_ready = 1;
    wire [INDEX_W-1:0] size_origin;
    wire [SIZE_W-1:0] size_count;
    wire done;
    integer decisions = 0;
    integer sizes = 0;
    reg [3:0] signs [0:TOTAL-1];
    integer expected_origin [0:TOTAL-1];
    integer expected_kind [0:TOTAL-1];
    integer expected_size_origin [0:2];
    integer expected_size [0:2];

    tri_oracle_token_merger #(
        .IMG_W(IMG_W), .IMG_H(IMG_H), .SIGN_W(4), .MATCH_THRESHOLD(3)
    ) dut (.*);

    task send(input [3:0] sign_bits);
        begin
            @(negedge clk);
            in_sign = sign_bits;
            in_valid = 1;
            while (!in_ready)
                @(negedge clk);
            @(posedge clk);
            #1 in_valid = 0;
        end
    endtask

    always @(posedge clk) begin
        if (rst_n && out_valid && out_ready) begin
            if (decisions >= TOTAL || out_index !== decisions ||
                out_origin !== expected_origin[decisions] ||
                out_merge !== expected_kind[decisions]) begin
                $display("decision %0d: got index=%0d origin=%0d kind=%0d",
                         decisions, out_index, out_origin, out_merge);
                $fatal(1, "incorrect token merge mapping");
            end
            decisions = decisions + 1;
        end
        if (rst_n && size_valid && size_ready) begin
            if (sizes >= 3 || size_origin !== expected_size_origin[sizes] ||
                size_count !== expected_size[sizes]) begin
                $display("size %0d: got origin=%0d count=%0d",
                         sizes, size_origin, size_count);
                $fatal(1, "incorrect token size");
            end
            sizes = sizes + 1;
        end
    end

    initial begin
        signs[0]=4'b0000; signs[1]=4'b0001;
        signs[2]=4'b1111; signs[3]=4'b1110;
        signs[4]=4'b0000; signs[5]=4'b0011;
        signs[6]=4'b1111; signs[7]=4'b1111;
        signs[8]=4'b1000; signs[9]=4'b0011;
        signs[10]=4'b0001; signs[11]=4'b1110;
        expected_origin[0]=0; expected_origin[1]=0;
        expected_origin[2]=2; expected_origin[3]=2;
        expected_origin[4]=0; expected_origin[5]=5;
        expected_origin[6]=2; expected_origin[7]=2;
        expected_origin[8]=0; expected_origin[9]=5;
        expected_origin[10]=5; expected_origin[11]=2;
        expected_kind[0]=0; expected_kind[1]=1;
        expected_kind[2]=0; expected_kind[3]=1;
        expected_kind[4]=2; expected_kind[5]=0;
        expected_kind[6]=2; expected_kind[7]=2;
        expected_kind[8]=2; expected_kind[9]=2;
        expected_kind[10]=1; expected_kind[11]=2;
        expected_size_origin[0]=0; expected_size[0]=4;
        expected_size_origin[1]=2; expected_size[1]=5;
        expected_size_origin[2]=5; expected_size[2]=3;

        repeat (3) @(negedge clk);
        rst_n = 1;
        for (integer i=0; i<TOTAL; i=i+1)
            send(signs[i]);
        wait(done);
        if (decisions != TOTAL || sizes != 3)
            $fatal(1, "missing token decisions or size records");
        $display("PASS: %0d token decisions and %0d survivor sizes", decisions, sizes);
        $finish;
    end
    initial begin
        #5000;
        $fatal(1, "simulation timeout");
    end
endmodule
