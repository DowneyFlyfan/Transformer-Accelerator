`timescale 1ns/1ps

module tri_oracle_wide_read_arbiter_tb;
    logic clk = 0, rst_n = 0;
    always #5 clk = ~clk;

    logic [1:0][1:0] client_req_valid = '0, client_req_ready;
    logic [1:0][1:0][63:0] client_req_address;
    logic [1:0][1:0][5:0] client_req_length;
    logic [1:0][1:0] client_rsp_valid, client_rsp_ready = '0, client_rsp_last, client_rsp_error;
    logic [1:0][1:0][511:0] client_rsp_data;
    logic [1:0] mem_req_valid, mem_req_ready = '0;
    logic [1:0][63:0] mem_req_address;
    logic [1:0][5:0] mem_req_length;
    logic [1:0] mem_rsp_valid = '0, mem_rsp_ready, mem_rsp_last = '0, mem_rsp_error = '0;
    logic [1:0][511:0] mem_rsp_data = '0;
    int requests = 0, responses = 0, stalls = 0;

    for (genvar lane = 0; lane < 2; lane++) begin : lanes
        tri_oracle_wide_read_arbiter dut (
            .clk, .rst_n, .client_req_valid(client_req_valid[lane]), .client_req_ready(client_req_ready[lane]),
            .client_req_address(client_req_address[lane]), .client_req_length(client_req_length[lane]),
            .client_rsp_valid(client_rsp_valid[lane]), .client_rsp_ready(client_rsp_ready[lane]),
            .client_rsp_last(client_rsp_last[lane]), .client_rsp_error(client_rsp_error[lane]),
            .client_rsp_data(client_rsp_data[lane]), .mem_req_valid(mem_req_valid[lane]),
            .mem_req_ready(mem_req_ready[lane]), .mem_req_address(mem_req_address[lane]),
            .mem_req_length(mem_req_length[lane]), .mem_rsp_valid(mem_rsp_valid[lane]),
            .mem_rsp_ready(mem_rsp_ready[lane]), .mem_rsp_last(mem_rsp_last[lane]),
            .mem_rsp_error(mem_rsp_error[lane]), .mem_rsp_data(mem_rsp_data[lane])
        );
    end

    always @(posedge clk) if (rst_n) begin
        requests += $countones(mem_req_valid & mem_req_ready);
        responses += $countones(mem_rsp_valid & mem_rsp_ready);
        stalls += $countones(mem_rsp_valid & ~mem_rsp_ready);
    end

    task automatic check_request(input int lane, owner, input bit ready);
        if (mem_req_valid[lane] !== 1'b1 || mem_req_address[lane] !== client_req_address[lane][owner] ||
            mem_req_length[lane] !== client_req_length[lane][owner] ||
            client_req_ready[lane] !== (ready ? (2'b01 << owner) : 2'b00))
            $fatal(1, "WIDE_READ_REQUEST lane=%0d owner=%0d ready=%0d", lane, owner, ready);
    endtask

    task automatic drive_response(input int lane, owner, tag, input bit ready, last, fault);
        mem_rsp_valid[lane] = 1;
        mem_rsp_last[lane] = last;
        mem_rsp_error[lane] = fault;
        client_rsp_ready[lane] = ready ? (2'b01 << owner) : (2'b10 >> owner);
        for (int word = 0; word < 8; word++)
            mem_rsp_data[lane][64*word +: 64] = 64'hface000000000000 | (64'(tag) << 8) | 64'(word);
    endtask

    task automatic check_response(input int lane, owner, input bit ready);
        if (client_rsp_valid[lane] !== (2'b01 << owner) || mem_rsp_ready[lane] !== ready ||
            mem_req_valid[lane] !== 1'b0)
            $fatal(1, "WIDE_READ_RESPONSE_OWNER lane=%0d owner=%0d ready=%0d", lane, owner, ready);
        if ({client_rsp_data[lane][owner], client_rsp_last[lane][owner], client_rsp_error[lane][owner]} !==
            {mem_rsp_data[lane], mem_rsp_last[lane], mem_rsp_error[lane]})
            $fatal(1, "WIDE_READ_FULL_WIDTH_RESPONSE lane=%0d owner=%0d", lane, owner);
    endtask

    initial begin
        client_req_address = {{64'h9000, 64'h8000}, {64'h5000, 64'h4000}};
        client_req_length = {{6'd1, 6'd1}, {6'd1, 6'd2}};
        repeat (2) @(negedge clk);
        rst_n = 1;

        client_req_valid = {2'b10, 2'b01};
        @(posedge clk);
        check_request(0, 0, 0);
        check_request(1, 1, 0);
        @(negedge clk);
        client_req_valid = '1;
        @(posedge clk);
        check_request(0, 0, 0);
        check_request(1, 1, 0);
        @(negedge clk);
        mem_req_ready = '1;
        @(posedge clk);
        check_request(0, 0, 1);
        check_request(1, 1, 1);
        @(negedge clk);
        client_req_valid = {2'b01, 2'b10};

        drive_response(0, 0, 10, 1, 0, 0);
        drive_response(1, 1, 11, 0, 1, 1);
        @(posedge clk);
        check_response(0, 0, 1);
        check_response(1, 1, 0);
        @(negedge clk);
        drive_response(0, 0, 12, 0, 1, 0);
        drive_response(1, 1, 11, 1, 1, 1);
        @(posedge clk);
        check_response(0, 0, 0);
        check_response(1, 1, 1);
        @(negedge clk);
        mem_rsp_valid[1] = 0;
        @(posedge clk);
        check_response(0, 0, 0);
        check_request(1, 0, 1);
        @(negedge clk);
        client_req_valid[1] = '0;
        drive_response(0, 0, 12, 1, 1, 0);
        drive_response(1, 0, 13, 1, 1, 0);
        @(posedge clk);
        check_response(0, 0, 1);
        check_response(1, 0, 1);
        @(negedge clk);
        mem_rsp_valid = '0;
        client_req_valid[0] = '1;
        @(posedge clk);
        check_request(0, 1, 1);
        @(negedge clk);
        client_req_valid = '0;
        drive_response(0, 1, 14, 1, 1, 0);
        @(posedge clk);
        check_response(0, 1, 1);
        @(negedge clk);
        mem_rsp_valid = '0;
        if (requests != 4 || responses != 5 || stalls != 3)
            $fatal(1, "WIDE_READ_INVENTORY requests=%0d responses=%0d stalls=%0d", requests, responses, stalls);
        $display("WIDE_READ_ARBITER_PASS requests=%0d responses=%0d stalls=%0d", requests, responses, stalls);
        $finish;
    end

    initial begin #10000; $fatal(1, "Wide read arbitration timed out"); end
endmodule
