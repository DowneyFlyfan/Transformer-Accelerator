`timescale 1ns/1ps

module tri_oracle_sign_cache_trained_masks_tb;
    localparam int TOKENS = 16, STRIPS = 256, GROUPS = 176, PAIRS = STRIPS * 4;
    localparam int EXPECTED_READS = 21824;
    localparam logic [63:0] GATE_BASE = 64'h0000000bffffff00, UP_BASE = 64'h0000000dffffff00;
    localparam logic [31:0] TAG = 32'h404c0001;
    logic clk = 0, rst_n = 0;
    always #5 clk = ~clk;

    logic cfg_valid = 0, cfg_ready;
    logic meta_valid = 0, meta_last = 0, meta_ready;
    logic [3:0] meta_token = 0;
    logic [9:0] meta_index = 0;
    logic [7:0] meta_outliers = 0, meta_negative = 0;
    logic commit_valid = 0, commit_ready;
    logic out_valid, out_ready, out_last;
    logic [31:0] out_tag, done_tag;
    logic [7:0] out_group;
    logic [3:0] out_token;
    logic [31:0] gate_nearzero_mask, up_nearzero_mask, skip_mask;
    logic [12:0] outlier_count;
    logic done_valid, done_error;
    logic req_valid, req_ready;
    logic [63:0] req_address;
    logic [4:0] req_length;
    logic rsp_valid, rsp_ready;
    logic [63:0] rsp_data;
    logic [533:0] strip_request;
    logic [111:0] strip_response;
    logic [111:0] cluster_response [0:4];

    logic [15:0] norm_words [0:TOKENS*STRIPS*8-1];
    logic [15:0] counts [0:TOKENS-1];
    logic [95:0] expected_masks [0:TOKENS*GROUPS-1];
    logic [63:0] gate_signs [0:GROUPS*PAIRS-1], up_signs [0:GROUPS*PAIRS-1];
    logic [63:0] expected_addresses [0:EXPECTED_READS-1];
    int cycle = 0, reads = 0, logical_reads = 0, checks = 0, skipped = 0;
    logic pending = 0;

    tri_oracle_batched_outlier_replay404 #(.CORE_STRIP_PREDICTOR(1)) dut (
        .clk, .rst_n, .cfg_valid, .cfg_ready, .cfg_tag(TAG), .cfg_tokens(5'(TOKENS)),
        .cfg_strips(10'(STRIPS)), .cfg_groups(8'(GROUPS)), .cfg_gate_sign_base(GATE_BASE),
        .cfg_up_sign_base(UP_BASE), .meta_valid, .meta_last, .meta_ready, .meta_tag(TAG),
        .meta_token, .meta_index, .meta_outliers, .meta_negative, .commit_valid, .abort_fill(1'b0),
        .commit_ready, .out_valid, .out_ready, .out_last, .out_tag, .out_group, .out_token,
        .gate_nearzero_mask, .up_nearzero_mask, .skip_mask, .outlier_count, .done_valid,
        .done_ready(1'b0), .done_error, .done_tag, .req_valid, .req_ready, .req_address, .req_length,
        .rsp_valid, .rsp_ready, .rsp_last(1'b1), .rsp_error(1'b0), .rsp_data, .strip_request, .strip_response
    );
    assign strip_response = cluster_response[strip_request[533:531]];
    for (genvar cluster = 0; cluster < 5; cluster++) begin : prediction_clusters
        wire [587:0] requests;
        wire [159:0] responses;
        tri_oracle_cluster_strip448 distributor (
            .request(strip_request[533:531] == 3'(cluster) ? strip_request[530:0] : '0),
            .response(cluster_response[cluster]), .core_requests(requests), .core_responses(responses)
        );
        for (genvar core = 0; core < 4; core++) begin : prediction_cores
            tri_oracle_core_strip448 core_predictor (
                .clk, .rst_n, .request(requests[147*core+:147]), .response(responses[40*core+:40])
            );
        end
    end

    assign req_ready = !pending && cycle % 7 != 0;
    assign rsp_valid = pending;
    assign out_ready = cycle % 13 != 0;
    always @(posedge clk) begin : monitor
        int index;
        cycle <= cycle + 1;
        if (rst_n) begin
            if (req_valid && req_ready) begin
                if (reads >= EXPECTED_READS || req_length != 1 || req_address !== expected_addresses[reads])
                    $fatal(1, "TRAINED_SIGN_CACHE_ADDRESS index=%0d address=%h", reads, req_address);
                if (req_address >= UP_BASE) begin
                    index = int'((req_address - UP_BASE) >> 3);
                    rsp_data <= up_signs[index];
                end else begin
                    index = int'((req_address - GATE_BASE) >> 3);
                    rsp_data <= gate_signs[index];
                end
                pending <= 1;
                reads++;
            end else if (rsp_valid && rsp_ready) begin
                pending <= 0;
            end
            if (dut.cache_req_valid && dut.cache_req_ready) logical_reads++;
            if (out_valid && out_ready) begin
                if (checks >= TOKENS*GROUPS || out_group != 8'(checks / TOKENS) || out_token != 4'(checks % TOKENS) ||
                    out_last != (checks == TOKENS*GROUPS-1) || out_tag !== TAG ||
                    outlier_count !== counts[out_token][12:0] ||
                    {gate_nearzero_mask, up_nearzero_mask, skip_mask} !== expected_masks[int'(out_token)*GROUPS+int'(out_group)])
                    $fatal(1, "TRAINED_SIGN_CACHE_MASK check=%0d group=%0d token=%0d", checks, out_group, out_token);
                skipped += $countones(skip_mask);
                checks++;
            end
        end
    end

    initial begin : stimulus
        string fixture, norm, addresses;
        logic signed [15:0] value;
        if (!$value$plusargs("FIXTURE=%s", fixture) || !$value$plusargs("NORM=%s", norm) ||
            !$value$plusargs("ADDRESSES=%s", addresses)) $fatal(1, "TRAINED_SIGN_CACHE_FIXTURES");
        $readmemh(norm, norm_words);
        $readmemh(addresses, expected_addresses);
        $readmemh({fixture, "/branch_masks.hex"}, expected_masks);
        $readmemh({fixture, "/outlier_counts.hex"}, counts);
        $readmemh({fixture, "/gate_sign.hex"}, gate_signs);
        $readmemh({fixture, "/up_sign.hex"}, up_signs);
        repeat (2) @(negedge clk);
        rst_n = 1;
        cfg_valid = 1;
        do @(posedge clk); while (!cfg_ready);
        @(negedge clk);
        cfg_valid = 0;
        for (int token = 0; token < TOKENS; token++) begin
            for (int strip = 0; strip < STRIPS; strip++) begin
                meta_valid = 1;
                meta_last = strip == STRIPS - 1;
                meta_token = 4'(token);
                meta_index = 10'(strip);
                for (int lane = 0; lane < 8; lane++) begin
                    value = $signed(norm_words[(token*STRIPS + strip)*8 + lane]);
                    meta_outliers[lane] = value > 16'sd768 || value < -16'sd768;
                    meta_negative[lane] = value < 0;
                end
                do @(posedge clk); while (!meta_ready);
                @(negedge clk);
            end
        end
        meta_valid = 0;
        commit_valid = 1;
        do @(posedge clk); while (!commit_ready);
        @(negedge clk);
        commit_valid = 0;
        wait (done_valid);
        @(negedge clk);
        if (done_error !== 0 || done_tag !== TAG || pending || reads != EXPECTED_READS || logical_reads != 55616 ||
            checks != GROUPS * TOKENS || skipped != 5231) $fatal(1, "TRAINED_SIGN_CACHE_INVENTORY");
        $display("TRAINED_SIGN_CACHE_PASS groups=%0d bits_per_mask=32 skipped=%0d logical=%0d external=%0d cycles=%0d",
                 checks, skipped, logical_reads, reads, cycle);
        $finish;
    end

    initial begin
        #30000000;
        $fatal(1, "TRAINED_SIGN_CACHE_TIMEOUT");
    end
endmodule
