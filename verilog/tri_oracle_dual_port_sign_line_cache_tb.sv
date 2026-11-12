`timescale 1ns/1ps

module tri_oracle_dual_port_sign_line_cache_tb #(
    parameter int ENTRIES = 128
);
    localparam logic [63:0] BASE = 64'h0000_000b_ffff_ff00;
    localparam int LINES = 176 * 256;
    localparam logic [63:0] PRIMARY_ADDRESS = 64'd0, AUXILIARY_ADDRESS = 64'd63 * 64;
    logic clk = 0, rst_n = 0, frame_start = 0;
    always #5 clk = ~clk;

    logic client_req_valid = 0, client_req_ready;
    logic [63:0] client_req_address;
    logic [5:0] client_req_length = 1;
    logic client_rsp_valid, client_rsp_ready = 0, client_rsp_last, client_rsp_error;
    logic [511:0] client_rsp_data;
    logic [1:0] mem_req_valid, mem_req_ready = 0, mem_rsp_valid = 0, mem_rsp_ready;
    logic [63:0] mem_req_address;
    logic [5:0] mem_req_length;
    logic [1:0] mem_rsp_last, mem_rsp_error;
    logic [1:0][511:0] mem_rsp_data;
    logic expected_response_port;
    logic [65:0] events[LINES*16];
    logic [511:0] packed_lines[LINES];
    int accepted[2] = '{default:0};

    tri_oracle_dual_port_sign_line_cache #(.ENTRIES(ENTRIES)) dut (.*);

    task automatic new_frame;
        frame_start = 1;
        @(negedge clk);
        frame_start = 0;
    endtask

    task automatic submit(input logic [63:0] address, input logic [5:0] length = 1);
        client_req_valid = 1;
        client_req_address = address;
        client_req_length = length;
        do @(posedge clk); while (!client_req_ready);
        @(negedge clk);
        client_req_valid = 0;
        client_req_address = 'x;
    endtask

    task automatic accept_miss(input int lane, input logic [63:0] address, input int stalls = 0);
        wait ((|mem_req_valid) || client_rsp_valid);
        for (int step = 0; step <= stalls; step++) begin
            if (mem_req_valid !== (2'b01 << lane) || mem_req_address !== address ||
                mem_req_length !== 6'd1 || client_rsp_valid || (|mem_rsp_ready))
                $fatal(1, "SIGN_LINE_MISS_ROUTE lane=%0d address=%h", lane, address);
            if (step < stalls) @(negedge clk);
        end
        mem_req_ready = 2'b01 << lane;
        @(negedge clk);
        mem_req_ready = 0;
        accepted[lane]++;
    endtask

    task automatic result(input logic [511:0] data, input bit last = 1, error = 0,
                          input int stalls = 0);
        wait (client_rsp_valid || (|mem_req_valid));
        if (|mem_req_valid) $fatal(1, "SIGN_LINE_UNEXPECTED_MISS");
        for (int step = 0; step <= stalls; step++) begin
            if (!client_rsp_valid || client_rsp_data !== data || client_rsp_last !== last ||
                client_rsp_error !== error || client_req_ready)
                $fatal(1, "SIGN_LINE_RESPONSE_MISMATCH");
            if (step < stalls) @(negedge clk);
        end
        client_rsp_ready = 1;
        @(negedge clk);
        client_rsp_ready = 0;
    endtask

    task automatic external_result(input int lane, input logic [511:0] data,
                                   input bit last = 1, error = 0, input int stalls = 0);
        // Present an unrelated response on the other port as well.
        mem_rsp_valid = 2'b11;
        mem_rsp_last = 2'b11;
        mem_rsp_error = 2'b11;
        mem_rsp_data = '0;
        mem_rsp_last[lane] = last;
        mem_rsp_error[lane] = error;
        mem_rsp_data[lane] = data;
        expected_response_port = 1'(lane);
        #1ps;
        result(data, last, error, stalls);
        mem_rsp_valid = 0;
    endtask

    always @(posedge clk) if (rst_n) begin
        if ((&mem_req_valid) || (&mem_rsp_ready) || (|mem_rsp_ready) && !client_rsp_ready)
            $fatal(1, "SIGN_LINE_RESPONSE_OWNERSHIP");
        if ((|mem_rsp_valid) && client_rsp_ready && mem_rsp_ready !== (2'b01 << expected_response_port))
            $fatal(1, "SIGN_LINE_WRONG_RESPONSE_PORT");
    end

    initial begin : exercise
        string sequence_file, packed_file;
        int requests, hits, lane, line_index;
        int initial_primary, initial_auxiliary;
        repeat (2) @(negedge clk);
        rst_n = 1;

        submit(PRIMARY_ADDRESS);
        accept_miss(0, PRIMARY_ADDRESS, 2);
        external_result(0, '1, 1, 0, 2);
        submit(PRIMARY_ADDRESS);
        result('1, 1, 0, 3);
        submit(AUXILIARY_ADDRESS);
        accept_miss(1, AUXILIARY_ADDRESS);
        external_result(1, 512'h456, 0);
        external_result(1, 512'h789);
        submit(AUXILIARY_ADDRESS);
        accept_miss(1, AUXILIARY_ADDRESS);
        external_result(1, 512'habc, 1, 1);
        submit(AUXILIARY_ADDRESS);
        accept_miss(1, AUXILIARY_ADDRESS);
        new_frame();
        external_result(1, 512'hdef);
        submit(AUXILIARY_ADDRESS);
        accept_miss(1, AUXILIARY_ADDRESS);
        external_result(1, 512'h123);
        submit(AUXILIARY_ADDRESS);
        result(512'h123);
        submit(64'd8);
        result('0, 1, 1);
        submit(PRIMARY_ADDRESS, 6'd2);
        result('0, 1, 1);

        new_frame();
        if (!$value$plusargs("SEQUENCE=%s", sequence_file) || !$value$plusargs("PACKED=%s", packed_file) ||
            !$value$plusargs("REQUESTS=%d", requests) || requests <= 0 || requests > LINES*16)
            $fatal(1, "SIGN_LINE_FIXTURES");
        $readmemh(sequence_file, events, 0, requests-1);
        $readmemh(packed_file, packed_lines);
        initial_primary = accepted[0];
        initial_auxiliary = accepted[1];
        hits = 0;
        for (int event_index = 0; event_index < requests; event_index++) begin
            logic [63:0] address;
            address = events[event_index][63:0];
            line_index = int'((address - BASE) >> 6);
            lane = int'(events[event_index][65:64]) - 1;
            if (line_index < 0 || line_index >= LINES || lane < -1 || lane > 1)
                $fatal(1, "SIGN_LINE_CONTROL_RANGE");
            submit(address);
            if (lane < 0) begin
                result(packed_lines[line_index]);
                hits++;
            end else begin
                accept_miss(lane, address);
                external_result(lane, packed_lines[line_index]);
            end
        end
        if (hits <= 0 || accepted[0] <= initial_primary || accepted[1] <= initial_auxiliary)
            $fatal(1, "SIGN_LINE_FIXTURE_COVERAGE");
        $display("SIGN_LINE_CACHE_PASS entries=%0d requests=%0d hits=%0d primary=%0d auxiliary=%0d",
                 ENTRIES, requests, hits, accepted[0]-initial_primary, accepted[1]-initial_auxiliary);
        $finish;
    end

    initial begin
        #10000000;
        $fatal(1, "SIGN_LINE_CACHE_TIMEOUT");
    end
endmodule
