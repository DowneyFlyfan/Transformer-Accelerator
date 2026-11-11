`timescale 1ns/1ps
module tri_oracle_cluster_local_tensor_tb;
    import tri_oracle_wac_softmax_types::*;

    localparam logic [63:0] QUERY = 64'h1000;
    localparam logic [63:0] KEYS = 64'h2000;
    logic clk = 0, rst_n = 0, cfg_valid = 0, cfg_ready;
    logic [31:0] cfg_tag = 0, out_tag, done_tag;
    logic [7:0] cfg_count = 0, out_count;
    logic [2559:0] cfg_channels = '0, out_channels;
    request_t softmax_request = '0;
    logic out_valid, out_ready = 0, out_last, done_valid, done_ready = 0, done_error;
    logic [5119:0] out_data;
    logic req_valid, req_ready, rsp_valid, rsp_ready, rsp_last;
    logic [63:0] req_address, read_address, rsp_data;
    logic [4:0] req_length, remaining = 0;
    int selected = 0;
    int query_reads, key_reads;
    int issues[5];
    always #5 clk = ~clk;

    tri_oracle_batched_tensor390 #(
        .AGGREGATOR_SIGN_BANK(1), .AGGREGATOR_MERGE_TABLE(1), .LOCAL_TOKEN_SIZES(1),
        .LOCAL_TOKEN_MERGE(1), .CORE_STRIP_PREDICTOR(1), .CORE_HEAD_PREDICTOR(1)
    ) dut (
        .clk, .rst_n, .cfg_valid, .cfg_ready, .cfg_tag, .cfg_count, .cfg_channels,
        .cfg_paired(1'b0), .cfg_tokens(5'd1), .cfg_feature_words(10'd8), .cfg_dense_rows(17'd32),
        .cfg_keep('1), .cfg_activation_base(QUERY), .cfg_weight_base(KEYS), .cfg_up_weight_base('0),
        .cfg_activation_stride(32'd64), .out_valid, .out_ready, .out_tag, .out_token(),
        .out_last, .out_count, .out_channels, .out_data, .done_valid, .done_ready, .done_error, .done_tag,
        .req_valid, .req_ready, .req_address, .req_length, .rsp_valid, .rsp_ready, .rsp_last,
        .rsp_error(1'b0), .rsp_data, .merge_sign_data('0), .merge_sign_control('0), .merge_sign_counts(),
        .merge_table_request('0), .merge_table_word(), .softmax_request, .softmax_response(),
        .token_sizes_request('0), .token_sizes_response(), .merge_request('0), .merge_response(),
        .strip_request('0), .strip_response(), .head_request('0), .head_response()
    );

    function automatic int activation(input int feature);
        return (feature % 7) - 3;
    endfunction
    function automatic int weight(input int channel, feature);
        return ((3*channel + feature) % 11) - 5;
    endfunction
    function automatic int dot(input int channel);
        int sum = 0;
        for (int feature = 0; feature < 64; feature++)
            sum += activation(feature)*weight(channel, feature);
        return sum;
    endfunction

    assign req_ready = remaining == 0;
    assign rsp_valid = remaining != 0;
    assign rsp_last = remaining == 1;
    always_comb begin
        rsp_data = '0;
        for (int lane = 0; lane < 8; lane++) begin
            if (read_address >= QUERY && read_address < QUERY + 64)
                rsp_data[8*lane+:8] = 8'(activation(int'(read_address - QUERY) + lane));
            else if (read_address >= KEYS && read_address < KEYS + 2048)
                rsp_data[8*lane+:8] = 8'(weight(int'((read_address - KEYS) >> 6),
                                                   int'((read_address - KEYS) & 63) + lane));
        end
    end
    always @(posedge clk) if (rst_n) begin
        if (req_valid && req_ready) begin
            if (req_length == 0 || !((req_address >= QUERY && req_address < QUERY + 64) ||
                  (req_address >= KEYS && req_address < KEYS + 2048)))
                $fatal(1, "CLUSTER_TENSOR_MEMORY_ADDRESS");
            if (req_address < KEYS) query_reads++;
            else key_reads++;
            remaining <= req_length;
            read_address <= req_address;
        end else if (rsp_valid && rsp_ready) begin
            remaining <= remaining - 1'b1;
            read_address <= read_address + 8;
        end
    end

    for (genvar cluster = 0; cluster < 5; cluster++) begin : physical_cluster
        always @(posedge clk) if (rst_n && dut.fabric.clusters[cluster].unit.cmd_valid) begin
            if (selected != cluster) $fatal(1, "CLUSTER_TENSOR_REMOTE_COMMAND");
            issues[cluster]++;
        end
    end

    initial begin
        for (int cluster = 0; cluster < 5; cluster++) issues[cluster] = 0;
        for (int lane = 0; lane < 32; lane++) cfg_channels[lane*16+:16] = 16'(31-lane);
        repeat (2) @(negedge clk);
        rst_n = 1;
        for (int cluster = 0; cluster < 5; cluster++) begin
            selected = cluster;
            query_reads = 0;
            key_reads = 0;
            cfg_tag = 32'h5000 + 32'(cluster);
            cfg_count = cluster == 4 ? 8'd32 : 8'(cluster+1);
            softmax_request.score_tile = 1;
            softmax_request.owner = 5'(cluster*4+3);
            cfg_valid = 1;
            @(posedge clk);
            if (!cfg_ready) $fatal(1, "CLUSTER_TENSOR_CONFIG");
            @(negedge clk);
            cfg_valid = 0;
            softmax_request = '0;
            do @(negedge clk); while (!out_valid && !done_valid);
            if (!out_valid || !out_last || out_tag !== cfg_tag || out_count !== cfg_count ||
                out_channels !== cfg_channels || out_data[5119:1024] !== '0)
                $fatal(1, "CLUSTER_TENSOR_OUTPUT_DESCRIPTOR");
            for (int lane = 0; lane < 32; lane++) begin
                if ($signed(out_data[lane*32+:32]) !== (lane < int'(cfg_count) ? dot(31-lane) : 0))
                    $fatal(1, "CLUSTER_TENSOR_SCORE cluster=%0d lane=%0d", cluster, lane);
            end
            out_ready = 1;
            @(negedge clk);
            out_ready = 0;
            while (!done_valid) @(negedge clk);
            if (done_error || done_tag !== cfg_tag || issues[cluster] != 2)
                $fatal(1, "CLUSTER_TENSOR_DONE cluster=%0d issues=%0d", cluster, issues[cluster]);
            if (query_reads != 4 || key_reads != 4 * int'(cfg_count))
                $fatal(1, "CLUSTER_TENSOR_READS query=%0d keys=%0d", query_reads, key_reads);
            done_ready = 1;
            @(negedge clk);
            done_ready = 0;
        end
        $display("CLUSTER_TENSOR_PASS clusters=5 score_outputs=42 matrix_commands=10");
        $finish;
    end

    initial begin
        #250000;
        $fatal(1, "CLUSTER_TENSOR_WATCHDOG");
    end
endmodule
