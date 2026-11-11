`timescale 1ns/1ps
module tri_oracle_cluster_local_projection_tb;
    logic clk = 0, rst_n = 0, in_valid = 0, in_ready;
    logic [4:0] in_clusters = 5'b10000;
    logic in_accumulate = 0, in_publish = 0;
    logic out_valid, done_valid, done_ready = 0, done_error;
    logic [31:0] done_tag;
    logic backend_rst_n, backend_cmd_valid;
    logic [4:0] backend_out_valid = '0, backend_out_ready;
    logic [19:0] backend_out_output = '0;
    int issued = 0;
    always #5 clk = ~clk;

    tri_oracle_batched_projection356 dut (
        .clk, .rst_n, .in_valid, .in_ready, .in_tag(32'h1234),
        .in_tokens(5'd1), .in_weight_base('0), .in_mask_base('0), .in_strips(6'd1),
        .in_clusters, .in_activation_base('0), .in_activation_stride(11'd1), .in_accumulate, .in_publish,
        .out_valid, .out_ready(1'b1), .out_tag(), .out_token(), .out_last(), .out_data(),
        .done_valid, .done_ready, .done_error, .done_tag, .backend_rst_n, .backend_cmd_valid,
        .backend_cmd_ready(1'b1), .backend_cmd_weight(), .backend_cmd_mask(), .backend_cmd_activation(),
        .backend_cmd_output(), .backend_cmd_accumulate(), .backend_out_valid, .backend_out_ready,
        .backend_out_output, .backend_out_data('0)
    );

    always @(posedge clk) if (backend_cmd_valid) issued++;

    task automatic submit;
        in_valid = 1;
        @(posedge clk);
        if (!in_ready) $fatal(1, "CLUSTER_PROJECTION_CONFIG");
        @(negedge clk);
        in_valid = 0;
    endtask

    task automatic retire(input bit expected_error);
        do @(negedge clk); while (!done_valid);
        if (done_error !== expected_error || done_tag !== 32'h1234)
            $fatal(1, "CLUSTER_PROJECTION_RESULT");
        done_ready = 1;
        @(posedge clk);
        @(negedge clk);
        done_ready = 0;
    endtask

    initial begin
        repeat (2) @(negedge clk);
        rst_n = 1;
        submit();
        wait (issued == 1);
        @(negedge clk);
        // An unselected cluster presents a stale slot and may remain valid.
        backend_out_valid = 5'b10001;
        backend_out_output[3:0] = 4'hf;
        @(posedge clk);
        if (backend_out_ready !== 5'b10000 || out_valid)
            $fatal(1, "CLUSTER_PROJECTION_DRAIN_MASK");
        @(negedge clk);
        backend_out_valid = 5'b00001;
        retire(0);

        // A partial accumulator belongs to the original set of clusters.
        backend_out_valid = '0;
        in_clusters = 5'b00001;
        in_accumulate = 1;
        in_publish = 1;
        submit();
        @(posedge clk);
        if (backend_cmd_valid) $fatal(1, "CLUSTER_PROJECTION_STALE_ISSUE");
        retire(1);
        if (issued != 1) $fatal(1, "CLUSTER_PROJECTION_STALE_ISSUE");

        in_clusters = 0;
        in_accumulate = 0;
        submit();
        retire(1);
        if (issued != 1) $fatal(1, "CLUSTER_PROJECTION_EMPTY_ISSUE");

        // Existing projection clients still wait for all five clusters.
        in_clusters = 5'b11111;
        submit();
        wait (issued == 2);
        @(negedge clk);
        backend_out_output = '0;
        backend_out_valid = 5'b11110;
        @(posedge clk);
        if (backend_out_ready !== '0 || out_valid) $fatal(1, "CLUSTER_PROJECTION_EARLY_COLLECT");
        @(negedge clk);
        backend_out_valid = '1;
        @(posedge clk);
        if (backend_out_ready !== '1 || !out_valid) $fatal(1, "CLUSTER_PROJECTION_ALL_CLUSTER_COLLECT");
        @(negedge clk);
        backend_out_valid = '0;
        retire(0);
        $display("CLUSTER_PROJECTION_PASS isolated_result=1 wrong_context=1 empty_scope=1 all_cluster_result=1");
        $finish;
    end

    initial begin
        #1000;
        $fatal(1, "CLUSTER_PROJECTION_WATCHDOG");
    end
endmodule
