`timescale 1ns/1ps

module tri_oracle_attention_projection_stream_tb;
    logic clk = 0, rst_n = 0;
    always #5 clk = ~clk;

    logic in_valid = 0, in_ready;
    logic [2047:0] in_data;
    logic [4:0] in_shift;
    logic [5:0] in_row;
    logic out_valid, out_ready = 0, out_last;
    logic [5:0] out_row;
    logic [2:0] out_word;
    logic [63:0] out_data;
    logic [2052:0] operands[64];
    logic [511:0] expected[64];
    string inputs, outputs;
    int words = 0, stalls = 0, resets = 0;

    tri_oracle_attention_projection_stream dut (.*);

    task automatic check_word(input int row, word, input bit ready);
        out_ready = ready;
        @(posedge clk);
        if ({out_valid, in_ready, out_row, out_word, out_last, out_data} !==
            {1'b1, (ready && word == 7), 6'(row), 3'(word), (word == 7), expected[row][64*word +: 64]})
            $fatal(1, "PROJECTION_STREAM_MISMATCH row=%0d word=%0d ready=%b", row, word, ready);
        if (ready) words++;
        else stalls++;
        @(negedge clk);
    endtask

    task automatic offer(input int row);
        in_row = 6'(row);
        {in_shift, in_data} = operands[row];
        in_valid = 1;
    endtask

    initial begin
        if (!$value$plusargs("OPERANDS=%s", inputs) || !$value$plusargs("EXPECTED=%s", outputs))
            $fatal(1, "PROJECTION_STREAM_ARGUMENTS");
        $readmemh(inputs, operands);
        $readmemh(outputs, expected);
        repeat (2) @(negedge clk);
        rst_n = 1;

        // Abort a partially consumed row and require the first word back after reset.
        offer(63);
        check_word(63, 0, 1);
        check_word(63, 1, 0);
        rst_n = 0;
        in_valid = 0;
        #1;
        if ({out_valid, in_ready} !== 2'b00) $fatal(1, "PROJECTION_STREAM_RESET");
        repeat (2) @(negedge clk);
        rst_n = 1;
        resets++;
        words = 0;
        stalls = 0;

        // Odd stride permutes all 64 rows with immediate changes after acceptance.
        for (int index = 0; index < 64; index++) begin
            int row;
            row = (index * 17 + 63) % 64;
            if (index % 5 == 0) begin
                in_valid = 0;
                out_ready = 1;
                @(posedge clk);
                if ({out_valid, in_ready} !== 2'b00) $fatal(1, "PROJECTION_STREAM_IDLE");
                @(negedge clk);
            end
            offer(row);
            for (int word = 0; word < 8; word++) begin
                repeat ((index + word) % 4) check_word(row, word, 0);
                check_word(row, word, 1);
            end
        end
        in_valid = 0;
        @(posedge clk);
        if (out_valid || words != 512 || stalls != 768 || resets != 1)
            $fatal(1, "PROJECTION_STREAM_INVENTORY");
        $display("PROJECTION_STREAM_PASS rows=64 words=%0d stalls=%0d resets=%0d", words, stalls, resets);
        $finish;
    end

    initial begin
        #20000;
        $fatal(1, "PROJECTION_STREAM_TIMEOUT");
    end
endmodule
