`timescale 1ns/1ps
// Trained residuals and packed weight signs enter the existing predictor.
// The test alone owns expected branch masks and the exact sign-read schedule.
module tri_oracle_batched396_masks_tb;
    localparam int TOKENS = 16;
    localparam int STRIPS = 256;
    localparam int GROUPS = 176;
    localparam int PAIRS = STRIPS * 4;
    localparam logic [63:0] GATE_BASE = 64'h00000001ffffe000;
    localparam logic [63:0] UP_BASE = 64'h00000003ffffe000;
    localparam logic [31:0] EPSILON_Q16 = 32'd43980465;

    logic clk = 0;
    always #5 clk = ~clk;
    logic rst_n = 0, cfg_valid = 0;
    wire cfg_ready;
    logic [31:0] cfg_tag = 0;
    logic [10:0] cfg_group = 0;
    logic stats_valid = 0, stats_last = 0, replay_valid = 0, replay_last = 0;
    logic [127:0] stats_data = 0, replay_data = 0;
    wire stats_ready, replay_ready;
    logic out_ready = 0;
    wire out_valid, out_error;
    wire [31:0] out_tag, gate_nearzero_mask, up_nearzero_mask, skip_mask;
    wire [12:0] outlier_count;
    wire req_valid, rsp_ready;
    wire [63:0] req_address;
    wire [4:0] req_length;
    logic rsp_valid = 0;
    logic [63:0] rsp_data = 0;
    int cycle = 0;
    wire req_ready = !rsp_valid && cycle % 5 >= 2;

    logic [127:0] residual_words [TOKENS * STRIPS];
    logic [63:0] gate_words [GROUPS * PAIRS], up_words [GROUPS * PAIRS];
    logic [95:0] branch_masks [TOKENS * GROUPS];
    logic [PAIRS-1:0] outlier_pairs [TOKENS];
    logic [15:0] outlier_counts [TOKENS];
    int token_id, group_limit, active_group, pair_cursor;
    int read_requests = 0, checked_groups = 0, skipped_channels = 0;
    bit next_up = 0, group_active = 0;
    bit held_request = 0;
    logic [68:0] prior_request;
    string fixture;

    tri_oracle_rms_sign_predictor dut (
        .clk(clk), .rst_n(rst_n), .cfg_valid(cfg_valid), .cfg_ready(cfg_ready),
        .cfg_tag(cfg_tag), .cfg_group(cfg_group), .cfg_strips(10'(STRIPS)),
        .cfg_epsilon_q16(EPSILON_Q16), .cfg_gate_sign_base(GATE_BASE), .cfg_up_sign_base(UP_BASE),
        .stats_valid(stats_valid), .stats_ready(stats_ready), .stats_last(stats_last), .stats_data(stats_data),
        .replay_valid(replay_valid), .replay_ready(replay_ready), .replay_last(replay_last), .replay_data(replay_data),
        .out_valid(out_valid), .out_ready(out_ready), .out_error(out_error), .out_tag(out_tag),
        .gate_nearzero_mask(gate_nearzero_mask), .up_nearzero_mask(up_nearzero_mask),
        .skip_mask(skip_mask), .outlier_count(outlier_count), .req_valid(req_valid), .req_ready(req_ready),
        .req_address(req_address), .req_length(req_length), .rsp_valid(rsp_valid),
        .rsp_ready(rsp_ready), .rsp_last(rsp_valid), .rsp_error(1'b0), .rsp_data(rsp_data)
    );

    always @(posedge clk) if (rst_n) begin : sign_memory
        int index;
        logic [63:0] wanted;
        cycle <= cycle + 1;
        if (held_request && (!req_valid || {req_address, req_length} !== prior_request))
            $fatal(1, "BATCH396_REQUEST_CHANGED");
        held_request = req_valid && !req_ready;
        prior_request = {req_address, req_length};
        if (rsp_valid && rsp_ready) rsp_valid <= 0;
        if (req_valid && req_ready) begin
            if (!group_active) $fatal(1, "BATCH396_REQUEST_WITHOUT_GROUP");
            while (pair_cursor < PAIRS && !outlier_pairs[token_id][pair_cursor]) pair_cursor++;
            if (pair_cursor == PAIRS) $fatal(1, "BATCH396_EXTRA_SIGN_REQUEST");
            index = active_group * PAIRS + pair_cursor;
            wanted = (next_up ? UP_BASE : GATE_BASE) + 64'(index) * 8;
            if (req_address !== wanted || req_length !== 5'd1)
                $fatal(1, "BATCH396_SIGN_ADDRESS token=%0d group=%0d got=%h expected=%h",
                    token_id, active_group, req_address, wanted);
            rsp_data <= next_up ? up_words[index] : gate_words[index];
            rsp_valid <= 1;
            if (next_up) pair_cursor++;
            next_up = !next_up;
            read_requests++;
        end
    end

    task automatic run_group(input int group_index);
        logic [31:0] tag;
        logic [95:0] wanted;
        int requests_before;
        @(negedge clk);
        tag = 32'h39600000 | (32'(token_id) << 16) | 32'(group_index);
        wanted = branch_masks[token_id * GROUPS + group_index];
        active_group = group_index;
        group_active = 1;
        pair_cursor = 0;
        next_up = 0;
        requests_before = read_requests;
        cfg_valid = 1;
        cfg_tag = tag;
        cfg_group = 11'(group_index);
        @(posedge clk);
        if (cfg_ready !== 1'b1) $fatal(1, "BATCH396_CONFIG_NOT_READY");
        @(negedge clk);
        cfg_valid = 0;
        cfg_tag = '1;
        cfg_group = '1;
        for (int strip = 0; strip < STRIPS; strip++) begin
            stats_valid = 1;
            stats_last = strip == STRIPS - 1;
            stats_data = residual_words[token_id * STRIPS + strip];
            do @(posedge clk); while (stats_ready !== 1'b1);
            @(negedge clk);
        end
        stats_valid = 0;
        stats_data = '1;
        for (int strip = 0; strip < STRIPS; strip++) begin
            replay_valid = 1;
            replay_last = strip == STRIPS - 1;
            replay_data = residual_words[token_id * STRIPS + strip];
            do @(posedge clk); while (replay_ready !== 1'b1);
            @(negedge clk);
            if (strip != STRIPS - 1 && out_valid) $fatal(1, "BATCH396_PREMATURE_RESULT");
        end
        replay_valid = 0;
        replay_data = '1;
        while (out_valid !== 1'b1) @(negedge clk);
        repeat (4) begin
            if (out_error !== 1'b0 || out_tag !== tag || outlier_count !== 13'(outlier_counts[token_id]) ||
                {gate_nearzero_mask, up_nearzero_mask, skip_mask} !== wanted)
                $fatal(1, "BATCH396_MASK token=%0d group=%0d got=%h expected=%h",
                    token_id, group_index, {gate_nearzero_mask, up_nearzero_mask, skip_mask}, wanted);
            @(negedge clk);
        end
        if (next_up || rsp_valid || read_requests - requests_before != 2 * $countones(outlier_pairs[token_id]))
            $fatal(1, "BATCH396_SIGN_READ_INVENTORY");
        skipped_channels += $countones(skip_mask);
        checked_groups++;
        group_active = 0;
        out_ready = 1;
        @(negedge clk);
        out_ready = 0;
    endtask

    initial begin
        if (!$value$plusargs("FIXTURE=%s", fixture) || !$value$plusargs("TOKEN=%d", token_id) ||
            token_id < 0 || token_id >= TOKENS) $fatal(1, "BATCH396_FIXTURE_REQUIRED");
        if (!$value$plusargs("GROUP_LIMIT=%d", group_limit)) group_limit = GROUPS;
        if (group_limit < 1 || group_limit > GROUPS) $fatal(1, "BATCH396_GROUP_LIMIT");
        $readmemh({fixture, "/raw.hex"}, residual_words);
        $readmemh({fixture, "/gate_sign.hex"}, gate_words);
        $readmemh({fixture, "/up_sign.hex"}, up_words);
        $readmemh({fixture, "/branch_masks.hex"}, branch_masks);
        $readmemh({fixture, "/outlier_pairs.hex"}, outlier_pairs);
        $readmemh({fixture, "/outlier_counts.hex"}, outlier_counts);
        repeat (3) @(negedge clk);
        rst_n = 1;
        $display("BATCH396_FIXTURE_LOADED token=%0d groups=%0d", token_id, group_limit);
        for (int group_index = 0; group_index < group_limit; group_index++) run_group(group_index);
        $display("BATCH396_MASKS_PASS token=%0d groups=%0d channels=%0d skipped=%0d sign_reads=%0d",
            token_id, checked_groups, checked_groups * 32, skipped_channels, read_requests);
        $finish;
    end

    initial begin
        #30000000;
        $fatal(1, "BATCH396_WATCHDOG token=%0d checked_groups=%0d", token_id, checked_groups);
    end
endmodule
