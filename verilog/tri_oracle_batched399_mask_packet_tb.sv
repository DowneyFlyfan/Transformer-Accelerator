`timescale 1ns/1ps
module tri_oracle_batched399_mask_packet_tb #(parameter bit NATIVE = 0);
    localparam logic [31:0] TAG = 32'h3990cafe;
    localparam logic [63:0] GATE_BASE = 64'h00000001ffffe000;
    localparam logic [63:0] UP_BASE = 64'h00000003ffffe000;
    localparam int GROUPS = 176;
    localparam int STRIPS = 256;
    localparam int PAIRS = STRIPS * 4;

    logic clk = 0;
    always #5 clk = ~clk;
    logic rst_n = 0, cfg_valid = 0, done_ready = 0;
    wire cfg_ready, done_valid, done_error;
    wire [31:0] done_tag;
    logic [31:0] cfg_tag = 0, cancel_tag = 0;
    logic [4:0] cfg_tokens = 0;
    logic [15:0] cfg_channels = 0;
    logic cancel_valid = 0, mask_ready = 0;
    wire mask_valid, mask_last, in_ready;
    wire [31:0] mask_tag;
    wire [15:0] mask_start;
    wire [6:0] mask_count;
    wire [1279:0] mask_bits;
    wire in_valid, in_last;
    wire [31:0] in_tag, in_skip_mask;
    wire [7:0] in_group;
    wire [3:0] in_token;

    logic literal_valid = 0, literal_last = 0;
    logic [31:0] literal_tag = 0, literal_skip = 0;
    logic [7:0] literal_group = 0;
    logic [3:0] literal_token = 0;
    logic stats_valid = 0, stats_last = 0, replay_valid = 0, replay_last = 0;
    logic [127:0] stats_data = 0, replay_data = 0;
    wire stats_ready, replay_ready;
    wire [3:0] residual_token;
    logic predictor_done_ready = 0;
    wire predictor_ready, predictor_done, predictor_error;
    wire [31:0] predictor_tag;
    wire req_valid, rsp_ready;
    wire [63:0] req_address;
    wire [4:0] req_length;
    logic rsp_valid = 0;
    logic [63:0] rsp_data = 0;
    logic [127:0] residual_words [16 * STRIPS];
    logic [63:0] gate_words [GROUPS * PAIRS], up_words [GROUPS * PAIRS];
    logic [95:0] branch_masks [16 * GROUPS];
    int packets = 0, compared_bits = 0, padding_bits = 0, sign_reads = 0, accepted_groups = 0;
    int cycles = 0;
    wire req_ready = !rsp_valid && cycles % 5 >= 2;
    string fixture;

    tri_oracle_batched_mask_packet399 dut (.*);
    generate if (NATIVE) begin : joined
        wire [31:0] unused_gate, unused_up;
        wire [12:0] unused_count;
        tri_oracle_batched_outliers398 predictor (
            .clk(clk), .rst_n(rst_n), .cfg_valid(cfg_valid), .cfg_ready(predictor_ready),
            .cfg_tag(cfg_tag), .cfg_tokens(cfg_tokens), .cfg_strips(10'(STRIPS)),
            .cfg_groups(cfg_channels[12:5]), .cfg_epsilon_q16(32'd43980465),
            .cfg_gate_sign_base(GATE_BASE), .cfg_up_sign_base(UP_BASE), .residual_token(residual_token),
            .stats_valid(stats_valid), .stats_last(stats_last), .stats_ready(stats_ready), .stats_data(stats_data),
            .replay_valid(replay_valid), .replay_last(replay_last), .replay_ready(replay_ready), .replay_data(replay_data),
            .out_valid(in_valid), .out_ready(in_ready), .out_last(in_last), .out_tag(in_tag),
            .out_group(in_group), .out_token(in_token), .gate_nearzero_mask(unused_gate),
            .up_nearzero_mask(unused_up), .skip_mask(in_skip_mask), .outlier_count(unused_count),
            .done_valid(predictor_done), .done_ready(predictor_done_ready), .done_error(predictor_error),
            .done_tag(predictor_tag), .req_valid(req_valid), .req_ready(req_ready),
            .req_address(req_address), .req_length(req_length), .rsp_valid(rsp_valid),
            .rsp_ready(rsp_ready), .rsp_last(rsp_valid), .rsp_error(1'b0), .rsp_data(rsp_data)
        );
        always @(posedge clk) if (rst_n) begin : sign_memory
            logic [63:0] offset;
            cycles <= cycles + 1;
            if (rsp_valid && rsp_ready) rsp_valid <= 0;
            if (req_valid && req_ready) begin
                if (req_length !== 5'd1 || req_address[2:0] !== 3'd0)
                    $fatal(1, "BATCH399_SIGN_REQUEST_SHAPE");
                if (req_address >= GATE_BASE && req_address < GATE_BASE + 64'(GROUPS * PAIRS * 8)) begin
                    offset = req_address - GATE_BASE;
                    rsp_data <= gate_words[offset[20:3]];
                end else if (req_address >= UP_BASE && req_address < UP_BASE + 64'(GROUPS * PAIRS * 8)) begin
                    offset = req_address - UP_BASE;
                    rsp_data <= up_words[offset[20:3]];
                end else $fatal(1, "BATCH399_SIGN_REQUEST_RANGE");
                rsp_valid <= 1;
                sign_reads++;
            end
        end
    end else begin : literal
        assign in_valid = literal_valid;
        assign in_tag = literal_tag;
        assign in_group = literal_group;
        assign in_token = literal_token;
        assign in_skip_mask = literal_skip;
        assign in_last = literal_last;
    end endgenerate

    always @(posedge clk) if (rst_n && in_valid && in_ready) accepted_groups++;

    function automatic bit expected_skip(input int token, channel);
        if (NATIVE) return branch_masks[token * GROUPS + channel / 32][channel % 32];
        return (token * 31 + channel * 17 + (channel / 19)) % 37 < 13;
    endfunction

    task automatic configure(input int tokens, channels);
        @(negedge clk);
        cfg_tag = TAG; cfg_tokens = 5'(tokens); cfg_channels = 16'(channels); cfg_valid = 1;
        @(posedge clk);
        if (!cfg_ready || (NATIVE && !predictor_ready)) $fatal(1, "BATCH399_CFG_NOT_READY");
        @(negedge clk);
        cfg_valid = 0; cfg_tag = '1; cfg_tokens = '1; cfg_channels = '1;
    endtask

    task automatic drive_literal(input int token, group_index, tokens, groups, fault = 0);
        literal_valid = 1;
        literal_tag = fault == 1 ? TAG ^ 32'h1 : TAG;
        literal_group = 8'(group_index + int'(fault == 2));
        literal_token = 4'(token + int'(fault == 3));
        literal_last = (group_index == groups - 1 && token == tokens - 1) ^ (fault == 4);
        for (int lane = 0; lane < 32; lane++)
            literal_skip[lane] = expected_skip(token, 32 * group_index + lane);
    endtask

    task automatic offer_literal(input int token, group_index, tokens, groups, fault = 0);
        @(negedge clk);
        drive_literal(token, group_index, tokens, groups, fault);
        do @(posedge clk); while (in_ready !== 1'b1);
        @(negedge clk);
        literal_valid = 0; literal_skip = 'x;
    endtask

    task automatic drive_residuals;
        for (int token = 0; token < 16; token++) begin
            for (int strip = 0; strip < STRIPS; strip++) begin
                stats_valid = 1; stats_last = strip == STRIPS - 1;
                stats_data = residual_words[token * STRIPS + strip];
                do @(posedge clk); while (stats_ready !== 1'b1);
                if (residual_token !== 4'(token)) $fatal(1, "BATCH399_STATS_TOKEN");
                @(negedge clk);
            end
            stats_valid = 0; stats_data = '1;
            for (int strip = 0; strip < STRIPS; strip++) begin
                replay_valid = 1; replay_last = strip == STRIPS - 1;
                replay_data = residual_words[token * STRIPS + strip];
                do @(posedge clk); while (replay_ready !== 1'b1);
                if (residual_token !== 4'(token)) $fatal(1, "BATCH399_REPLAY_TOKEN");
                @(negedge clk);
            end
            replay_valid = 0; replay_data = '1;
        end
    endtask

    task automatic receive_packets(input int tokens, channels);
        int count;
        logic [1279:0] expected;
        for (int start = 0; start < channels; start += 80) begin
            count = channels - start > 80 ? 80 : channels - start;
            expected = '0;
            for (int token = 0; token < tokens; token++)
                for (int row = 0; row < count; row++)
                    expected[token * 80 + row] = !expected_skip(token, start + row);
            while (mask_valid !== 1'b1) begin
                if (done_valid || (NATIVE && predictor_done && predictor_error))
                    $fatal(1, "BATCH399_EARLY_DONE");
                @(negedge clk);
            end
            repeat (5) begin
                if (mask_valid !== 1'b1 || in_ready || mask_tag !== TAG || mask_start !== 16'(start) ||
                    mask_count !== 7'(count) || mask_last !== (start + count == channels) ||
                    mask_bits !== expected)
                    $fatal(1, "BATCH399_PACKET_MISMATCH tokens=%0d channels=%0d start=%0d count=%0d",
                        tokens, channels, start, count);
                @(negedge clk);
            end
            mask_ready = 1;
            @(negedge clk);
            mask_ready = 0;
            packets++;
            compared_bits += tokens * count;
            padding_bits += 1280 - tokens * count;
        end
    endtask

    task automatic finish_packetizer(input bit error);
        while (done_valid !== 1'b1) @(negedge clk);
        repeat (4) begin
            if (!done_valid || done_tag !== TAG || done_error !== error || cfg_ready || mask_valid || in_ready)
                $fatal(1, "BATCH399_DONE");
            @(negedge clk);
        end
        done_ready = 1;
        if (NATIVE) begin
            if (!predictor_done || predictor_error || predictor_tag !== TAG || req_valid || rsp_valid)
                $fatal(1, "BATCH399_PREDICTOR_DONE");
            predictor_done_ready = 1;
        end
        @(negedge clk);
        done_ready = 0; predictor_done_ready = 0;
        if (!cfg_ready) $fatal(1, "BATCH399_OWNER_NOT_RELEASED");
    endtask

    task automatic run_frame(input int tokens, channels);
        int prior_groups;
        prior_groups = accepted_groups;
        configure(tokens, channels);
        fork
            begin
                if (NATIVE) drive_residuals();
                else for (int group_index = 0; group_index < channels / 32; group_index++)
                    for (int token = 0; token < tokens; token++)
                        offer_literal(token, group_index, tokens, channels / 32);
            end
            receive_packets(tokens, channels);
        join
        finish_packetizer(0);
        if (accepted_groups - prior_groups != tokens * channels / 32)
            $fatal(1, "BATCH399_GROUP_INVENTORY");
        $display("BATCH399_FRAME tokens=%0d channels=%0d packets=%0d", tokens, channels, (channels + 79) / 80);
    endtask

    task automatic cancel_held_packet;
        logic [1279:0] held;
        configure(3, 160);
        for (int group_index = 0; group_index < 3; group_index++)
            for (int token = 0; token < 3; token++) offer_literal(token, group_index, 3, 5);
        if (mask_valid !== 1'b1 || mask_start !== 0 || in_ready)
            $fatal(1, "BATCH399_CANCELLATION_PACKET_ABSENT");
        held = mask_bits;
        drive_literal(0, 3, 3, 5);
        cancel_valid = 1; cancel_tag = TAG ^ 32'h1;
        repeat (4) begin
            @(negedge clk);
            if (mask_valid !== 1'b1 || mask_bits !== held || in_ready || done_valid)
                $fatal(1, "BATCH399_FOREIGN_CANCEL");
        end
        cancel_tag = TAG;
        mask_ready = 1;
        @(posedge clk);
        if (mask_valid || in_ready) $fatal(1, "BATCH399_CANCEL_TRANSFERRED");
        @(negedge clk);
        cancel_valid = 0; literal_valid = 0; mask_ready = 0;
        finish_packetizer(1);
        $display("BATCH399_HELD_PACKET_CANCELLED");
        run_frame(3, 96);
    endtask

    initial begin
        if (NATIVE) begin
            if (!$value$plusargs("FIXTURE=%s", fixture)) $fatal(1, "BATCH399_FIXTURE_REQUIRED");
            $readmemh({fixture, "/raw.hex"}, residual_words);
            $readmemh({fixture, "/gate_sign.hex"}, gate_words);
            $readmemh({fixture, "/up_sign.hex"}, up_words);
            $readmemh({fixture, "/branch_masks.hex"}, branch_masks);
        end
        repeat (3) @(negedge clk);
        rst_n = 1;
        if (NATIVE) begin
            run_frame(16, 5632);
            if (packets != 71 || compared_bits != 90112 || padding_bits != 768 || sign_reads != 55616)
                $fatal(1, "BATCH399_NATIVE_FINAL_INVENTORY");
        end else begin
            configure(1, 33);
            finish_packetizer(1);
            for (int fault = 1; fault <= 4; fault++) begin
                configure(1, 32);
                offer_literal(0, 0, 1, 1, fault);
                finish_packetizer(1);
            end
            run_frame(1, 32);
            run_frame(2, 64);
            run_frame(3, 96);
            run_frame(9, 128);
            run_frame(16, 160);
            run_frame(3, 192);
            run_frame(16, 8160);
            cancel_held_packet();
        end
        $display("BATCH399_PASS native=%0d packets=%0d mask_bits=%0d padding_bits=%0d sign_reads=%0d",
            NATIVE, packets, compared_bits, padding_bits, sign_reads);
        $finish;
    end

    initial begin #40000000; $fatal(1, "BATCH399_WATCHDOG"); end
endmodule
