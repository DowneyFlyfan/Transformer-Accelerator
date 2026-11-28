`timescale 1ns/1ps
`default_nettype none

// A real broker and compute fabric drive the context spool. Only the tensor
// source and scratch port peers are behavioral. Score/probability/context
// signals are never driven by the reference model.
module tri_oracle_broker_context_spool_tb;
    localparam logic [63:0] SCRATCH = 64'h400, CODES = 64'h4000;
    localparam integer WORDS = 2304;
    localparam integer TRAINED = 0, BAD_V_UNIT = 1, NEGATIVE_UNITS = 2, ALIAS_UNITS = 3;
    logic clk = 0, rst_n = 0, cancel = 0;
    logic cfg_valid = 0, cfg_ready;
    logic [31:0] cfg_streaming, cfg_tag, cfg_heads;
    logic [10:0] cfg_total_keys, cfg_visible_keys;
    logic [223:0] cfg_score_shifts;
    logic [35:0] cfg_value_exponents;
    logic [15:0] cfg_query, cfg_epoch;
    logic [63:0] cfg_spool_base, cfg_code_base;
    logic [287:0] cfg_weight_units, cfg_output_units;

    logic tensor_req_valid, tensor_req_ready, tensor_rsp_valid, tensor_rsp_ready, tensor_rsp_error;
    logic [1:0] tensor_req_kind, tensor_rsp_kind;
    logic [4:0] tensor_req_head, tensor_rsp_head;
    logic [9:0] tensor_req_key, tensor_rsp_key, tensor_rsp_size;
    logic [15:0] tensor_req_query, tensor_req_epoch, tensor_rsp_query, tensor_rsp_epoch;
    logic [31:0] tensor_req_tag, tensor_rsp_tag;
    logic signed [8:0] tensor_rsp_value_exponent;
    logic [511:0] tensor_rsp_data;

    logic fabric_load_valid, fabric_load_error, fabric_cmd_valid, fabric_cmd_ready, fabric_cmd_accumulate;
    logic [4:0] fabric_load_core, fabric_cmd_clusters, fabric_cmd_weight, fabric_cmd_mask;
    logic [4:0] fabric_activation_reloaded, fabric_out_valid, fabric_out_ready;
    logic [1:0] fabric_load_kind, fabric_cmd_reduce;
    logic [9:0] fabric_load_addr, fabric_cmd_activation;
    logic [2047:0] fabric_load_data;
    logic [31:0] fabric_load_rows;
    logic [3:0] fabric_cmd_output;
    logic [2:0] fabric_core_select;
    logic [19:0] fabric_out_slot;
    logic [5119:0] fabric_out_data;
    tri_oracle_wac_softmax_types::request_t softmax_request;
    tri_oracle_wac_softmax_types::response_t softmax_response;

    logic done_valid, done_ready = 0, done_error, reset_required, busy, cfg_error, all_contexts_collected;
    logic [7:0] error_code;
    logic [31:0] done_tag;
    logic [15:0] done_query, done_epoch;
    logic signed [9:0] done_unit;
    logic wr_req_valid, wr_req_ready, wr_data_valid, wr_data_ready, wr_last;
    logic wr_rsp_valid, wr_rsp_ready, wr_error;
    logic [63:0] wr_address, wr_data, rd_address, rd_data;
    logic [4:0] wr_length, rd_length;
    logic rd_req_valid, rd_req_ready, rd_rsp_valid, rd_rsp_ready, rd_last, rd_error;

    tri_oracle_broker_context_spool dut (.*);
    tri_oracle_compute_fabric #(
        .AGGREGATOR_SIGN_BANK(1), .AGGREGATOR_MERGE_TABLE(1), .LOCAL_TOKEN_SIZES(1),
        .LOCAL_TOKEN_MERGE(1), .CORE_STRIP_PREDICTOR(1), .CORE_HEAD_PREDICTOR(1)
    ) fabric (
        .clk, .rst_n, .load_valid(fabric_load_valid), .load_core(fabric_load_core),
        .load_kind(fabric_load_kind), .load_addr(fabric_load_addr), .load_data(fabric_load_data),
        .load_row_enable(fabric_load_rows), .load_error(fabric_load_error),
        .cmd_valid(fabric_cmd_valid), .cmd_ready(fabric_cmd_ready), .cmd_clusters(fabric_cmd_clusters),
        .cmd_weight(fabric_cmd_weight), .cmd_mask(fabric_cmd_mask), .cmd_activation(fabric_cmd_activation),
        .cmd_output(fabric_cmd_output), .cmd_accumulate(fabric_cmd_accumulate), .cmd_reduce(fabric_cmd_reduce),
        .core_score_select(fabric_core_select), .activation_reloaded(fabric_activation_reloaded),
        .out_valid(fabric_out_valid), .out_ready(fabric_out_ready), .out_output(fabric_out_slot),
        .out_data(fabric_out_data), .softmax_request, .softmax_response,
        .merge_sign_data('0), .merge_sign_control('0), .merge_sign_counts(),
        .merge_table_request('0), .merge_table_word(), .token_sizes_request('0), .token_sizes_response(),
        .merge_request('0), .merge_response(), .strip_rst_n(rst_n), .strip_request('0), .strip_response(),
        .head_request('0), .head_response()
    );

    string trained_dir;
    logic [511:0] trained_q[32], trained_k[8], trained_v[8];
    logic [2047:0] trained_gold[32];
    logic [287:0] trained_cfg[6];
    logic [7:0] trained_codes[2048];
    integer scenario, cycles, expected_unit, expected_keys;
    logic [35:0] expected_units;
    logic [31:0] expected_tag;
    logic [15:0] expected_query, expected_epoch;
    logic [63:0] memory[WORDS], pending_words[16];
    bit written[WORDS];
    bit tensor_pending, injected, writing, acknowledging, reading;
    integer tensor_delay, write_base, write_len, write_index, write_delay;
    integer read_base, read_len, read_index, read_delay, output_words;
    integer read_bursts, write_bursts, probabilities, request_stalls, data_stalls, accepted_values;
    bit saw_value[32][2];

    always #5 clk = ~clk;
    task automatic check(input logic cond, input string msg);
        if (cond !== 1'b1)
            $fatal(1, "BROKER_CONTEXT_ASSERT case=%0d cycle=%0d %s", scenario, cycles, msg);
    endtask

    // Multiples of eight keep every signed right shift exact, and magnitude
    // 64 in every group establishes a unique maximum row unit.
    function automatic int v_code(input int group_id, lane);
        if (lane % 8 == 0) return group_id % 2 == 0 ? 64 : -64;
        return 8 * (((group_id * 3 + lane) % 15) - 7);
    endfunction
    function automatic logic [511:0] tensor_word(input int kind, head, key_id);
        logic [511:0] word_out;
        if (scenario == TRAINED) begin
            case (kind)
                0: return trained_q[head];
                1: return trained_k[2*(head/8)+key_id];
                2: return trained_v[2*(head/8)+key_id];
                default: return 'x;
            endcase
        end
        word_out = '0;
        if (kind == 2)
            for (int lane = 0; lane < 64; lane++)
                word_out[8*lane+:8] = 8'(v_code(head/8, lane));
        return word_out;
    endfunction

    assign tensor_req_ready = rst_n && !tensor_pending && !tensor_rsp_valid && cycles % 5 != 1;
    always @(posedge clk) begin
        if (!rst_n) begin
            cycles <= 0;
            tensor_rsp_valid <= 0;
            tensor_pending <= 0;
            tensor_rsp_error <= 0;
            injected <= 0;
            probabilities <= 0;
            accepted_values <= 0;
            foreach (saw_value[h,k]) saw_value[h][k] <= 0;
        end else begin
            cycles <= cycles + 1;
            if (softmax_response.out_valid && softmax_request.out_ready)
                probabilities <= probabilities + 1;
            if (tensor_req_valid && tensor_req_ready) begin
                check(tensor_req_kind inside {0,1,2}, "unknown tensor kind");
                check(tensor_req_tag === expected_tag && tensor_req_epoch === expected_epoch &&
                      tensor_req_query === expected_query, "tensor request metadata changed");
                check(!$isunknown({tensor_req_head,tensor_req_key}) && int'(tensor_req_key) < expected_keys,
                      "tensor request index out of bounds");
                if (tensor_req_kind == 2) begin
                    check(!saw_value[tensor_req_head][tensor_req_key], "duplicate value read");
                    saw_value[tensor_req_head][tensor_req_key] <= 1;
                    accepted_values <= accepted_values + 1;
                end
                tensor_rsp_kind <= tensor_req_kind;
                tensor_rsp_head <= tensor_req_head;
                tensor_rsp_key <= tensor_req_key;
                tensor_rsp_query <= tensor_req_query;
                tensor_rsp_epoch <= tensor_req_epoch;
                tensor_rsp_tag <= tensor_req_tag;
                tensor_rsp_size <= 1;
                tensor_rsp_data <= tensor_word(int'(tensor_req_kind),int'(tensor_req_head),int'(tensor_req_key));
                tensor_rsp_value_exponent <= expected_units[9*tensor_req_head[4:3]+:9];
                if (scenario == BAD_V_UNIT && tensor_req_kind == 2 && !injected) begin
                    tensor_rsp_value_exponent <= expected_units[9*tensor_req_head[4:3]+:9] ^ 9'h100;
                    injected <= 1;
                end
                tensor_delay <= 1 + cycles % 3;
                tensor_pending <= 1;
            end
            if (tensor_pending) begin
                if (tensor_delay == 0) begin
                    tensor_pending <= 0;
                    tensor_rsp_valid <= 1;
                end else tensor_delay <= tensor_delay - 1;
            end
            if (tensor_rsp_valid && tensor_rsp_ready) tensor_rsp_valid <= 0;
        end
    end

    assign wr_req_ready = rst_n && !writing && !acknowledging && cycles % 5 != 0;
    assign wr_data_ready = rst_n && writing && cycles % 4 != 0;
    assign wr_rsp_valid = rst_n && acknowledging && write_delay == 0;
    assign wr_error = 0;
    assign rd_req_ready = rst_n && !reading && cycles % 4 != 2;
    assign rd_rsp_valid = rst_n && reading && read_delay == 0;
    assign rd_data = reading ? memory[read_base+read_index] : '0;
    assign rd_last = reading && read_index == read_len-1;
    assign rd_error = 0;

    function automatic bit valid_burst(input logic [63:0] address, input logic [4:0] length,
                                       input bit is_write);
        if ($isunknown({address,length}) || address[2:0] != 0) return 0;
        if (address >= SCRATCH && address < SCRATCH+8192)
            return address[6:0] == 0 && length == 16;
        if (address >= SCRATCH+8192 && address < SCRATCH+8448) return length == 1;
        if (address >= CODES && address < CODES+2048)
            return is_write && address[4:0] == 0 && length == 4;
        return 0;
    endfunction

    always @(posedge clk) begin
        if (!rst_n) begin
            writing <= 0; acknowledging <= 0; reading <= 0;
            write_bursts <= 0; read_bursts <= 0; output_words <= 0;
            request_stalls <= 0; data_stalls <= 0;
            foreach (written[w]) written[w] <= 0;
        end else begin
            if (wr_req_valid && !wr_req_ready) request_stalls <= request_stalls + 1;
            if (wr_data_valid && !wr_data_ready) data_stalls <= data_stalls + 1;
            if (wr_req_valid && wr_req_ready) begin
                check(valid_burst(wr_address,wr_length,1), "invalid write burst");
                writing <= 1; write_base <= int'(wr_address >> 3); write_len <= int'(wr_length);
                write_index <= 0; write_bursts <= write_bursts + 1;
            end
            if (wr_data_valid && wr_data_ready) begin
                check(!$isunknown(wr_data) && wr_last === (write_index == write_len-1), "invalid write beat");
                pending_words[write_index] <= wr_data;
                if (wr_last) begin
                    writing <= 0; acknowledging <= 1; write_delay <= 2;
                end else write_index <= write_index + 1;
            end
            if (acknowledging && write_delay > 0) write_delay <= write_delay - 1;
            if (wr_rsp_valid && wr_rsp_ready) begin
                for (int j = 0; j < write_len; j++) begin
                    check(!written[write_base+j], "duplicate scratch or context write");
                    memory[write_base+j] <= pending_words[j];
                    written[write_base+j] <= 1;
                end
                if (write_base >= int'(CODES>>3)) output_words <= output_words+write_len;
                acknowledging <= 0;
            end
            if (rd_req_valid && rd_req_ready) begin
                check(valid_burst(rd_address,rd_length,0), "invalid read burst");
                read_base <= int'(rd_address >> 3); read_len <= int'(rd_length);
                read_index <= 0; reading <= 1; read_delay <= 2; read_bursts <= read_bursts + 1;
            end
            if (reading && read_delay > 0) read_delay <= read_delay - 1;
            if (rd_rsp_valid && rd_rsp_ready) begin
                check(written[read_base+read_index], "read before write acknowledgement");
                if (rd_last) reading <= 0;
                else begin read_index <= read_index + 1; read_delay <= cycles % 3; end
            end
        end
    end

    task automatic check_row;
        integer raw_word, unit_word, code_word, group_id;
        logic [31:0] raw_ref;
        logic [7:0] code_ref;
        for (int h = 0; h < 32; h++) begin
            group_id = h/8;
            unit_word = int'(SCRATCH >> 3) + 1024 + h;
            check(written[unit_word] && memory[unit_word] === {55'd0,expected_units[9*group_id+:9]},
                  $sformatf("stored signed nine-bit value unit, head %0d", h));
            for (int k = 0; k < expected_keys; k++)
                check(saw_value[h][k], "missing accepted value tensor");
            for (int lane = 0; lane < 64; lane++) begin
                raw_word = int'(SCRATCH >> 3) + 32*h + lane/2;
                code_word = int'(CODES >> 3) + 8*h + lane/8;
                if (scenario == TRAINED) begin
                    raw_ref = trained_gold[h][32*lane+:32];
                    code_ref = trained_codes[64*h+lane];
                end else begin
                    // With one visible key, p=65535. Group units differ
                    // by exactly one bit per group; every division is exact.
                    raw_ref = 32'(65535 * v_code(group_id,lane));
                    code_ref = 8'(v_code(group_id,lane) / (1 << (3-group_id)));
                end
                check(written[raw_word] && memory[raw_word][32*(lane%2)+:32] === raw_ref,
                      $sformatf("accumulator mismatched at head=%0d lane=%0d",h,lane));
                check(written[code_word] && memory[code_word][8*(lane%8)+:8] === code_ref,
                      $sformatf("context code mismatched at head=%0d lane=%0d",h,lane));
            end
        end
        check(done_unit === 10'(expected_unit), "wrong signed common row unit");
        check(write_bursts == 160 && read_bursts == 96 && output_words == 256,
              "wrong write/read burst count or output extent");
        check(probabilities == 32*expected_keys && accepted_values == 32*expected_keys,
              "incomplete normalization or accepted value traversal");
        check(request_stalls > 0 && data_stalls > 0, "memory stalls did not exercise valid/ready");
    endtask

    task automatic run_case(input integer test_id);
        integer group_zero;
        logic [74:0] held_terminal;
        // The underlying broker requires a coordinated reset after failure.
        @(negedge clk);
        rst_n = 0; cfg_valid = 0; done_ready = 0; scenario = test_id;
        repeat (3) @(negedge clk);
        expected_tag = 32'h8d2c0000 + 32'(test_id);
        expected_epoch = 16'h42f1;
        expected_query = (test_id == TRAINED) ? 1 : 0;
        expected_keys = (test_id == TRAINED) ? 2 : 1;
        cfg_tag = expected_tag; cfg_epoch = expected_epoch; cfg_query = expected_query;
        cfg_heads = '1; cfg_spool_base = SCRATCH; cfg_code_base = CODES;
        cfg_total_keys = test_id == TRAINED ? 11'd281 : 11'd1;
        cfg_visible_keys = 11'(expected_keys);
        if (test_id == TRAINED) begin
            cfg_streaming = trained_cfg[0][31:0];
            cfg_score_shifts = trained_cfg[1][223:0];
            cfg_value_exponents = trained_cfg[2][35:0];
            cfg_weight_units = trained_cfg[3];
            cfg_output_units = trained_cfg[4];
            expected_unit = int'($signed(trained_cfg[5][9:0]));
        end else begin
            cfg_streaming = '0; cfg_score_shifts = '0;
            group_zero = test_id == ALIAS_UNITS ? 56 : -200;
            expected_unit = group_zero+3;
            for (int g = 0; g < 4; g++) cfg_value_exponents[9*g+:9] = 9'(group_zero+g);
            cfg_weight_units = '0;
            for (int h = 0; h < 32; h++) cfg_output_units[9*h+:9] = 9'(expected_unit+16);
        end
        expected_units = cfg_value_exponents;
        rst_n = 1;
        @(negedge clk);
        cfg_valid = 1;
        do @(posedge clk); while (cfg_ready !== 1'b1);
        @(negedge clk);
        cfg_valid = 0;
        // Force the wrapper to keep its admitted metadata across both waves.
        cfg_heads = 'x; cfg_value_exponents = 'x; cfg_output_units = 'x; cfg_weight_units = 'x;
        cfg_tag = 'x; cfg_query = 'x; cfg_epoch = 'x;
        cfg_total_keys = 'x; cfg_visible_keys = 'x; cfg_streaming = 'x; cfg_score_shifts = 'x;
        cfg_spool_base = 'x; cfg_code_base = 'x;

        do @(negedge clk); while (done_valid !== 1'b1);
        check(done_tag === expected_tag && done_query === expected_query && done_epoch === expected_epoch,
              "completion returned wrong frame");
        check(done_error === (test_id == BAD_V_UNIT), "unexpected terminal outcome");
        check(!tensor_pending && !tensor_rsp_valid && !writing && !acknowledging && !reading,
              "terminal arrived before all outstanding responses drained");
        if (test_id == BAD_V_UNIT) begin
            check(injected && accepted_values > 0, "high-bit rejection never exercised");
            check(error_code === 8'h31 && reset_required, "wrong high-bit mismatch diagnosis");
            check(output_words == 0 && read_bursts == 0, "rejected unit reached output conversion");
        end else check_row();
        held_terminal = {done_error,done_tag,done_query,done_epoch,done_unit};
        repeat (4) begin
            @(negedge clk);
            check(done_valid && {done_error,done_tag,done_query,done_epoch,done_unit} === held_terminal,
                  "terminal changed under backpressure");
        end
        done_ready = 1;
        @(negedge clk);
        done_ready = 0;
        $display("BROKER_CONTEXT_CASE_PASS case=%0d keys=%0d value_requests=%0d probabilities=%0d output_bytes=%0d common_unit=%0d injected=%0d",
                 test_id, expected_keys, accepted_values, probabilities, output_words*8,
                 $signed(held_terminal[9:0]), injected);
    endtask

    initial begin
        if (!$value$plusargs("TRAINED=%s",trained_dir)) $fatal(1, "+TRAINED=<fixture directory> required");
        $readmemh({trained_dir,"/trained32_q.hex"}, trained_q);
        $readmemh({trained_dir,"/trained32_k.hex"}, trained_k);
        $readmemh({trained_dir,"/trained32_v.hex"}, trained_v);
        $readmemh({trained_dir,"/trained32_gold.hex"}, trained_gold);
        $readmemh({trained_dir,"/cfg.hex"}, trained_cfg);
        $readmemh({trained_dir,"/codes.hex"}, trained_codes);
        foreach (trained_q[h]) check(!$isunknown(trained_q[h]) && !$isunknown(trained_gold[h]), "missing trained row");
        foreach (trained_k[k]) check(!$isunknown(trained_k[k]) && !$isunknown(trained_v[k]), "missing tensor vector");
        foreach (trained_cfg[i]) check(!$isunknown(trained_cfg[i]), "missing trained configuration");
        foreach (trained_codes[i]) check(!$isunknown(trained_codes[i]), "missing expected context byte");
        run_case(TRAINED);
        run_case(BAD_V_UNIT);
        run_case(NEGATIVE_UNITS);
        run_case(ALIAS_UNITS);
        $display("BROKER_CONTEXT_SPOOL_PASS cases=4 trained_rows=1 alias_rows=2 rejected=1");
        $finish;
    end
    initial begin
        #30ms;
        $fatal(1, "BROKER_CONTEXT_SPOOL_TIMEOUT case=%0d cycles=%0d", scenario, cycles);
    end
endmodule
`default_nettype wire
