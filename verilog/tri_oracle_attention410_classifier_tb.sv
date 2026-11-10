`timescale 1ns/1ps
module tri_oracle_attention410_classifier_tb;
    localparam int HEADS = 32, ROWS = 15, TILE = 32;
    localparam logic [31:0] TAG = 32'h4100cafe;
    logic clk = 0;
    always #5 clk = ~clk;
    logic rst_n = 0, cfg_valid = 0;
    wire cfg_ready;
    logic [31:0] cfg_tag = 0, cfg_alpha = 0;
    logic [12:0] cfg_rows = 0;
    logic [7:0] cfg_ratio_num = 0, cfg_ratio_den = 0;
    logic in_valid = 0, in_last = 0;
    wire in_ready;
    logic [31:0] in_tag = 0;
    logic [1:0] in_region = 0;
    logic [7:0] in_lanes = 0;
    logic [255:0] in_scores = 0;
    wire out_valid, out_error, out_streaming;
    logic out_ready = 0;
    wire [31:0] out_tag;
    wire [17:0] out_inner, out_outer;
    logic [31:0] tile_scores [HEADS * ROWS * 3 * TILE];
    logic [31:0] alphas [HEADS];
    logic [7:0] intensities [HEADS * ROWS * 2], expected_streaming [HEADS];
    int trained_scores = 0, streaming_heads = 0;
    string fixture;

    tri_oracle_attention_head_classifier410 dut (.*);

    task automatic configure(
        input int rows, input logic [31:0] alpha, input logic [7:0] ratio_num, ratio_den
    );
        @(negedge clk);
        cfg_valid = 1;
        cfg_tag = TAG; cfg_rows = 13'(rows); cfg_alpha = alpha;
        cfg_ratio_num = ratio_num; cfg_ratio_den = ratio_den;
        @(posedge clk);
        if (cfg_ready !== 1'b1) $fatal(1, "BATCH410_CONFIG_NOT_READY");
        @(negedge clk);
        cfg_valid = 0;
        cfg_tag = '1; cfg_rows = '1; cfg_alpha = '1; cfg_ratio_num = '1; cfg_ratio_den = '1;
    endtask

    task automatic offer(
        input int region, input logic [255:0] scores, input logic [7:0] lanes,
        input bit last, input logic [31:0] tag = TAG
    );
        in_valid = 1; in_region = 2'(region); in_scores = scores; in_lanes = lanes;
        in_last = last; in_tag = tag;
        do @(posedge clk); while (in_ready !== 1'b1);
        @(negedge clk);
        in_valid = 0; in_scores = 'x;
    endtask

    task automatic finish_head(input int inner_count, outer_count, input bit streaming, error);
        while (out_valid !== 1'b1) @(negedge clk);
        repeat (4) begin
            if (out_valid !== 1'b1 || cfg_ready || in_ready || out_error !== error || out_tag !== TAG ||
                out_inner !== 18'(inner_count) || out_outer !== 18'(outer_count) ||
                out_streaming !== streaming)
                $fatal(1, "BATCH410_HEAD expected=%0d/%0d got=%0d/%0d streaming=%b error=%b",
                    inner_count, outer_count, out_inner, out_outer, out_streaming, out_error);
            @(negedge clk);
        end
        out_ready = 1;
        @(negedge clk);
        out_ready = 0;
        if (!cfg_ready) $fatal(1, "BATCH410_OWNER_NOT_RELEASED");
    endtask

    task automatic trained_head(input int head);
        int inner_count, outer_count, offset;
        logic [255:0] scores;
        configure(ROWS, alphas[head], 1, 1);
        inner_count = 0; outer_count = 0;
        for (int row = 0; row < ROWS; row++) begin
            for (int region = 0; region < 3; region++)
                for (int beat = 0; beat < TILE/8; beat++) begin
                    offset = ((head * ROWS + row)*3 + region)*TILE + beat*8;
                    for (int lane = 0; lane < 8; lane++)
                        scores[lane*32 +: 32] = tile_scores[offset+lane];
                    offer(region, scores, 8'hff, row==ROWS-1 && region==2 && beat==TILE/8-1);
                    trained_scores += 8;
                end
            inner_count += int'(intensities[(head*ROWS+row)*2]);
            outer_count += int'(intensities[(head*ROWS+row)*2+1]);
            if (dut.total_inner !== 18'(inner_count) || dut.total_outer !== 18'(outer_count))
                $fatal(1, "BATCH410_ROW_COUNTS head=%0d row=%0d", head, row);
            if (row!=ROWS-1 && out_valid) $fatal(1, "BATCH410_EARLY_HEAD");
        end
        finish_head(inner_count, outer_count, expected_streaming[head][0], 0);
        streaming_heads += int'(expected_streaming[head][0]);
    endtask

    task automatic synthetic_head(input int rows, input bit extreme);
        // The extreme cutoff is below every signed32 score. Invalid lanes
        // must still be excluded. The other case exercises maximum totals.
        configure(rows, extreme ? 32'hffffffff : 32'd4, 8'd255, 8'd255);
        for (int row = 0; row < rows; row++)
            for (int region = 0; region < 3; region++)
                for (int beat = 0; beat < 4; beat++)
                    offer(region, extreme ? {8{32'h80000000}} : {8{32'd7}},
                        extreme ? (beat!=0 ? 8'd0 : (region==2 ? 8'h07 : 8'h03)) : 8'hff,
                        row==rows-1 && region==2 && beat==3);
        finish_head(extreme ? 2 : rows*32, extreme ? 3 : rows*32, extreme, 0);
    endtask

    task automatic cutoff_head(input logic [7:0] ratio_num, ratio_den, input bit streaming);
        configure(1, 4, ratio_num, ratio_den);
        for (int beat = 0; beat < 3; beat++) offer(0, {8{32'd9}}, 8'hff, 0);
        // The final valid sink maximum is 10. The masked lane cannot raise it.
        offer(0, {32'h7fffffff, 192'd0, 32'd10}, 8'h01, 0);
        offer(1, {96'd0, 32'h7fffffff, 32'd7, 32'd7, 32'd6, 32'd5}, 8'h0f, 0);
        for (int beat = 0; beat < 3; beat++) offer(1, {8{32'h7fffffff}}, 8'h00, 0);
        offer(2, {64'd0, 32'h7fffffff, 32'd7, 32'd7, 32'd7, 32'd6, 32'd5}, 8'h1f, 0);
        for (int beat = 0; beat < 3; beat++) offer(2, {8{32'h7fffffff}}, 8'h00, beat == 2);
        finish_head(2, 3, streaming, 0);
    endtask

    initial begin
        if (!$value$plusargs("FIXTURE=%s", fixture)) $fatal(1, "BATCH410_FIXTURE_REQUIRED");
        $readmemh({fixture, "/scores.hex"}, tile_scores);
        $readmemh({fixture, "/alpha.hex"}, alphas);
        $readmemh({fixture, "/counts.hex"}, intensities);
        $readmemh({fixture, "/streaming.hex"}, expected_streaming);
        repeat (3) @(negedge clk);
        rst_n = 1;
        configure(1, 4, 1, 0);
        finish_head(0, 0, 0, 1);
        configure(1, 4, 1, 1);
        offer(1, '0, 8'hff, 0);
        repeat (5) begin
            if (out_valid) $fatal(1, "BATCH410_DONE_BEFORE_LAST");
            @(negedge clk);
        end
        offer(2, '0, 8'hff, 1);
        finish_head(0, 0, 0, 1);
        configure(1, 4, 1, 1);
        for (int beat = 0; beat < 4; beat++) offer(0, '0, 8'd0, 0);
        offer(2, '0, 8'hff, 1);
        finish_head(0, 0, 0, 1);
        cutoff_head(4, 3, 1);
        cutoff_head(3, 2, 0);
        cutoff_head(2, 1, 0);
        cutoff_head(0, 1, 1);
        synthetic_head(1, 1);
        synthetic_head(4096, 0);
        for (int head = 0; head < HEADS; head++) trained_head(head);
        if (trained_scores != 46080 || streaming_heads != 4)
            $fatal(1, "BATCH410_FINAL_INVENTORY");
        $display("BATCH410_PASS heads=32 rows=480 scores=46080 streaming=4 max_rows=4096 fault_controls=3 cutoff_controls=4");
        $finish;
    end
    initial begin #10000000; $fatal(1, "BATCH410_WATCHDOG"); end
endmodule
