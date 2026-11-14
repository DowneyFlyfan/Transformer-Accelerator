`timescale 1ns/1ps
module tri_oracle_projection_read_bridge_tb;
    logic clk = 0, rst_n = 0, projection_enabled = 0;
    always #5 clk = ~clk;
    logic req_valid = 0, req_wide = 0, req_ready;
    logic [63:0] req_address = 0;
    logic [5:0] req_length = 0;
    logic rsp_valid, rsp_last, rsp_error, rsp_ready = 0;
    logic [511:0] rsp_data;
    logic external_req_valid, external_req_ready = 0, external_req_wide;
    logic [63:0] external_req_address;
    logic [5:0] external_req_length;
    logic external_rsp_valid = 0, external_rsp_last = 0, external_rsp_error = 0, external_rsp_ready;
    logic [511:0] external_rsp_data = 512'h55 << 504;
    logic local_req_valid, local_req_ready = 0;
    logic [8:0] local_req_word;
    logic [4:0] local_req_length;
    logic local_rsp_valid = 0, local_rsp_last = 0, local_rsp_error = 0, local_rsp_ready;
    logic [63:0] local_rsp_data = 64'h0123456789abcdef;
    logic idle;
    bit mutate;
    int requests, responses;

    tri_oracle_projection_read_bridge dut (.*);

    task automatic issue(input bit local_bank, enable, wide,
                         input logic [63:0] addr, input logic [5:0] len);
        req_valid = 1;
        projection_enabled = enable;
        req_wide = wide;
        req_address = addr;
        req_length = len;
        repeat (2) begin
            @(posedge clk);
            if ({idle, req_ready, local_req_valid, external_req_valid} !==
                {1'b1, 1'b0, local_bank, !local_bank})
                $fatal(1, "PROJECTION_BRIDGE_REQUEST_ROUTE");
            if (local_bank && {local_req_word, local_req_length} !==
                {addr[11:3], ((addr[2:0] != 0 || len[5]) ? 5'd0 : len[4:0])})
                $fatal(1, "PROJECTION_BRIDGE_REQUEST_LOCAL");
            if (!local_bank && {external_req_wide, external_req_address, external_req_length} !== {wide, addr, len})
                $fatal(1, "PROJECTION_BRIDGE_REQUEST_EXTERNAL");
            @(negedge clk);
        end
        local_req_ready = local_bank;
        external_req_ready = !local_bank;
        @(posedge clk);
        if (req_ready !== 1'b1) $fatal(1, "PROJECTION_BRIDGE_REQUEST_ACCEPT");
        @(negedge clk);
        local_req_ready = 0;
        external_req_ready = 0;
        // Leave another request offered while the current burst owns the bus.
        projection_enabled = !enable;
        req_wide = !wide;
        req_address = ~addr;
        requests++;
    endtask

    task automatic drain(input bit local_bank, last, fault);
        logic [511:0] expected;
        local_rsp_valid = 1;
        external_rsp_valid = 1;
        local_rsp_last = local_bank ? last : !last;
        external_rsp_last = local_bank ? !last : last;
        local_rsp_error = local_bank ? fault : !fault;
        external_rsp_error = local_bank ? !fault : fault;
        expected = local_bank && !mutate ? {448'b0, local_rsp_data} : external_rsp_data;
        for (int step = 0; step < 3; step++) begin
            rsp_ready = step == 2;
            @(posedge clk);
            if ({idle, req_ready, local_req_valid, external_req_valid, rsp_valid, rsp_last, rsp_error, rsp_data}
                !== {4'b0, 1'b1, last, fault, expected})
                $fatal(1, "PROJECTION_BRIDGE_RESPONSE_ROUTE local=%b step=%0d", local_bank, step);
            if ({local_rsp_ready, external_rsp_ready} !==
                {(rsp_ready && local_bank), (rsp_ready && !local_bank)})
                $fatal(1, "PROJECTION_BRIDGE_RESPONSE_OWNER");
            @(negedge clk);
        end
        local_rsp_valid = 0;
        external_rsp_valid = 0;
        rsp_ready = 0;
        req_valid = 0;
        responses++;
    endtask

    initial begin
        mutate = $test$plusargs("WRONG_SOURCE");
        repeat (2) @(negedge clk);
        rst_n = 1;
        issue(1, 1, 0, 64'h10000, 6'd2);
        drain(1, 0, 0);
        drain(1, 1, 0);
        issue(0, 1, 1, 64'h10000, 6'd32);
        drain(0, 1, 0);
        issue(0, 0, 0, 64'h10000, 6'd1);
        drain(0, 1, 0);
        issue(0, 1, 0, 64'h11000, 6'd1);
        drain(0, 1, 0);
        issue(1, 1, 0, 64'h10007, 6'd1);
        drain(1, 1, 1);
        issue(1, 1, 0, 64'h10ff8, 6'd32);
        drain(1, 1, 1);
        issue(1, 1, 0, 64'h10ff8, 6'd1);
        rst_n = 0;
        local_rsp_valid = 1;
        external_rsp_valid = 1;
        rsp_ready = 1;
        @(posedge clk);
        if (!idle || rsp_valid || local_rsp_ready || external_rsp_ready)
            $fatal(1, "PROJECTION_BRIDGE_RESET");
        if (requests != 7 || responses != 7) $fatal(1, "PROJECTION_BRIDGE_INVENTORY");
        $display("PROJECTION_BRIDGE_PASS requests=%0d responses=%0d reset=1", requests, responses);
        $finish;
    end
endmodule
