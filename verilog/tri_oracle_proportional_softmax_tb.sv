`timescale 1ns/1ps
module tri_oracle_proportional_softmax_tb;
    localparam int MAX_KEYS = 1024;
    logic clk = 0;
    always #5 clk = ~clk;

    logic rst_n = 0, cfg_valid = 0, in_valid = 0, out_ready = 0;
    logic [10:0] cfg_length;
    logic signed [15:0] in_score;
    logic [9:0] in_size;
    wire cfg_ready, cfg_error, in_ready, out_valid, out_last;
    wire [15:0] out_probability;

    tri_oracle_proportional_softmax dut (.*);

    logic [15:0] scores [MAX_KEYS];
    logic [9:0] sizes [MAX_KEYS];
    logic [15:0] expected [MAX_KEYS];
    integer fixture, length, rows = 0, compared = 0, stalls = 0;
    string fixture_path;
    logic row_active;
    logic [10:0] inputs_pending;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            row_active <= 0;
            inputs_pending <= 0;
        end else begin
            if (out_valid && (!row_active || inputs_pending != 0))
                $fatal(1, "SOFTMAX_OUTPUT_WITHOUT_LOADED_ROW");
            if (cfg_valid && cfg_ready && cfg_length > 0 && cfg_length <= 11'(MAX_KEYS)) begin
                row_active <= 1;
                inputs_pending <= cfg_length;
            end
            if (in_valid && in_ready) inputs_pending <= inputs_pending - 1'b1;
            if (out_valid && out_ready && out_last) row_active <= 0;
        end
    end

    task automatic configure(input int entries, input bit invalid);
        @(negedge clk);
        cfg_valid = 1;
        cfg_length = 11'(entries);
        @(posedge clk);
        if (cfg_ready !== 1'b1) $fatal(1, "SOFTMAX_CONFIG_BUSY");
        #1;
        if (cfg_error !== invalid) $fatal(1, "SOFTMAX_CONFIG_ERROR length=%0d", entries);
        @(negedge clk);
        cfg_valid = 0;
    endtask

    task automatic send_key(input logic signed [15:0] score, input logic [9:0] size);
        @(negedge clk);
        in_valid = 1;
        in_score = score;
        in_size = size;
        @(posedge clk);
        if (in_ready !== 1'b1) $fatal(1, "SOFTMAX_INPUT_STALLED");
        @(negedge clk);
        in_valid = 0;
    endtask

    task automatic check_word(input int index);
        if (out_valid !== 1'b1 || out_probability !== expected[index] ||
            out_last !== (index == length-1))
            $fatal(1, "SOFTMAX_MISMATCH row=%0d key=%0d observed=%0d expected=%0d last=%0d",
                   rows, index, out_probability, expected[index], out_last);
    endtask

    initial begin
        if (!$value$plusargs("FIXTURE=%s", fixture_path)) $fatal(1, "Missing fixture");
        fixture = $fopen(fixture_path, "r");
        if (!fixture) $fatal(1, "Could not open fixture");
        repeat (2) @(negedge clk);
        rst_n = 1;
        configure(0, 1);
        configure(MAX_KEYS+1, 1);
        configure(2, 0);
        send_key(-16'sd19, 10'd1);
        rst_n = 0;
        repeat (2) @(negedge clk);
        rst_n = 1;

        configure(1, 0);
        send_key(16'sd0, 10'd1);
        do @(negedge clk); while (!out_valid);
        cfg_valid = 1;
        cfg_length = 11'd2;
        repeat (3) begin
            @(posedge clk);
            if (cfg_ready || cfg_error || !out_valid || !out_last || out_probability != 16'hffff)
                $fatal(1, "SOFTMAX_BUSY_CONFIGURATION");
        end
        @(negedge clk);
        rst_n = 0;
        cfg_valid = 0;
        repeat (2) @(negedge clk);
        if (out_valid || in_ready || !cfg_ready) $fatal(1, "SOFTMAX_RESET_DRAIN");
        rst_n = 1;

        configure(2, 0);
        send_key(16'sd0, 10'd1);
        send_key(16'shxxxx, 10'd0);
        length = 2;
        expected[0] = 16'hffff;
        expected[1] = 16'h0000;
        out_ready = 1;
        for (int key = 0; key < length; key++) begin
            do @(posedge clk); while (!out_valid);
            check_word(key);
        end
        @(negedge clk);
        out_ready = 0;

        while ($fscanf(fixture, "%d", length) == 1) begin
            if (length < 1 || length > MAX_KEYS) $fatal(1, "Invalid fixture length");
            for (int key = 0; key < length; key++)
                if ($fscanf(fixture, "%h %d %d", scores[key], sizes[key], expected[key]) != 3)
                    $fatal(1, "Invalid fixture word");
            configure(length, 0);
            @(negedge clk);
            in_valid = 1;
            for (int key = 0; key < length; key++) begin
                in_score = scores[key];
                in_size = sizes[key];
                @(posedge clk);
                if (!in_ready) $fatal(1, "SOFTMAX_INPUT_STALLED");
                @(negedge clk);
            end
            in_valid = 0;
            for (int key = 0; key < length; key++) begin
                if (key == length-1 || key % 23 == 0) begin
                    do @(negedge clk); while (!out_valid);
                    repeat (3) begin
                        @(posedge clk);
                        check_word(key);
                        if (in_ready || cfg_ready) $fatal(1, "SOFTMAX_PREMATURE_READY");
                        stalls++;
                    end
                    @(negedge clk);
                end
                out_ready = 1;
                do @(posedge clk); while (!out_valid);
                check_word(key);
                compared++;
                @(negedge clk);
                out_ready = 0;
            end
            if (out_valid) $fatal(1, "SOFTMAX_DUPLICATE");
            rows++;
        end
        if (!$feof(fixture) || rows == 0) $fatal(1, "Invalid fixture termination");
        $fclose(fixture);
        repeat (3) @(negedge clk);
        $display("SOFTMAX_PASS rows=%0d words=%0d stalls=%0d", rows, compared, stalls);
        $finish;
    end

    initial begin
        #10_000_000;
        $fatal(1, "SOFTMAX_TIMEOUT");
    end
endmodule
