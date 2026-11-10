`timescale 1ns/1ps
module tri_oracle_attention411_score_tb #(
    parameter int FIRST_HEAD = 0, HEAD_COUNT = 32
);
    localparam int HEADS = 32, ROWS = 15, WIDTH = 64, SEQUENCE = 606;
    localparam logic [31:0] TAG = 32'h4110cafe;
    localparam logic [63:0] QUERY_BASE = 64'h10000, KEY_BASE = 64'h100000;
    logic clk = 0;
    always #5 clk = ~clk;
    logic rst_n = 0;
    logic row_valid = 0, row_last;
    wire row_ready;
    logic [31:0] row_tag;
    logic [63:0] row_query_addr, row_key_base;
    logic [16:0] row_key_rows;
    logic [15:0] row_query_index;
    logic [47:0] row_tile_start;
    logic [17:0] row_tile_valid_keys;
    wire score_valid, score_last, score_error, score_ready;
    wire [31:0] score_tag;
    wire [1:0] score_region;
    wire [7:0] score_lanes;
    wire [255:0] score_data;
    wire tensor_cfg_valid, tensor_cfg_ready, tensor_out_valid, tensor_out_last, tensor_out_ready;
    wire tensor_done_valid, tensor_done_error, tensor_done_ready;
    wire [31:0] tensor_cfg_tag, tensor_out_tag, tensor_done_tag;
    wire [16:0] tensor_cfg_dense_rows;
    wire [2559:0] tensor_cfg_channels, tensor_cfg_keep;
    wire [63:0] tensor_cfg_activation_base, tensor_cfg_weight_base;
    wire [3:0] tensor_out_token;
    wire [7:0] tensor_out_count;
    wire [5119:0] tensor_results;
    wire [3071:0] tensor_out_data = tensor_results[3071:0];
    wire req_valid, req_ready, rsp_valid, rsp_ready, rsp_last, rsp_error;
    wire [63:0] req_address, rsp_data;
    wire [4:0] req_length;
    logic cfg_valid = 0;
    wire cfg_ready, classifier_in_ready, out_valid, out_error, out_streaming;
    logic out_ready = 0;
    logic [31:0] cfg_alpha;
    logic [12:0] cfg_rows;
    wire [31:0] out_tag;
    wire [17:0] out_inner, out_outer;
    logic [7:0] queries[HEADS*ROWS*WIDTH], keys[4*SEQUENCE*WIDTH];
    logic signed [31:0] expected_scores[HEADS*ROWS*3*32];
    logic [31:0] alphas[HEADS];
    logic [7:0] counts[HEADS*ROWS*2], types[HEADS];
    logic [63:0] read_address;
    logic reading = 0;
    int words_left, word_in_burst, cycles = 0;
    int head_index, row_index, score_beats, reads = 0, errors = 0;
    int trained_scores = 0, partial_scores = 0, stalls = 0, streaming_heads = 0;
    int key_starts[3], valid_keys[3], fault = 0;
    int query_words[8], key_words[3][32][8];
    logic [63:0] expected_query, expected_key;
    logic blocked = 0;
    logic [299:0] held_score;
    wire [299:0] score_packet = {score_tag, score_last, score_error, score_region, score_lanes, score_data};
    wire permit = cycles % 5 < 2;
    string fixture;

    tri_oracle_attention_score_adapter411 adapter (.*);
    tri_oracle_batched_tensor390 tensor (
        .clk, .rst_n, .cfg_valid(tensor_cfg_valid), .cfg_ready(tensor_cfg_ready),
        .cfg_paired(1'b0), .cfg_tag(tensor_cfg_tag), .cfg_tokens(5'd1), .cfg_feature_words(10'd8),
        .cfg_dense_rows(tensor_cfg_dense_rows), .cfg_count(8'd96), .cfg_channels(tensor_cfg_channels),
        .cfg_keep(tensor_cfg_keep), .cfg_activation_base(tensor_cfg_activation_base),
        .cfg_weight_base(tensor_cfg_weight_base), .cfg_up_weight_base(64'd0), .cfg_activation_stride(32'd64),
        .out_valid(tensor_out_valid), .out_ready(tensor_out_ready), .out_tag(tensor_out_tag),
        .out_token(tensor_out_token), .out_last(tensor_out_last), .out_count(tensor_out_count),
        .out_channels(), .out_data(tensor_results), .done_valid(tensor_done_valid), .done_ready(tensor_done_ready),
        .done_error(tensor_done_error), .done_tag(tensor_done_tag),
        .req_valid, .req_ready, .req_address, .req_length, .rsp_valid, .rsp_ready, .rsp_last, .rsp_error, .rsp_data
    );
    assign score_ready = classifier_in_ready && permit;
    tri_oracle_attention_head_classifier410 classifier (
        .clk, .rst_n, .cfg_valid, .cfg_ready, .cfg_tag(TAG), .cfg_alpha, .cfg_rows,
        .cfg_ratio_num(8'd1), .cfg_ratio_den(8'd1), .in_valid(score_valid && permit),
        .in_last(score_last), .in_ready(classifier_in_ready), .in_tag(score_tag), .in_region(score_region),
        .in_lanes(score_lanes), .in_scores(score_data), .out_valid, .out_ready, .out_error,
        .out_streaming, .out_tag, .out_inner, .out_outer
    );

    assign req_ready = !reading && cycles % 7 != 0;
    assign rsp_valid = reading;
    assign rsp_last = words_left == 1;
    assign rsp_error = fault == 3 && word_in_burst == 0;
    for (genvar byte_index = 0; byte_index < 8; byte_index++) begin : memory_read
        assign rsp_data[byte_index*8 +: 8] = read_address >= KEY_BASE ?
            keys[int'(read_address-KEY_BASE)+byte_index] : queries[int'(read_address-QUERY_BASE)+byte_index];
    end

    always @(posedge clk) if (rst_n) begin
        cycles <= cycles + 1;
        if (req_valid && req_ready) begin
            if (fault inside {1, 2, 4} || req_length == 0 || req_length > 2 || req_address[2:0] != 0)
                $fatal(1, "BATCH411_ILLEGAL_READ fault=%0d addr=%h len=%0d", fault, req_address, req_length);
            for (int word = 0; word < int'(req_length); word++) begin
                logic [63:0] addr;
                int key, feature_word, region, lane;
                addr = req_address + 64'(8*word);
                if (addr >= expected_query && addr < expected_query+64) begin
                    feature_word = int'(addr-expected_query)/8;
                    query_words[feature_word]++;
                end else if (addr >= expected_key && addr < expected_key+SEQUENCE*WIDTH) begin
                    key = int'(addr-expected_key)/WIDTH;
                    feature_word = (int'(addr-expected_key)%WIDTH)/8;
                    region = -1; lane = 0;
                    for (int i = 0; i < 3; i++)
                        if (key >= key_starts[i] && key < key_starts[i]+valid_keys[i]) begin
                            region = i; lane = key-key_starts[i];
                        end
                    if (region == -1) $fatal(1, "BATCH411_UNSELECTED_KEY key=%0d", key);
                    key_words[region][lane][feature_word]++;
                end else $fatal(1, "BATCH411_READ_OUTSIDE_ROW addr=%h", addr);
            end
            reads++;
            reading <= 1;
            read_address <= req_address;
            words_left <= int'(req_length);
            word_in_burst <= 0;
        end else if (rsp_valid && rsp_ready) begin
            reading <= !rsp_last;
            read_address <= read_address+64'd8;
            words_left <= words_left-1;
            word_in_burst <= word_in_burst+1;
        end

        if (blocked && (!score_valid || score_packet !== held_score)) $fatal(1, "BATCH411_UNSTABLE_SCORE");
        blocked <= score_valid && !score_ready;
        if (score_valid && !score_ready) begin
            held_score <= score_packet;
            stalls++;
        end
        if (score_valid && score_ready) begin
            if (score_tag !== TAG) $fatal(1, "BATCH411_WRONG_SCORE_TAG");
            if (fault != 0) begin
                if (!score_error || !score_last || score_region != 2 || score_lanes != 0 || score_data != 0)
                    $fatal(1, "BATCH411_ERROR_EXPOSED_SCORES fault=%0d", fault);
                errors++;
            end else begin
                if (score_error || score_region != score_beats/4 || score_last !== (row_last && score_beats==11))
                    $fatal(1, "BATCH411_SCORE_ORDER head=%0d row=%0d beat=%0d", head_index, row_index, score_beats);
                for (int lane = 0; lane < 8; lane++) begin
                    int key_lane;
                    bit live_lane;
                    logic [31:0] expected;
                    key_lane = (score_beats%4)*8+lane;
                    live_lane = key_lane < valid_keys[score_region];
                    expected = live_lane ? expected_scores[((head_index*ROWS+row_index)*3+int'(score_region))*32+key_lane] : 0;
                    if (score_lanes[lane] !== live_lane || score_data[lane*32 +: 32] !== expected)
                        $fatal(1, "BATCH411_WRONG_SCORE head=%0d row=%0d region=%0d lane=%0d expected=%h actual=%h",
                               head_index, row_index, score_region, key_lane, expected, score_data[lane*32 +: 32]);
                    if (live_lane) begin
                        if (valid_keys[1] == 32) trained_scores++;
                        else partial_scores++;
                    end
                end
            end
            score_beats++;
        end
    end

    task automatic configure(input int head, rows);
        @(negedge clk);
        cfg_valid = 1; cfg_rows = 13'(rows); cfg_alpha = alphas[head];
        @(posedge clk);
        if (!cfg_ready) $fatal(1, "BATCH411_CONFIG_NOT_READY");
        @(negedge clk);
        cfg_valid = 0;
    endtask

    task automatic send_row(input int head, row, input bit last, partial, input int problem);
        int read_before;
        @(negedge clk);
        head_index = head; row_index = row; fault = problem; score_beats = 0; read_before = reads;
        expected_query = QUERY_BASE+64'((head*ROWS+row)*WIDTH);
        expected_key = KEY_BASE+64'((head/8)*SEQUENCE*WIDTH);
        key_starts = '{0, (row+1)*32, (row+3)*32};
        valid_keys = '{32, partial ? 17 : 32, partial ? 9 : 32};
        foreach (query_words[i]) query_words[i] = 0;
        foreach (key_words[i,j,k]) key_words[i][j][k] = 0;
        row_valid = 1; row_tag = TAG; row_last = last;
        row_query_addr = expected_query + (fault == 2 ? 64'd1 : 64'd0);
        row_key_base = expected_key; row_key_rows = 17'(SEQUENCE);
        row_query_index = 16'(127+32*row);
        row_tile_start = {fault == 1 ? 16'(SEQUENCE-7) : 16'(key_starts[2]+int'(fault==4)),
                          16'(key_starts[1]), 16'd0};
        row_tile_valid_keys = {6'(valid_keys[2]), 6'(valid_keys[1]), 6'd32};
        @(posedge clk);
        if (!row_ready) $fatal(1, "BATCH411_ROW_NOT_READY");
        @(negedge clk);
        row_valid = 0;
        row_tag = 'x; row_query_addr = 'x; row_key_base = 'x;
        row_key_rows = 'x; row_query_index = 'x; row_tile_start = 'x; row_tile_valid_keys = 'x;
        while (!row_ready) @(negedge clk);
        if (score_beats != (fault == 0 ? 12 : 1)) $fatal(1, "BATCH411_SCORE_INVENTORY");
        if (fault != 0) begin
            if (reads-read_before != (fault == 3 ? 1 : 0) || reading)
                $fatal(1, "BATCH411_FAULT_READ_INVENTORY");
        end else begin
            for (int word = 0; word < 8; word++) begin
                bit nonzero;
                nonzero = 0;
                for (int i = 0; i < 8; i++) nonzero |= queries[(head*ROWS+row)*WIDTH+word*8+i] != 0;
                if (query_words[word] != 1) $fatal(1, "BATCH411_QUERY_READ_INVENTORY");
                for (int region = 0; region < 3; region++)
                    for (int lane = 0; lane < 32; lane++)
                        if (key_words[region][lane][word] != int'(nonzero && lane < valid_keys[region]))
                            $fatal(1, "BATCH411_KEY_READ_INVENTORY region=%0d key=%0d word=%0d", region, lane, word);
            end
        end
    endtask

    task automatic finish_head(input int inner_count, recent_count, input bit streaming, error);
        while (!out_valid) @(negedge clk);
        repeat (3) begin
            if (!out_valid || out_tag !== TAG || out_error !== error || out_streaming !== streaming ||
                out_inner !== 18'(inner_count) || out_outer !== 18'(recent_count))
                $fatal(1, "BATCH411_WRONG_CLASS head=%0d expected=%0d/%0d/%b got=%0d/%0d/%b error=%b",
                       head_index, inner_count, recent_count, streaming, out_inner, out_outer, out_streaming, out_error);
            @(negedge clk);
        end
        out_ready = 1;
        @(negedge clk);
        out_ready = 0;
    endtask

    initial begin
        if (!$value$plusargs("FIXTURE=%s", fixture)) $fatal(1, "BATCH411_FIXTURE_REQUIRED");
        $readmemh({fixture, "/query.hex"}, queries);
        $readmemh({fixture, "/key.hex"}, keys);
        $readmemh({fixture, "/scores.hex"}, expected_scores);
        $readmemh({fixture, "/alpha.hex"}, alphas);
        $readmemh({fixture, "/counts.hex"}, counts);
        $readmemh({fixture, "/streaming.hex"}, types);
        repeat (3) @(negedge clk);
        rst_n = 1;
        if (FIRST_HEAD == 0) begin
            int inner_count, recent_count, cutoff;
            for (int problem = 1; problem <= 4; problem++) begin
                configure(0, 2);
                send_row(0, 0, 0, 0, problem);
                finish_head(0, 0, 0, 1);
            end
            cutoff = expected_scores[0];
            for (int lane = 1; lane < 32; lane++)
                if (expected_scores[lane] > cutoff) cutoff = expected_scores[lane];
            cutoff -= int'(alphas[0]);
            inner_count = 0; recent_count = 0;
            for (int lane = 0; lane < 17; lane++) inner_count += int'(expected_scores[32+lane] > cutoff);
            for (int lane = 0; lane < 9; lane++) recent_count += int'(expected_scores[64+lane] > cutoff);
            configure(0, 1);
            send_row(0, 0, 1, 1, 0);
            finish_head(inner_count, recent_count, recent_count > inner_count, 0);
        end
        for (int head = FIRST_HEAD; head < FIRST_HEAD+HEAD_COUNT; head++) begin
            int inner_count, recent_count;
            inner_count = 0; recent_count = 0;
            configure(head, ROWS);
            for (int row = 0; row < ROWS; row++) begin
                send_row(head, row, row == ROWS-1, 0, 0);
                inner_count += int'(counts[(head*ROWS+row)*2]);
                recent_count += int'(counts[(head*ROWS+row)*2+1]);
                if (classifier.total_inner !== 18'(inner_count) || classifier.total_outer !== 18'(recent_count))
                    $fatal(1, "BATCH411_WRONG_ROW_COUNTS head=%0d row=%0d", head, row);
            end
            finish_head(inner_count, recent_count, types[head][0], 0);
            streaming_heads += int'(types[head][0]);
        end
        if (trained_scores != HEAD_COUNT*ROWS*3*32 || stalls == 0 ||
            errors != (FIRST_HEAD == 0 ? 4 : 0) || partial_scores != (FIRST_HEAD == 0 ? 58 : 0))
            $fatal(1, "BATCH411_FINAL_INVENTORY");
        $display("BATCH411_PASS first=%0d heads=%0d rows=%0d scores=%0d streaming=%0d partial_scores=%0d errors=%0d reads=%0d stalls=%0d",
                 FIRST_HEAD, HEAD_COUNT, HEAD_COUNT*ROWS, trained_scores, streaming_heads, partial_scores, errors, reads, stalls);
        $finish;
    end
    initial begin #50000000; $fatal(1, "BATCH411_WATCHDOG"); end
endmodule
