`timescale 1ns/1ps
module tri_oracle_batched404_preoffer_tb;
    localparam logic [31:0] TAG = 32'h4040cafe;
    localparam logic [63:0] GATE_BASE = 64'h0000000100001000;
    localparam logic [63:0] UP_BASE = 64'h0000000100002000;
    logic clk = 0;
    always #5 clk = ~clk;
    logic rst_n = 0, cfg_valid = 0, meta_valid = 0, commit_valid = 0;
    logic out_ready = 0, done_ready = 0, rsp_valid = 0;
    wire cfg_ready, meta_ready, commit_ready, out_valid, out_last, done_valid, done_error;
    wire [31:0] out_tag, done_tag, gate_nearzero_mask, up_nearzero_mask, skip_mask;
    wire [7:0] out_group;
    wire [3:0] out_token;
    wire [12:0] outlier_count;
    wire req_valid, rsp_ready;
    wire [63:0] req_address;
    wire [4:0] req_length;
    logic [7:0] meta_outliers = 0, meta_negative = 0;
    int lane_index = 0, requests = 0;

    tri_oracle_batched_outlier_replay404 dut (
        .clk(clk), .rst_n(rst_n), .cfg_valid(cfg_valid), .cfg_ready(cfg_ready),
        .cfg_tag(TAG), .cfg_tokens(5'd1), .cfg_strips(10'd1), .cfg_groups(8'd1),
        .cfg_gate_sign_base(GATE_BASE), .cfg_up_sign_base(UP_BASE),
        .meta_valid(meta_valid), .meta_last(1'b1), .meta_ready(meta_ready), .meta_tag(TAG),
        .meta_token(4'd0), .meta_index(10'd0), .meta_outliers(meta_outliers), .meta_negative(meta_negative),
        .commit_valid(commit_valid), .abort_fill(1'b0), .commit_ready(commit_ready),
        .out_valid(out_valid), .out_ready(out_ready), .out_last(out_last), .out_tag(out_tag),
        .out_group(out_group), .out_token(out_token), .gate_nearzero_mask(gate_nearzero_mask),
        .up_nearzero_mask(up_nearzero_mask), .skip_mask(skip_mask), .outlier_count(outlier_count),
        .done_valid(done_valid), .done_ready(done_ready), .done_error(done_error), .done_tag(done_tag),
        .req_valid(req_valid), .req_ready(!rsp_valid), .req_address(req_address), .req_length(req_length),
        .rsp_valid(rsp_valid), .rsp_ready(rsp_ready), .rsp_last(rsp_valid), .rsp_error(1'b0), .rsp_data(64'hffffffffffffffff)
    );

    always @(posedge clk) if (rst_n) begin
        if (rsp_valid && rsp_ready) rsp_valid <= 0;
        if (req_valid && !rsp_valid) begin
            if (requests >= 2 || req_length !== 5'd1 ||
                req_address !== (requests == 0 ? GATE_BASE : UP_BASE) + 64'(lane_index / 2) * 8)
                $fatal(1, "BATCH404_STALE_OR_MISPLACED_METADATA lane=%0d address=%h", lane_index, req_address);
            requests++;
            rsp_valid <= 1;
        end
    end

    task automatic frame(input int lane, input bit negative, preoffered);
        @(negedge clk);
        requests = 0;
        lane_index = lane;
        meta_outliers = 8'b1 << lane;
        meta_negative = negative ? meta_outliers : 8'd0;
        meta_valid = preoffered;
        cfg_valid = 1;
        @(posedge clk);
        if (!cfg_ready || meta_ready) $fatal(1, "BATCH404_CONFIG_ORDER");
        @(negedge clk);
        cfg_valid = 0;
        if (!preoffered) meta_valid = 1;
        @(posedge clk);
        if (!meta_ready) $fatal(1, "BATCH404_METADATA_NOT_ACCEPTED");
        @(negedge clk);
        meta_valid = 0;
        repeat (4) begin
            if (!commit_ready || req_valid || out_valid) $fatal(1, "BATCH404_READ_BEFORE_COMMIT");
            @(negedge clk);
        end
        commit_valid = 1;
        @(negedge clk);
        commit_valid = 0;
        while (out_valid !== 1'b1) @(negedge clk);
        if (requests != 2 || out_tag !== TAG || out_group !== 0 || out_token !== 0 ||
            out_last !== 1'b1 || outlier_count !== 13'd1 ||
            gate_nearzero_mask !== (negative ? 32'd0 : 32'hffffffff) ||
            up_nearzero_mask !== 32'd0 || skip_mask !== 32'd0)
            $fatal(1, "BATCH404_STALE_OR_MISPLACED_METADATA lane=%0d", lane_index);
        out_ready = 1;
        @(negedge clk);
        out_ready = 0;
        if (!done_valid || done_error || done_tag !== TAG)
            $fatal(1, "BATCH404_DONE");
        done_ready = 1;
        @(negedge clk);
        done_ready = 0;
    endtask

    initial begin
        repeat (3) @(negedge clk);
        rst_n = 1;
        frame(3, 0, 0);
        frame(6, 1, 1);
        $display("BATCH404_PREOFFER_PASS same_address=1 strips=1");
        $finish;
    end
    initial begin #100000; $fatal(1, "BATCH404_WATCHDOG"); end
endmodule
