`timescale 1ns/1ps
module tri_oracle_residual_add_tb;
    localparam int FixtureWords = 512;
    localparam int CornerWords = 16;
    localparam int Strips = FixtureWords / 2;
    logic clk = 0, rst_n = 0;
    logic cfg_valid = 0, cfg_ready;
    logic [31:0] cfg_tag = 0;
    logic stats_valid = 0, stats_ready, stats_last = 0;
    logic replay_valid = 0, replay_ready, replay_last = 0;
    logic [127:0] replay_gamma = 0;
    logic out_valid, out_ready = 0, out_last, out_error;
    logic [31:0] out_tag;
    logic [9:0] out_index;
    logic [3:0] out_count;
    logic [127:0] out_norm_q8;
    logic [7:0] out_outlier_mask;
    logic [63:0] out_activation;
    logic [215:0] residual_q25;
    logic [63:0] projection_codes;
    logic [4:0] projection_shift;
    logic [127:0] result_q13;
    logic [412:0] vectors [FixtureWords + CornerWords];
    logic [255:0] normalization_inputs [FixtureWords];
    logic [247:0] normalization_expected [FixtureWords];
    int checked = 0, cycle = 0;
    string fixture, norm_inputs_file, norm_expected_file;

    tri_oracle_residual_add dut (.*);

    tri_oracle_rms_activation activation (
        .clk, .rst_n, .cfg_valid, .cfg_ready, .cfg_tag,
        .cfg_epsilon_q16(32'd43980465), .cfg_strips(10'(Strips)), .cfg_shift(6'd17),
        .stats_valid, .stats_ready, .stats_last, .stats_data(result_q13),
        .replay_valid, .replay_ready, .replay_last, .replay_data(result_q13), .replay_gamma,
        .out_valid, .out_ready, .out_last, .out_error, .out_tag, .out_index,
        .out_count, .out_norm_q8, .out_outlier_mask, .out_activation
    );

    always #5 clk = ~clk;
    always @(negedge clk) begin
        cycle++;
        out_ready = cycle % 17 < 5;
    end

    always @(posedge clk) begin
        if (rst_n && out_valid && out_ready) begin
            if (checked >= FixtureWords ||
                {out_tag, out_index, out_count, out_last, out_error, out_norm_q8,
                 out_outlier_mask, out_activation} !== normalization_expected[checked])
                $fatal(1, "RESIDUAL_NORMALIZATION_MISMATCH word=%0d", checked);
            checked++;
        end
    end

    task automatic drive_operands(input int word_index);
        {projection_shift, projection_codes, residual_q25} = vectors[word_index][284:0];
    endtask

    task automatic normalize_token(input int token);
        @(negedge clk); #1;
        cfg_tag = 32'ha4010000 + 32'(token);
        cfg_valid = 1;
        do @(posedge clk); while (cfg_ready !== 1'b1);
        @(negedge clk); #1;
        cfg_valid = 0;
        for (int strip = 0; strip < Strips; strip++) begin
            drive_operands(token * Strips + strip);
            stats_valid = 1;
            stats_last = strip == Strips - 1;
            do @(posedge clk); while (stats_ready !== 1'b1);
            @(negedge clk); #1;
        end
        stats_valid = 0;
        for (int strip = 0; strip < Strips; strip++) begin
            drive_operands(token * Strips + strip);
            replay_gamma = normalization_inputs[token * Strips + strip][255:128];
            replay_valid = 1;
            replay_last = strip == Strips - 1;
            do @(posedge clk); while (replay_ready !== 1'b1);
            @(negedge clk); #1;
        end
        replay_valid = 0;
        wait (checked == (token + 1) * Strips && cfg_ready);
    endtask

    initial begin
        #200000;
        $fatal(1, "RESIDUAL_NORMALIZATION_TIMEOUT word=%0d", checked);
    end

    initial begin
        logic [127:0] expected;
        if (!$value$plusargs("VECTORS=%s", fixture) ||
            !$value$plusargs("NORM_INPUTS=%s", norm_inputs_file) ||
            !$value$plusargs("NORM_EXPECTED=%s", norm_expected_file))
            $fatal(1, "RESIDUAL_ADD_FIXTURE_MISSING");
        $readmemh(fixture, vectors);
        $readmemh(norm_inputs_file, normalization_inputs);
        $readmemh(norm_expected_file, normalization_expected);
        for (int i = 0; i < FixtureWords + CornerWords; i++) begin
            {expected, projection_shift, projection_codes, residual_q25} = vectors[i];
            #1;
            if (result_q13 !== expected)
                $fatal(1, "RESIDUAL_ADD_MISMATCH word=%0d actual=%h expected=%h", i, result_q13, expected);
        end
        $display("RESIDUAL_ADD_PASS fixture_words=%0d corner_words=%0d", FixtureWords, CornerWords);
        @(negedge clk); #1;
        rst_n = 1;
        normalize_token(0);
        normalize_token(1);
        $display("RESIDUAL_NORMALIZATION_PASS words=%0d", checked);
        $finish;
    end
endmodule
