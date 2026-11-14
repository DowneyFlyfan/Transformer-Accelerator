`timescale 1ns/1ps

module tri_oracle_grouped_cluster_batch_tb;
    logic clk = 0, rst_n = 0;
    always #5 clk = ~clk;
    logic start_valid = 0, start_ready;
    logic [4:0] start_mask = 0, cluster_start_valid, cluster_start_ready = 0;
    logic [4:0] cluster_done_valid = 0, cluster_done_error = 0, cluster_done_ready;
    logic [4:0] cluster_result_valid = 0, cluster_result_last = 0, cluster_result_ready;
    logic [4:0][1:0] cluster_result_lane = '0;
    logic [4:0][2047:0] cluster_result_data;
    logic result_valid, result_last, result_ready = 0;
    logic [2:0] result_cluster;
    logic [1:0] result_lane;
    logic [2047:0] result_data;
    logic batch_active, done_valid, done_error, done_ready = 0;
    int results = 0, stalls = 0, batches = 0;

    tri_oracle_grouped_cluster_batch dut (.*);

    task automatic launch(input logic [4:0] mask);
        start_mask = mask;
        start_valid = 1;
        @(posedge clk);
        if (start_ready !== 1 || batch_active !== 0) $fatal(1, "CLUSTER_BATCH_START");
        @(negedge clk);
        start_valid = 0;
        start_mask = '1;
    endtask

    task automatic check_result(input int client, input bit ready);
        result_ready = ready;
        @(posedge clk);
        if ({result_valid, result_cluster, result_lane, result_last, result_data} !==
            {1'b1, 3'(client), cluster_result_lane[client], cluster_result_last[client], cluster_result_data[client]} ||
            cluster_result_ready !== (ready ? 5'b1 << client : 5'b0) || done_valid !== 0)
            $fatal(1, "CLUSTER_BATCH_RESULT client=%0d ready=%0d", client, ready);
        @(negedge clk);
        if (ready) begin
            results++;
            cluster_result_valid[client] = 0;
        end else stalls++;
    endtask

    task automatic check_done(input bit expected_error);
        repeat (3) begin
            @(posedge clk);
            if ({done_valid, done_error, start_ready, batch_active, result_valid} !==
                {1'b1, expected_error, 1'b0, 1'b1, 1'b0} ||
                (cluster_start_valid | cluster_done_ready | cluster_result_ready) !== '0)
                $fatal(1, "CLUSTER_BATCH_COMPLETION");
            @(negedge clk);
        end
        done_ready = 1;
        @(negedge clk);
        done_ready = 0;
        batches++;
    endtask

    initial begin
        for (int client = 0; client < 5; client++) begin
            cluster_result_lane[client] = 2'(client + 1);
            cluster_result_data[client] = {32{64'h7300000000000011 ^ (64'(client) << 48)}};
        end
        repeat (3) @(negedge clk);
        rst_n = 1;
        launch(5'b11111);
        cluster_start_ready = 5'b10101;
        @(posedge clk);
        if (cluster_start_valid !== 5'b11111 || cluster_done_ready !== 0) $fatal(1, "CLUSTER_BATCH_LAUNCH");
        @(negedge clk);
        cluster_start_ready = 0;
        cluster_result_valid = 5'b00100;
        cluster_result_last = 5'b10101;
        check_result(2, 0);
        cluster_result_valid = 5'b10101;
        check_result(2, 0);
        if (cluster_start_valid !== 5'b01010 || cluster_done_ready !== 5'b10101)
            $fatal(1, "CLUSTER_BATCH_PENDING");
        check_result(2, 1);
        cluster_done_valid = 5'b00100;
        check_result(4, 1);
        cluster_done_valid = 5'b10000;
        check_result(0, 1);
        cluster_done_valid = 5'b00001;
        cluster_start_ready = 5'b01010;
        @(negedge clk);
        cluster_done_valid = 0;
        cluster_result_valid = 5'b01010;
        cluster_result_last = 5'b01010;
        check_result(1, 1);
        cluster_done_valid = 5'b00010;
        check_result(3, 1);
        cluster_done_valid = 5'b01000;
        cluster_done_error = 5'b01000;
        @(negedge clk);
        cluster_done_valid = 0;
        cluster_done_error = 0;
        check_done(1);
        launch(0);
        check_done(1);
        launch(5'b10000);
        cluster_start_ready = '1;
        @(negedge clk);
        cluster_done_valid = 5'b10000;
        @(negedge clk);
        cluster_done_valid = 0;
        check_done(0);
        if (results != 5 || stalls != 2 || batches != 3) $fatal(1, "CLUSTER_BATCH_INVENTORY");
        $display("CLUSTER_BATCH_PASS clusters=5 results=%0d stalls=%0d batches=%0d", results, stalls, batches);
        $finish;
    end

    initial begin
        #10000;
        $fatal(1, "CLUSTER_BATCH_TIMEOUT");
    end
endmodule
