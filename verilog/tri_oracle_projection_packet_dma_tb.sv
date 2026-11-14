`timescale 1ns/1ps
module tri_oracle_projection_packet_dma_tb;
    localparam logic [63:0] BASE = 64'h02000000;
    logic clk=0, rst_n=0;
    always #5 clk=~clk;
    logic packet_request_valid=0, packet_request_ready;
    logic [5:0] packet_request_address;
    logic packet_response_valid, packet_response_ready=0, packet_response_error;
    logic [511:0] packet_response_data;
    logic req_valid, req_ready=0;
    logic [63:0] req_address;
    logic [4:0] req_length;
    logic rsp_valid=0, rsp_ready, rsp_last, rsp_error;
    logic [63:0] rsp_data;
    logic [511:0] packets[64];
    string fixture;
    int read_requests=0, beats=0;

    tri_oracle_projection_packet_dma #(.CACHE_BASE(BASE)) dut (.*);

    task automatic transaction(input int index, fault);
        int count;
        logic [63:0] expected_address;
        expected_address = BASE + 64'(index/2)*65536 + 64'(index%2)*64;
        packet_request_address=6'(index);
        packet_request_valid=1;
        @(posedge clk);
        if (!packet_request_ready) $fatal(1,"PROJECTION_DMA_NOT_READY index=%0d",index);
        @(negedge clk);
        packet_request_valid=0;
        repeat (3) begin
            @(posedge clk);
            if (!req_valid || req_address !== expected_address || req_length !== 5'd8 ||
                packet_request_ready || packet_response_valid)
                $fatal(1,"PROJECTION_DMA_ADDRESS index=%0d address=%h expected=%h",index,req_address,expected_address);
        end
        @(negedge clk);
        req_ready=1;
        @(posedge clk);
        if (!req_valid) $fatal(1,"PROJECTION_DMA_LOST_REQUEST");
        read_requests++;
        @(negedge clk);
        req_ready=0;
        count = fault==1 ? 3 : fault==3 ? 10 : 8;
        for (int beat=0; beat<count; beat++) begin
            if (beat%2==0) @(negedge clk);
            rsp_valid=1;
            rsp_data=beat<8 ? packets[index][64*beat +: 64] : 64'hfeedc0de;
            rsp_last=beat==count-1;
            rsp_error=fault==2 && beat==2;
            @(posedge clk);
            if (!rsp_ready || packet_response_valid || req_valid)
                $fatal(1,"PROJECTION_DMA_BEAT index=%0d beat=%0d",index,beat);
            beats++;
            @(negedge clk);
            rsp_valid=0;
        end
        repeat (3) begin
            @(posedge clk);
            if (!packet_response_valid || packet_response_error !== (fault!=0) ||
                packet_response_data !== (fault==0 ? packets[index] : 512'd0) ||
                packet_request_ready || rsp_ready)
                $fatal(1,"PROJECTION_DMA_RESPONSE index=%0d fault=%0d",index,fault);
        end
        @(negedge clk);
        packet_response_ready=1;
        @(negedge clk);
        packet_response_ready=0;
        if (packet_response_valid) $fatal(1,"PROJECTION_DMA_RESPONSE_REPEATED");
    endtask

    initial begin
        if (!$value$plusargs("PACKETS=%s",fixture)) $fatal(1,"Missing trained projection packets");
        $readmemh(fixture,packets);
        repeat (3) @(negedge clk);
        rst_n=1;
        for (int token=0; token<2; token++)
            for (int head=0; head<32; head++)
                transaction(2*head+token,0);
        for (int fault=1; fault<=3; fault++) begin
            transaction(17,fault);
            transaction(30+fault,0);
        end
        if (read_requests!=70 || beats!=557) $fatal(1,"PROJECTION_DMA_COUNTS reads=%0d beats=%0d",read_requests,beats);
        $display("PROJECTION_PACKET_DMA_PASS trained_packets=64 codes=4096 read_beats=512 faults=3 recoveries=3");
        $finish;
    end
    initial begin #40000; $fatal(1,"PROJECTION_DMA_TIMEOUT"); end
endmodule
