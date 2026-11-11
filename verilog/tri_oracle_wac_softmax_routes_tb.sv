`timescale 1ns/1ps
module tri_oracle_wac_softmax_routes_tb;
    import tri_oracle_wac_softmax_types::*;

    logic clk = 0, rst_n = 0;
    request_t request = '0;
    response_t response;
    always #5 clk = ~clk;

    tri_oracle_compute_fabric #(
        .AGGREGATOR_SIGN_BANK(1), .AGGREGATOR_MERGE_TABLE(1), .LOCAL_TOKEN_SIZES(1),
        .LOCAL_TOKEN_MERGE(1), .CORE_STRIP_PREDICTOR(1), .CORE_HEAD_PREDICTOR(1)
    ) fabric (
        .clk, .rst_n, .load_valid(1'b0), .load_core('0), .load_kind('0), .load_addr('0),
        .load_data('0), .load_row_enable('0), .load_error(), .cmd_valid(1'b0), .cmd_ready(),
        .cmd_clusters('0), .cmd_weight('0), .cmd_mask('0), .cmd_activation('0), .cmd_output('0),
        .cmd_accumulate(1'b0), .cmd_reduce('0), .out_valid(), .out_ready('0), .out_output(), .out_data(),
        .merge_sign_data('0), .merge_sign_control('0), .merge_sign_counts(), .merge_table_request('0),
        .merge_table_word(), .activation_reloaded(1'b0), .softmax_request(request), .softmax_response(response),
        .token_sizes_request('0), .token_sizes_response(), .merge_request('0), .merge_response(),
        .strip_rst_n(rst_n), .strip_request('0), .strip_response(), .head_request('0), .head_response()
    );

    task automatic replay_head(input int head);
        int length;
        longint unsigned denominator, reciprocal, numerator;
        logic [15:0] expected;
        length = head + 1;
        denominator = 64'(length) << 20;
        reciprocal = (64'd1 << 48) / denominator;
        numerator = (reciprocal << 20) * 64'd65535 + (64'd1 << 47);
        expected = 16'(numerator >> 48);
        request.owner = core_owner(5'(head));
        request.cfg_length = 11'(length);
        request.cfg_valid = 1;
        @(posedge clk);
        if (response.cfg_ready !== 1'b1) $fatal(1, "WAC_ROUTE_CONFIG head=%0d", head);
        @(negedge clk);
        request.cfg_valid = 0;
        request.in_valid = 1;
        request.size = 1;
        for (int key = 0; key < length; key++) begin
            @(posedge clk);
            if (response.in_ready !== 1'b1 || response.cfg_error)
                $fatal(1, "WAC_ROUTE_LOAD head=%0d key=%0d", head, key);
            @(negedge clk);
        end
        request.in_valid = 0;
        for (int key = 0; key < length; key++) begin
            do @(negedge clk); while (response.out_valid !== 1'b1);
            if (key == 0) repeat (3) begin
                @(posedge clk);
                if (response.out_valid !== 1'b1 || response.probability !== expected)
                    $fatal(1, "WAC_ROUTE_STALL head=%0d", head);
                @(negedge clk);
            end
            request.out_ready = 1;
            @(posedge clk);
            if (response.probability !== expected || response.out_last !== (key == length-1))
                $fatal(1, "WAC_ROUTE_RESULT head=%0d key=%0d", head, key);
            @(negedge clk);
            request.out_ready = 0;
        end
    endtask

    initial begin
        repeat (2) @(negedge clk);
        rst_n = 1;
        for (int invalid = 20; invalid < 32; invalid++) begin
            request.owner = 5'(invalid);
            request.cfg_valid = 1;
            request.cfg_length = 1;
            @(posedge clk);
            if (response !== '0) $fatal(1, "WAC_ROUTE_INVALID_DESTINATION owner=%0d", invalid);
            @(negedge clk);
        end
        request = '0;
        for (int head = 0; head < 32; head++) replay_head(head);
        $display("WAC_ROUTES_PASS heads=32 probabilities=528 invalid_destinations=12");
        $finish;
    end

    initial begin
        #100000;
        $fatal(1, "WAC_ROUTE_WATCHDOG");
    end
endmodule

module tri_oracle_wac_softmax_route_witness (
    input logic clk, rst_n, cfg_valid, cfg_ready,
    input logic [10:0] cfg_length
);
    always @(posedge clk) if (rst_n && cfg_valid && cfg_ready)
        $display("WAC_ROUTE_TRANSFER %m length=%0d", cfg_length);
endmodule
bind tri_oracle_wac_softmax tri_oracle_wac_softmax_route_witness route_witness (.*);
