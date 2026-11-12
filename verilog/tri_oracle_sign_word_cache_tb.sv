`timescale 1ns/1ps

module tri_oracle_sign_word_cache_tb;
    parameter bit BYPASS = 0;
    localparam logic [63:0] GATE_BASE = 64'h0000000bffffff00;
    localparam logic [63:0] UP_BASE = 64'h0000000dffffff00;
    logic clk = 0;
    always #5 clk = ~clk;

    logic rst_n = 0, frame_start = 0;
    logic client_req_valid = 0, client_req_ready;
    logic [63:0] client_req_address = 0;
    logic [4:0] client_req_length = 0;
    logic client_rsp_valid, client_rsp_ready = 1, client_rsp_last, client_rsp_error;
    logic [63:0] client_rsp_data;
    logic mem_req_valid, mem_req_ready;
    logic [63:0] mem_req_address;
    logic [4:0] mem_req_length;
    logic mem_rsp_valid, mem_rsp_ready, mem_rsp_last, mem_rsp_error;
    logic [63:0] mem_rsp_data;

    logic [1023:0] outlier_pairs [0:15];
    int mem_reads = 0, logical_reads = 0, cycle = 0;
    int remaining = 0, latency = 0, epoch = 0;
    logic [63:0] word_address = 0;
    logic inject_error = 0, inject_extra_beat = 0;

    if (BYPASS) begin : control
        assign {mem_req_valid, mem_req_address, mem_req_length} =
            {client_req_valid, client_req_address, client_req_length};
        assign client_req_ready = mem_req_ready;
        assign {client_rsp_valid, client_rsp_last, client_rsp_error, client_rsp_data} =
            {mem_rsp_valid, mem_rsp_last, mem_rsp_error, mem_rsp_data};
        assign mem_rsp_ready = client_rsp_ready;
    end else begin : experiment
        tri_oracle_sign_word_cache dut (.*);
    end

    function automatic logic [63:0] memory_data(input logic [63:0] address);
        return 64'h831c20aef44ea938 ^ (address * 64'd197) ^ (64'(epoch) << 37);
    endfunction

    // Delayed memory with intermittent request stalls. The data depend on
    // all address bits and the frame, so aliases and stale hits are visible.
    assign mem_req_ready = rst_n && remaining == 0 && cycle % 7 != 0;
    assign mem_rsp_valid = rst_n && remaining != 0 && latency == 0;
    assign mem_rsp_last = remaining == 1;
    assign mem_rsp_error = inject_error;
    assign mem_rsp_data = memory_data(word_address);
    always @(posedge clk) begin
        cycle <= cycle + 1;
        if (!rst_n) begin
            remaining <= 0;
            latency <= 0;
        end else if (mem_req_valid && mem_req_ready) begin
            mem_reads <= mem_reads + 1;
            remaining <= int'(mem_req_length) + int'(inject_extra_beat);
            latency <= 3;
            word_address <= mem_req_address;
        end else if (latency != 0) begin
            latency <= latency - 1;
        end else if (mem_rsp_valid && mem_rsp_ready) begin
            remaining <= remaining - 1;
            word_address <= word_address + 64'd8;
        end
    end

    task automatic start_frame;
        @(negedge clk);
        frame_start = 1;
        epoch++;
        @(negedge clk);
        frame_start = 0;
    endtask

    task automatic read_sign(input logic [63:0] address, input int beats, input bit stall = 0);
        @(negedge clk);
        client_req_valid = 1;
        client_req_address = address;
        client_req_length = 5'(beats);
        client_rsp_ready = !stall;
        do @(posedge clk); while (!client_req_ready);
        @(negedge clk);
        client_req_valid = 0;
        // After acceptance the request may change while its result stalls.
        client_req_address = ~address;
        client_req_length = 0;
        logical_reads++;
        if (stall) begin
            do @(posedge clk); while (!client_rsp_valid);
            repeat (4) begin
                @(posedge clk);
                if ({client_rsp_valid, client_rsp_last, client_rsp_error, client_rsp_data} !==
                    {1'b1, 1'b1, 1'b0, memory_data(address)})
                    $fatal(1, "SIGN_CACHE_CHANGED_WHILE_STALLED");
            end
            @(negedge clk);
            client_rsp_ready = 1;
        end
        for (int beat = 0; beat < beats + int'(inject_extra_beat); beat++) begin
            do @(posedge clk); while (!client_rsp_valid);
            if ({client_rsp_last, client_rsp_error, client_rsp_data} !==
                {beat == beats + int'(inject_extra_beat) - 1, inject_error, memory_data(address + 64'(8*beat))})
                $fatal(1, "SIGN_CACHE_RESPONSE_MISMATCH address=%h beat=%0d", address, beat);
        end
        @(negedge clk);
    endtask

    initial begin : test
        string fixture;
        int started, prior_reads;
        logic [63:0] offset;
        if (!$value$plusargs("PAIRS=%s", fixture)) $fatal(1, "SIGN_CACHE_NEEDS_PAIRS");
        $readmemh(fixture, outlier_pairs);
        repeat (2) @(negedge clk);
        rst_n = 1;
        start_frame();
        started = cycle;
        for (int group_id = 0; group_id < 176; group_id++) begin
            for (int token = 0; token < 16; token++) begin
                for (int pair = 0; pair < 1024; pair++) begin
                    if (outlier_pairs[token][pair]) begin
                        offset = 64'(group_id * 1024 + pair) << 3;
                        read_sign(GATE_BASE + offset, 1);
                        read_sign(UP_BASE + offset, 1);
                    end
                end
            end
        end
        $display("SIGN_CACHE_TRACE logical=%0d external=%0d cycles=%0d", logical_reads, mem_reads, cycle - started);
        if (logical_reads != 55616 || mem_reads != 21824)
            $fatal(1, "SIGN_CACHE_TRACE_NO_REUSE logical=%0d external=%0d", logical_reads, mem_reads);

        start_frame();
        prior_reads = mem_reads;
        read_sign(GATE_BASE, 1);
        read_sign(GATE_BASE, 1, 1);
        if (mem_reads != prior_reads + 1) $fatal(1, "SIGN_CACHE_MISSED_REPEAT");
        start_frame();
        read_sign(GATE_BASE, 1);
        if (mem_reads != prior_reads + 2) $fatal(1, "SIGN_CACHE_REUSED_OLD_FRAME");

        prior_reads = mem_reads;
        inject_error = 1;
        read_sign(GATE_BASE + 64'd8, 1);
        inject_error = 0;
        read_sign(GATE_BASE + 64'd8, 1);
        inject_extra_beat = 1;
        read_sign(GATE_BASE + 64'd16, 1);
        inject_extra_beat = 0;
        read_sign(GATE_BASE + 64'd16, 1);
        read_sign(UP_BASE, 2);
        read_sign(UP_BASE, 1);
        if (mem_reads != prior_reads + 6) $fatal(1, "SIGN_CACHE_REUSED_INVALID_RESPONSE");
        $display("SIGN_CACHE_PASS repeat_frame_stall_error_drain_burst=1");
        $finish;
    end

    initial begin
        #10000000;
        $fatal(1, "SIGN_CACHE_TIMEOUT");
    end
endmodule
