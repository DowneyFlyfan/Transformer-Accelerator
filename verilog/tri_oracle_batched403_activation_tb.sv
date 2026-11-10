`timescale 1ns/1ps
module tri_oracle_batched403_activation_tb;
    localparam int TOKENS = 16;
    localparam int FEATURES = 2048;
    localparam int STRIPS = FEATURES / 8;

    logic clk = 0;
    always #5 clk = ~clk;
    logic rst_n = 0, cfg_valid = 0;
    wire cfg_ready;
    logic [31:0] cfg_tag = 0;
    logic [5:0] cfg_shift = 0;
    logic stats_valid = 0, stats_last = 0, replay_valid = 0, replay_last = 0;
    logic [127:0] stats_data = 0, replay_data = 0, replay_gamma = 0;
    wire stats_ready, replay_ready;
    logic out_ready = 0;
    wire out_valid, out_last, out_error;
    wire [31:0] out_tag;
    wire [9:0] out_index;
    wire [3:0] out_count;
    wire [127:0] out_norm_q8;
    wire [7:0] out_outlier_mask;
    wire [63:0] out_activation;
    logic [127:0] raw_words [TOKENS * STRIPS];
    logic [15:0] gamma_words [FEATURES], expected_norm [TOKENS * FEATURES];
    logic [7:0] expected_activation [TOKENS * FEATURES], shifts [TOKENS];
    int checked = 0, outliers = 0;
    string input_dir, expected_dir;

    tri_oracle_rms_activation dut (
        .clk(clk), .rst_n(rst_n), .cfg_valid(cfg_valid), .cfg_ready(cfg_ready),
        .cfg_tag(cfg_tag), .cfg_epsilon_q16(32'd43980465), .cfg_strips(10'(STRIPS)), .cfg_shift(cfg_shift),
        .stats_valid(stats_valid), .stats_ready(stats_ready), .stats_last(stats_last), .stats_data(stats_data),
        .replay_valid(replay_valid), .replay_ready(replay_ready), .replay_last(replay_last),
        .replay_data(replay_data), .replay_gamma(replay_gamma), .out_valid(out_valid), .out_ready(out_ready),
        .out_last(out_last), .out_error(out_error), .out_tag(out_tag), .out_index(out_index),
        .out_count(out_count), .out_norm_q8(out_norm_q8), .out_outlier_mask(out_outlier_mask),
        .out_activation(out_activation)
    );

    task automatic send_token(input int token);
        for (int strip = 0; strip < STRIPS; strip++) begin
            stats_valid = 1;
            stats_last = strip == STRIPS - 1;
            stats_data = raw_words[token * STRIPS + strip];
            do @(posedge clk); while (stats_ready !== 1'b1);
            @(negedge clk);
        end
        stats_valid = 0;
        stats_data = '1;
        for (int strip = 0; strip < STRIPS; strip++) begin
            replay_valid = 1;
            replay_last = strip == STRIPS - 1;
            replay_data = raw_words[token * STRIPS + strip];
            for (int lane = 0; lane < 8; lane++) replay_gamma[lane*16 +: 16] = gamma_words[strip*8 + lane];
            do @(posedge clk); while (replay_ready !== 1'b1);
            @(negedge clk);
        end
        replay_valid = 0;
        replay_data = '1;
        replay_gamma = 'x;
    endtask

    task automatic receive_token(input int token);
        int index;
        logic [127:0] norm_packet;
        logic [63:0] activation_packet;
        logic [7:0] outlier_mask;
        for (int strip = 0; strip < STRIPS; strip++) begin
            for (int lane = 0; lane < 8; lane++) begin
                index = token * FEATURES + strip * 8 + lane;
                norm_packet[lane*16 +: 16] = expected_norm[index];
                activation_packet[lane*8 +: 8] = expected_activation[index];
                outlier_mask[lane] = $signed(expected_norm[index]) > 16'sd768 ||
                    $signed(expected_norm[index]) < -16'sd768;
            end
            while (out_valid !== 1'b1) @(negedge clk);
            repeat (strip % 17 == 0 ? 4 : 1) begin
                if (out_valid !== 1'b1 || out_error !== 1'b0 || out_tag !== (32'h40300000 | 32'(token)) ||
                    out_index !== 10'(strip) || out_count !== 4'd8 || out_last !== (strip == STRIPS - 1) ||
                    out_norm_q8 !== norm_packet || out_activation !== activation_packet ||
                    out_outlier_mask !== outlier_mask)
                    $fatal(1, "BATCH403_ACTIVATION token=%0d strip=%0d got=%h expected=%h",
                        token, strip, out_activation, activation_packet);
                @(negedge clk);
            end
            out_ready = 1;
            @(negedge clk);
            out_ready = 0;
            checked += 8;
            outliers += $countones(outlier_mask);
        end
    endtask

    initial begin
        if (!$value$plusargs("INPUT=%s", input_dir) || !$value$plusargs("EXPECTED=%s", expected_dir))
            $fatal(1, "BATCH403_FIXTURES_REQUIRED");
        $readmemh({input_dir, "/raw.hex"}, raw_words);
        $readmemh({expected_dir, "/gamma.hex"}, gamma_words);
        $readmemh({expected_dir, "/norm.hex"}, expected_norm);
        $readmemh({expected_dir, "/activation.hex"}, expected_activation);
        $readmemh({expected_dir, "/shifts.hex"}, shifts);
        repeat (3) @(negedge clk);
        rst_n = 1;
        for (int token = 0; token < TOKENS; token++) begin
            cfg_valid = 1;
            cfg_tag = 32'h40300000 | 32'(token);
            cfg_shift = shifts[token][5:0];
            @(posedge clk);
            if (cfg_ready !== 1'b1) $fatal(1, "BATCH403_CONFIG");
            @(negedge clk);
            cfg_valid = 0;
            cfg_shift = '1;
            fork send_token(token); receive_token(token); join
        end
        if (checked != 32768 || outliers != 159 || !cfg_ready)
            $fatal(1, "BATCH403_INVENTORY");
        $display("BATCH403_NATIVE_PASS tokens=16 activation_codes=%0d norm_codes=%0d outliers=%0d", checked, checked, outliers);
        $finish;
    end

    initial begin #3000000; $fatal(1, "BATCH403_WATCHDOG"); end
endmodule
