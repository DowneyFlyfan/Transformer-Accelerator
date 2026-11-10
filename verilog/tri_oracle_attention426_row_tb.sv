`timescale 1ns/1ps
module tri_oracle_attention426_row_tb;
    localparam logic [63:0] QUERY_ADDR = 64'h1000, KEY_ADDR = 64'h2000;
    logic clk = 0, rst_n = 0;
    always #5 clk = ~clk;

    logic frame_valid = 0, map_valid = 0, row_valid = 0, result_ready = 0;
    logic [9:0] frame_image_start, map_origin;
    logic [10:0] row_key_count, row_position;
    logic [31:0] row_tag;
    logic row_streaming;
    logic signed [6:0] row_score_shift;
    wire frame_ready, frame_error, map_ready, row_ready, result_valid, result_error;
    wire [31:0] result_tag;
    wire [2047:0] result_values;

    wire tensor_cfg_valid, tensor_cfg_ready, tensor_out_valid, tensor_out_ready, tensor_out_last;
    wire tensor_done_valid, tensor_done_ready, tensor_done_error;
    wire [31:0] tensor_cfg_tag, native_tensor_out_tag, tensor_done_tag;
    wire [7:0] tensor_cfg_count, tensor_out_count;
    wire [16:0] tensor_cfg_dense_rows;
    wire [2559:0] tensor_cfg_channels, tensor_cfg_keep, tensor_out_channels;
    wire [63:0] tensor_cfg_activation_base, tensor_cfg_weight_base;
    wire [3:0] tensor_out_token;
    wire [5119:0] tensor_out_data;

    wire value_req_valid, value_rsp_ready;
    logic value_pending = 0;
    wire [9:0] value_req_rank;
    logic [9:0] value_rank;

    wire req_valid, rsp_ready;
    logic reading = 0;
    wire [63:0] req_address;
    wire [4:0] req_length;
    logic [63:0] read_address;
    int words_left;
    int cycles = 0, fault = 0, row_id, accepted_values = 0, accepted_scores = 0;
    int expected_selected, key_count, query_position, is_streaming, score_shift, image_start;
    int rows_checked = 0, errors_checked = 0, values_checked = 0, scores_checked = 0, output_stalls = 0;
    logic [511:0] query;
    logic [511:0] keys[1024], values[1024];
    logic [9:0] origins[576], ranks[1024];
    logic [31:0] dots[1024];
    bit selected[1024];
    logic [2047:0] expected_result;
    string fixture_path;

    wire req_ready = !reading && cycles%5!=0;
    wire rsp_valid = reading;
    wire rsp_last = words_left == 1;
    wire rsp_error = fault == 1;
    wire [9:0] read_rank = 10'((read_address-KEY_ADDR)>>6);
    wire [63:0] rsp_data = read_address >= KEY_ADDR ?
        keys[read_rank][int'(read_address[5:3])*64 +: 64] : query[int'(read_address[5:3])*64 +: 64];
    wire value_req_ready = !value_pending && cycles%7!=0;
    wire value_rsp_valid = value_pending;
    wire value_rsp_error = fault == 2 && accepted_values == 3;
    wire [511:0] value_rsp_data = values[value_rank];
    wire [31:0] tensor_out_tag = fault == 4 ? native_tensor_out_tag ^ 32'h40000000 : native_tensor_out_tag;

    tri_oracle_attention_row426 dut (.row_query_addr(QUERY_ADDR), .row_key_base(KEY_ADDR), .*);
    tri_oracle_batched_tensor390 tensor (
        .clk, .rst_n, .cfg_valid(tensor_cfg_valid), .cfg_ready(tensor_cfg_ready),
        .cfg_paired(1'b0), .cfg_tag(tensor_cfg_tag), .cfg_tokens(5'd1), .cfg_feature_words(10'd8),
        .cfg_dense_rows(tensor_cfg_dense_rows), .cfg_count(tensor_cfg_count),
        .cfg_channels(tensor_cfg_channels), .cfg_keep(tensor_cfg_keep),
        .cfg_activation_base(tensor_cfg_activation_base), .cfg_weight_base(tensor_cfg_weight_base),
        .cfg_up_weight_base(64'd0), .cfg_activation_stride(32'd64),
        .out_valid(tensor_out_valid), .out_ready(tensor_out_ready), .out_tag(native_tensor_out_tag),
        .out_token(tensor_out_token), .out_last(tensor_out_last), .out_count(tensor_out_count),
        .out_channels(tensor_out_channels), .out_data(tensor_out_data), .done_valid(tensor_done_valid),
        .done_ready(tensor_done_ready), .done_error(tensor_done_error), .done_tag(tensor_done_tag),
        .req_valid, .req_ready, .req_address, .req_length, .rsp_valid, .rsp_ready, .rsp_last, .rsp_error, .rsp_data
    );

    always @(posedge clk) if (rst_n) begin
        cycles <= cycles+1;
        if (req_valid && req_ready) begin
            if (req_length == 0 || req_address[2:0] != 0 || fault inside {3,5})
                $fatal(1, "ROW426_UNEXPECTED_READ row=%0d", row_id);
            for (int word = 0; word < int'(req_length); word++) begin
                logic [63:0] address;
                address = req_address + 64'(word*8);
                if (address < QUERY_ADDR || (address >= QUERY_ADDR+64 && address < KEY_ADDR) ||
                    address >= KEY_ADDR+64'(key_count*64))
                    $fatal(1, "ROW426_READ_ADDRESS row=%0d address=%h", row_id, address);
                if (address >= KEY_ADDR && !selected[int'((address-KEY_ADDR)>>6)])
                    $fatal(1, "ROW426_SKIPPED_KEY_READ row=%0d address=%h", row_id, address);
            end
            reading <= 1;
            read_address <= req_address;
            words_left <= int'(req_length);
        end else if (rsp_valid && rsp_ready) begin
            reading <= !rsp_last;
            read_address <= read_address+64'd8;
            words_left <= words_left-1;
        end
        if (tensor_out_valid && tensor_out_ready) begin
            for (int lane = 0; lane < int'(tensor_out_count); lane++) begin
                if (accepted_scores >= expected_selected ||
                    tensor_out_channels[lane*16 +: 16] !== 16'(ranks[accepted_scores]) ||
                    tensor_out_data[lane*32 +: 32] !== dots[accepted_scores])
                    $fatal(1, "ROW426_DOT row=%0d lane=%0d index=%0d", row_id, lane, accepted_scores);
                accepted_scores++;
            end
        end
        if (value_req_valid && value_req_ready) begin
            if (fault inside {1,3,4,5} || accepted_values >= expected_selected ||
                value_req_rank !== ranks[accepted_values])
                $fatal(1, "ROW426_VALUE_ORDER row=%0d index=%0d rank=%0d", row_id, accepted_values, value_req_rank);
            value_rank <= value_req_rank;
            value_pending <= 1;
            accepted_values++;
        end else if (value_rsp_valid && value_rsp_ready) value_pending <= 0;
    end

    task automatic load_frame(input bit malformed);
        @(negedge clk);
        frame_image_start = 10'(image_start);
        frame_valid = 1;
        @(posedge clk);
        if (!frame_ready) $fatal(1, "ROW426_FRAME_BUSY");
        @(negedge clk);
        frame_valid = 0;
        map_valid = 1;
        for (int index = 0; index < 576; index++) begin
            map_origin = (malformed && index == 0) ? 10'd1 : origins[index];
            @(posedge clk);
            if (!map_ready || frame_error) $fatal(1, "ROW426_MAP index=%0d", index);
            @(negedge clk);
        end
        map_valid = 0;
        while (!row_ready) @(negedge clk);
        if (frame_error !== malformed) $fatal(1, "ROW426_FRAME_ERROR");
    endtask

    task automatic evaluate_row(input int problem);
        int expected_values, expected_scores;
        @(negedge clk);
        fault = problem;
        accepted_values = 0;
        accepted_scores = 0;
        row_tag = 32'(row_id+32'h42600000+problem);
        row_position = 11'(query_position);
        row_key_count = problem == 3 ? 11'd0 : 11'(key_count);
        row_streaming = is_streaming != 0;
        row_score_shift = 7'(score_shift);
        row_valid = 1;
        @(posedge clk);
        if (!row_ready) $fatal(1, "ROW426_ROW_BUSY");
        @(negedge clk);
        row_valid = 0;
        while (!result_valid) @(negedge clk);
        expected_values = problem == 2 ? 3 : problem == 0 ? expected_selected : 0;
        expected_scores = problem inside {0,2,4} ? expected_selected : 0;
        if (accepted_values != expected_values || accepted_scores != expected_scores || value_pending || reading)
            $fatal(1, "ROW426_INVENTORY row=%0d values=%0d scores=%0d", row_id, accepted_values, accepted_scores);
        repeat (3) begin
            if (!result_valid || result_error !== (problem != 0) || result_tag !== row_tag || row_ready || frame_ready)
                $fatal(1, "ROW426_RESULT_STATUS row=%0d fault=%0d", row_id, problem);
            for (int feature = 0; feature < 64; feature++)
                if (result_values[feature*32 +: 32] !== (problem == 0 ? expected_result[feature*32 +: 32] : 32'd0))
                    $fatal(1, "ROW426_RESULT row=%0d feature=%0d expected=%0d got=%0d",
                           row_id, feature, $signed(expected_result[feature*32 +: 32]),
                           $signed(result_values[feature*32 +: 32]));
            output_stalls++;
            @(negedge clk);
        end
        result_ready = 1;
        @(negedge clk);
        result_ready = 0;
        if (problem == 0) begin
            rows_checked++;
            values_checked += accepted_values;
            scores_checked += accepted_scores;
        end else errors_checked++;
    endtask

    initial begin
        int file;
        if (!$value$plusargs("FIXTURE=%s", fixture_path)) $fatal(1, "ROW426_FIXTURE_REQUIRED");
        file = $fopen(fixture_path, "r");
        if (!file) $fatal(1, "ROW426_FIXTURE_OPEN");
        repeat (4) @(negedge clk);
        rst_n = 1;
        while ($fscanf(file, "%d %d %d %d %d %d %d", row_id, image_start, key_count, query_position,
                       is_streaming, score_shift, expected_selected) == 7) begin
            if ($fscanf(file, "%h %h", query, expected_result) != 2) $fatal(1, "ROW426_FIXTURE_HEADER");
            for (int index = 0; index < 576; index++)
                if ($fscanf(file, "%h", origins[index]) != 1) $fatal(1, "ROW426_FIXTURE_MAP");
            for (int rank = 0; rank < key_count; rank++) begin
                selected[rank] = 0;
                if ($fscanf(file, "%h %h", keys[rank], values[rank]) != 2) $fatal(1, "ROW426_FIXTURE_KV");
            end
            for (int index = 0; index < expected_selected; index++) begin
                if ($fscanf(file, "%h %h", ranks[index], dots[index]) != 2) $fatal(1, "ROW426_FIXTURE_DOT");
                selected[ranks[index]] = 1;
            end
            if (row_id == 0) begin
                load_frame(1);
                evaluate_row(5);
            end
            load_frame(0);
            if (row_id == 0) evaluate_row(3);
            if (expected_selected >= 3 && errors_checked == 2) begin
                evaluate_row(1);
                evaluate_row(2);
                evaluate_row(4);
            end
            evaluate_row(0);
        end
        if (!$feof(file) || rows_checked == 0) $fatal(1, "ROW426_FIXTURE_END");
        $fclose(file);
        $display("ROW426_PASS rows=%0d scores=%0d values=%0d errors=%0d stalls=%0d",
                 rows_checked, scores_checked, values_checked, errors_checked, output_stalls);
        $finish;
    end

    initial begin
        #50000000;
        $fatal(1, "ROW426_TIMEOUT");
    end
endmodule
