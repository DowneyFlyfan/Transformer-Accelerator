`timescale 1ns/1ps
module tri_oracle_projection_strip_reader_tb;
    logic clk=0, rst_n=0;
    always #5 clk=~clk;
    logic start_valid=0, start_ready, start_token;
    logic request_valid, request_ready, response_valid=0, response_ready;
    wire [5:0] request_packet;
    wire [5:0] reader_packet;
    logic [511:0] response_data;
    logic out_valid, out_ready;
    logic [7:0] out_strip;
    logic [63:0] out_codes;
    logic out_last;

    logic [511:0] packets[64];
    logic [708:0] vectors[576];
    string packet_path, vector_path;
    int cycle, requests, strips, stalls;
    logic held=0;
    logic [72:0] held_output;

    tri_oracle_projection_strip_reader dut (.*, .request_packet(reader_packet));
`ifdef SEQUENTIAL_ADDRESS_CONTROL
    assign request_packet = {start_token, reader_packet[5:1]};
`else
    assign request_packet = reader_packet;
`endif
    assign request_ready = !response_valid && cycle%5>=2;
    assign out_ready = cycle%7>=3;
    always @(negedge clk) cycle++;
    always @(posedge clk) if (rst_n) begin
        if (request_valid && request_ready) begin
            if (request_packet !== {5'(requests%32), start_token})
                $fatal(1,"PROJECTION_STRIP_REQUEST index=%0d address=%0d",requests,request_packet);
            response_data <= packets[request_packet];
            response_valid <= 1;
            requests++;
        end
        if (response_valid && response_ready) response_valid <= 0;
        if (held && (!out_valid || {out_strip,out_codes,out_last} !== held_output))
            $fatal(1,"PROJECTION_STRIP_STALL");
        held = out_valid && !out_ready;
        held_output = {out_strip,out_codes,out_last};
        if (held) stalls++;
        if (out_valid && out_ready) begin
            if (strips>=512 || out_strip !== 8'(strips) || out_codes !== vectors[strips][343:280] ||
                out_last !== (strips%256==255))
                $fatal(1,"PROJECTION_STRIP_CONTENT row=%0d",strips);
            strips++;
        end
    end
    initial begin
        if (!$value$plusargs("PACKETS=%s",packet_path) || !$value$plusargs("VECTORS=%s",vector_path))
            $fatal(1,"Missing trained projection packets");
        $readmemh(packet_path,packets);
        $readmemh(vector_path,vectors);
        repeat (3) @(negedge clk);
        rst_n=1;
        for (int token=0; token<2; token++) begin
            start_token=1'(token);
            start_valid=1;
            do @(posedge clk); while (start_ready !== 1'b1);
            @(negedge clk);
            start_valid=0;
            wait (start_ready);
            @(negedge clk);
        end
        if (strips!=512 || requests!=64 || stalls==0)
            $fatal(1,"PROJECTION_STRIP_COUNT strips=%0d requests=%0d stalls=%0d",strips,requests,stalls);
        $display("PROJECTION_STRIP_PASS packets=64 strips=512 codes=4096 stalls=%0d",stalls);
        $finish;
    end
    initial begin #30000; $fatal(1,"PROJECTION_STRIP_TIMEOUT"); end
endmodule
