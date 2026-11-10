`timescale 1ns/1ps
// Compare the reused predictor against all original residual and sign words.
// Modes 1 and 4 stretch early and late sign failures. Mode 2 changes replay
// energy. Mode 3 cancels both held residual offers after an invalid descriptor.
module tri_oracle_batched398_outliers_tb;
    localparam int TOKENS = 16;
    localparam int STRIPS = 256;
    localparam int GROUPS = 176;
    localparam int PAIRS = STRIPS * 4;
    localparam logic [63:0] GATE_BASE = 64'h00000001ffffe000;
    localparam logic [63:0] UP_BASE = 64'h00000003ffffe000;

    logic clk = 0;
    always #5 clk = ~clk;
    logic rst_n = 0, cfg_valid = 0, done_ready = 0;
    wire cfg_ready, done_valid, done_error;
    logic [31:0] cfg_tag = 0;
    logic [4:0] cfg_tokens = 0;
    logic [9:0] cfg_strips = 0;
    logic [7:0] cfg_groups = 0;
    logic [31:0] cfg_epsilon_q16 = 0;
    logic [63:0] cfg_gate_sign_base = 0, cfg_up_sign_base = 0;
    logic stats_valid = 0, stats_last = 0, replay_valid = 0, replay_last = 0;
    logic [127:0] stats_data = 0, replay_data = 0;
    wire stats_ready, replay_ready;
    wire [3:0] residual_token;
    logic out_ready = 0;
    wire out_valid, out_last;
    wire [31:0] out_tag, done_tag, gate_nearzero_mask, up_nearzero_mask, skip_mask;
    wire [7:0] out_group;
    wire [3:0] out_token;
    wire [12:0] outlier_count;
    wire req_valid, rsp_ready;
    wire [63:0] req_address;
    wire [4:0] req_length;
    logic rsp_valid = 0, rsp_last = 0, rsp_error = 0;
    logic [63:0] rsp_data = 0;
    int cycle = 0;
    wire req_ready = !rsp_valid && cycle % 5 >= 2;
    logic [127:0] residual_words [TOKENS * STRIPS];
    logic [63:0] gate_words [GROUPS * PAIRS], up_words [GROUPS * PAIRS];
    logic [95:0] branch_masks [TOKENS * GROUPS];
    logic [PAIRS-1:0] outlier_pairs [TOKENS];
    logic [15:0] outlier_counts [TOKENS];
    int fault, group_limit, active_group, active_token, pair_cursor, replay_frames;
    int sign_reads, checked_groups, skipped_channels, drains, failure_read_start;
    int normalizer_starts, lower_writes, upper_writes, lower_reads, upper_reads;
    bit next_up, inject_fault, group_failed, held_request, short_frame;
    logic [68:0] prior_request;
    string fixture;

    tri_oracle_batched_outliers398 dut (.*);

    always @(posedge clk) if (rst_n) begin : sign_memory
        int index;
        logic [63:0] wanted;
        bit fail_this_request;
        cycle <= cycle + 1;
        if (dut.normalizer.cfg_valid && dut.normalizer.cfg_ready) normalizer_starts++;
        if (!dut.lower_metadata.CEB) begin
            if (dut.lower_metadata.WEB) begin
                if (short_frame && dut.lower_metadata.A !== 9'((lower_reads % 16 / 2) * 64 + lower_reads % 2))
                    $fatal(1, "BATCH398_SHORT_LOWER_READ_ADDRESS");
                lower_reads++;
            end else begin
                if (short_frame && (dut.lower_metadata.A !== 9'(lower_writes / 2 * 64 + lower_writes % 2) ||
                    dut.lower_metadata.D !== 64'd0))
                    $fatal(1, "BATCH398_SHORT_LOWER_WRITE");
                lower_writes++;
            end
        end
        if (!dut.upper_metadata.CEB) begin
            if (dut.upper_metadata.WEB) begin
                if (short_frame && dut.upper_metadata.A !== 9'(upper_reads % 2))
                    $fatal(1, "BATCH398_SHORT_UPPER_READ_ADDRESS");
                upper_reads++;
            end else begin
                if (short_frame && (dut.upper_metadata.A !== 9'(upper_writes) || dut.upper_metadata.D !== 64'd0))
                    $fatal(1, "BATCH398_SHORT_UPPER_WRITE");
                upper_writes++;
            end
        end
        if (held_request && (!req_valid || {req_address, req_length} !== prior_request))
            $fatal(1, "BATCH398_REQUEST_CHANGED");
        held_request = req_valid && !req_ready;
        prior_request = {req_address, req_length};
        if (rsp_valid && rsp_ready) begin
            if (rsp_last) begin
                rsp_valid <= 0;
                if (group_failed) drains++;
            end else begin
                rsp_last <= 1;
                rsp_error <= 0;
                rsp_data <= '1;
            end
        end
        if (req_valid && req_ready) begin
            if (replay_frames != TOKENS || group_failed || active_group >= group_limit)
                $fatal(1, "BATCH398_UNEXPECTED_SIGN_REQUEST");
            while (pair_cursor < PAIRS && !outlier_pairs[active_token][pair_cursor]) pair_cursor++;
            if (pair_cursor == PAIRS) $fatal(1, "BATCH398_EXTRA_SIGN_REQUEST");
            index = active_group * PAIRS + pair_cursor;
            wanted = (next_up ? UP_BASE : GATE_BASE) + 64'(index) * 8;
            if (req_address !== wanted || req_length !== 5'd1)
                $fatal(1, "BATCH398_SIGN_ADDRESS token=%0d group=%0d got=%h expected=%h",
                    active_token, active_group, req_address, wanted);
            rsp_data <= next_up ? up_words[index] : gate_words[index];
            rsp_valid <= 1;
            fail_this_request = inject_fault && (fault == 1 ||
                (fault == 4 && active_group == 1 && active_token == 3));
            rsp_error <= fail_this_request;
            rsp_last <= !fail_this_request;
            if (fail_this_request) begin
                group_failed = 1;
                failure_read_start = sign_reads;
            end
            if (next_up) pair_cursor++;
            next_up = !next_up;
            sign_reads++;
        end
        if (replay_frames == TOKENS && (stats_ready || replay_ready))
            $fatal(1, "BATCH398_EXTRA_NORMALIZATION");
        if (inject_fault && (fault != 4 || group_failed) && out_valid)
            $fatal(1, "BATCH398_FAULT_PUBLISHED_MASK");
    end

    task automatic configure(input bit short_zero = 0);
        @(negedge clk);
        active_group = 0; active_token = 0; pair_cursor = 0; replay_frames = 0;
        short_frame = short_zero;
        sign_reads = 0; checked_groups = 0; skipped_channels = 0; drains = 0;
        normalizer_starts = 0; lower_writes = 0; upper_writes = 0; lower_reads = 0; upper_reads = 0;
        next_up = 0; group_failed = 0; failure_read_start = -1;
        cfg_valid = 1;
        cfg_tag = 32'h3980cafe;
        cfg_tokens = short_zero ? 5'd9 : 5'(TOKENS);
        cfg_strips = short_zero ? 10'd5 : 10'(STRIPS);
        cfg_groups = inject_fault && fault == 3 ? 8'd0 : 8'(group_limit);
        cfg_epsilon_q16 = 32'd43980465;
        cfg_gate_sign_base = GATE_BASE;
        cfg_up_sign_base = UP_BASE;
        @(posedge clk);
        if (cfg_ready !== 1'b1) $fatal(1, "BATCH398_CONFIG_NOT_READY");
        @(negedge clk);
        cfg_valid = 0; cfg_tag = '1; cfg_tokens = '1; cfg_strips = '1; cfg_groups = '1;
        cfg_epsilon_q16 = '1; cfg_gate_sign_base = '1; cfg_up_sign_base = '1;
    endtask

    task automatic normalize_token(input int token, input bit short_zero = 0);
        int strip_count;
        strip_count = short_zero ? 5 : STRIPS;
        for (int strip = 0; strip < strip_count; strip++) begin
            stats_valid = 1;
            stats_last = strip == strip_count - 1;
            stats_data = short_zero ? {8{16'd8192}} : residual_words[token * STRIPS + strip];
            do @(posedge clk); while (stats_ready !== 1'b1);
            if (residual_token !== 4'(token)) $fatal(1, "BATCH398_STATS_TOKEN");
            @(negedge clk);
        end
        stats_valid = 0; stats_data = '1;
        for (int strip = 0; strip < strip_count; strip++) begin
            replay_valid = 1;
            replay_last = strip == strip_count - 1;
            replay_data = short_zero ? {8{16'd8192}} : residual_words[token * STRIPS + strip];
            if (inject_fault && fault == 2 && replay_last) replay_data[15:0] = 16'sd32000;
            do @(posedge clk); while (replay_ready !== 1'b1);
            if (residual_token !== 4'(token)) $fatal(1, "BATCH398_REPLAY_TOKEN");
            @(negedge clk);
        end
        replay_valid = 0; replay_data = '1;
        replay_frames++;
    endtask

    task automatic receive_group(input int group_index, token);
        logic [95:0] wanted;
        wanted = branch_masks[token * GROUPS + group_index];
        while (!out_valid && !done_valid) @(negedge clk);
        repeat (3) begin
            if (out_valid !== 1'b1 || done_valid || out_tag !== 32'h3980cafe ||
                out_group !== 8'(group_index) || out_token !== 4'(token) ||
                out_last !== (group_index == group_limit - 1 && token == TOKENS - 1) ||
                outlier_count !== 13'(outlier_counts[token]) ||
                {gate_nearzero_mask, up_nearzero_mask, skip_mask} !== wanted)
                $fatal(1, "BATCH398_MASK token=%0d group=%0d got=%h expected=%h",
                    token, group_index, {gate_nearzero_mask, up_nearzero_mask, skip_mask}, wanted);
            @(negedge clk);
        end
        if (next_up || rsp_valid) $fatal(1, "BATCH398_SIGN_NOT_DRAINED");
        while (pair_cursor < PAIRS && !outlier_pairs[token][pair_cursor]) pair_cursor++;
        if (pair_cursor != PAIRS) $fatal(1, "BATCH398_MISSING_SIGN_READ");
        checked_groups++;
        skipped_channels += $countones(skip_mask);
        out_ready = 1;
        @(negedge clk);
        out_ready = 0;
        pair_cursor = 0;
        if (token == TOKENS - 1) begin active_token = 0; active_group++; end
        else active_token++;
    endtask

    task automatic finish_frame(input bit expect_error, input bit cancel_residual = 0);
        while (!done_valid) @(negedge clk);
        repeat (3) begin
            if (done_valid !== 1'b1 || done_error !== expect_error || done_tag !== 32'h3980cafe ||
                cfg_ready || req_valid || rsp_valid || out_valid)
                $fatal(1, "BATCH398_DONE");
            if (cancel_residual && ({stats_valid, stats_last, stats_data, replay_valid, replay_last, replay_data}
                !== {2'b11, 128'h1122, 2'b11, 128'h3344} || stats_ready || replay_ready))
                $fatal(1, "BATCH398_HELD_RESIDUAL_CHANGED");
            @(negedge clk);
        end
        if (cancel_residual) begin
            stats_valid = 0;
            replay_valid = 0;
            @(negedge clk);
            if (!done_valid || !done_error) $fatal(1, "BATCH398_CANCELLATION_LOST_DONE");
            $display("BATCH398_RESIDUAL_OFFERS_CANCELLED streams=2");
        end
        done_ready = 1;
        @(negedge clk);
        done_ready = 0;
        if (!cfg_ready) $fatal(1, "BATCH398_OWNER_NOT_RELEASED");
    endtask

    initial begin : stimulus
        int expected_reads;
        if (!$value$plusargs("FIXTURE=%s", fixture)) $fatal(1, "BATCH398_FIXTURE_REQUIRED");
        if (!$value$plusargs("FAULT=%d", fault)) fault = 0;
        if (!$value$plusargs("GROUP_LIMIT=%d", group_limit)) group_limit = GROUPS;
        if (fault < 0 || fault > 4 || group_limit < 1 || group_limit > GROUPS ||
            (fault == 4 && group_limit < 2))
            $fatal(1, "BATCH398_BAD_ARGUMENT");
        $readmemh({fixture, "/raw.hex"}, residual_words);
        $readmemh({fixture, "/gate_sign.hex"}, gate_words);
        $readmemh({fixture, "/up_sign.hex"}, up_words);
        $readmemh({fixture, "/branch_masks.hex"}, branch_masks);
        $readmemh({fixture, "/outlier_pairs.hex"}, outlier_pairs);
        $readmemh({fixture, "/outlier_counts.hex"}, outlier_counts);
        repeat (3) @(negedge clk);
        rst_n = 1;
        if (fault != 0) begin
            inject_fault = 1;
            if (fault == 3) begin
                stats_valid = 1; stats_last = 1; stats_data = 128'h1122;
                replay_valid = 1; replay_last = 1; replay_data = 128'h3344;
            end
            configure();
            if (fault != 3)
                for (int token = 0; token < (fault == 2 ? 1 : TOKENS); token++) normalize_token(token);
            if (fault == 4)
                for (int index = 0; index < TOKENS + 3; index++) receive_group(index / TOKENS, index % TOKENS);
            finish_frame(1, fault == 3);
            if (checked_groups != (fault == 4 ? 19 : 0) ||
                sign_reads != failure_read_start + 1 || drains != int'(fault == 1 || fault == 4))
                $fatal(1, "BATCH398_FAULT_INVENTORY");
            $display("BATCH398_FAULT_RECOVERED fault=%0d drained=%0d provisional_groups=%0d",
                fault, drains, checked_groups);
            inject_fault = 0;
        end
        configure();
        for (int token = 0; token < TOKENS; token++) normalize_token(token);
        for (int group_index = 0; group_index < group_limit; group_index++)
            for (int token = 0; token < TOKENS; token++) receive_group(group_index, token);
        finish_frame(0);
        expected_reads = 0;
        for (int token = 0; token < TOKENS; token++) expected_reads += 2 * group_limit * $countones(outlier_pairs[token]);
        if (sign_reads != expected_reads || checked_groups != TOKENS * group_limit ||
            normalizer_starts != TOKENS || lower_writes != 8 * STRIPS / 4 ||
            upper_writes != 8 * STRIPS / 4 || lower_reads != 8 * STRIPS / 4 * group_limit ||
            upper_reads != 8 * STRIPS / 4 * group_limit)
            $fatal(1, "BATCH398_FINAL_INVENTORY");
        $display("BATCH398_PASS tokens=16 groups=%0d normalizations=%0d mask_bits=%0d skipped=%0d sign_reads=%0d fault=%0d",
            group_limit, normalizer_starts, 32 * checked_groups, skipped_channels, sign_reads, fault);
        $display("BATCH398_MACROS lower_writes=%0d upper_writes=%0d lower_reads=%0d upper_reads=%0d",
            lower_writes, upper_writes, lower_reads, upper_reads);
        if (fault == 3) begin
            configure(1);
            for (int token = 0; token < 9; token++) normalize_token(token, 1);
            for (int group_index = 0; group_index < group_limit; group_index++)
                for (int token = 0; token < 9; token++) begin
                    while (!out_valid && !done_valid) @(negedge clk);
                    if (out_valid !== 1'b1 || out_tag !== 32'h3980cafe ||
                        out_group !== 8'(group_index) || out_token !== 4'(token) ||
                        out_last !== (group_index == group_limit - 1 && token == 8) ||
                        {gate_nearzero_mask, up_nearzero_mask, skip_mask, outlier_count} !== '0)
                        $fatal(1, "BATCH398_SHORT_ZERO_MASK");
                    out_ready = 1;
                    @(negedge clk);
                    out_ready = 0;
                end
            finish_frame(0);
            if (normalizer_starts != 9 || sign_reads != 0 || lower_writes != 16 || upper_writes != 2 ||
                lower_reads != 16 * group_limit || upper_reads != 2 * group_limit)
                $fatal(1, "BATCH398_SHORT_ZERO_INVENTORY");
            $display("BATCH398_SHORT_ZERO_PASS tokens=9 strips=5 sign_reads=0");
        end
        $finish;
    end

    initial begin #40000000; $fatal(1, "BATCH398_WATCHDOG"); end
endmodule
