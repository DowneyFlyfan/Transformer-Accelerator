`timescale 1ns/1ps
module tri_oracle_residual_fabric_tb;
    logic clk = 0, rst_n = 0;
    always #5 clk = ~clk;

    logic load_valid = 0, load_error;
    logic [4:0] load_core;
    logic [1:0] load_kind;
    logic [9:0] load_addr;
    logic [2047:0] load_data;
    logic cmd_valid = 0, cmd_ready;
    logic [9:0] cmd_activation;
    logic [3:0] cmd_output;
    logic [4:0] matrix_valid;
    logic [19:0] matrix_slots;
    logic [5119:0] matrix_data;

    logic reserved = 0, load_residual = 0, bank_ce_n, bank_we_n, req_ready;
    logic [8:0] load_row, bank_addr;
    logic [255:0] bank_d, bank_q;
    logic bypass_valid, bypass_ready;
    logic [231:0] bypass_data;
    logic in_valid = 0, in_ready, in_last;
    logic [3:0] in_token;
    logic [15:0] in_start;
    logic [7:0] in_count;
    logic [5119:0] in_data;
    logic out_valid, out_ready = 0, out_last;
    logic [31:0] out_tag;
    logic [3:0] out_token;
    logic [15:0] out_start;
    logic [3:0] out_count;
    logic [127:0] out_data;

    logic [620:0] trained [512];
    string fixture;
    int strips = 0, packets = 0, matrix_commands = 0, overlap_commands = 0;
    int matrix_results [5];
    int input_macros = 0;

    tri_oracle_residual_compute_fabric fabric (
        .clk, .rst_n, .load_valid, .load_core, .load_kind, .load_addr, .load_data,
        .load_row_enable(32'hffffffff), .load_error,
        .cmd_valid, .cmd_ready, .cmd_clusters(5'b11111), .cmd_weight(5'd0),
        .cmd_mask(5'd0), .cmd_activation, .cmd_output, .cmd_accumulate(1'b0), .cmd_reduce(2'd0),
        .out_valid(matrix_valid), .out_ready(5'b11111), .out_output(matrix_slots), .out_data(matrix_data),
        .merge_sign_data('0), .merge_sign_control('0), .merge_sign_counts(),
        .merge_table_request('0), .merge_table_word(), .strip_rst_n(rst_n),
        .strip_request('0), .strip_response(), .head_request('0), .head_response(),
        .residual_reserved(reserved), .residual_ce_n(bank_ce_n), .residual_we_n(bank_we_n),
        .residual_addr(bank_addr), .residual_d(bank_d), .residual_q(bank_q)
    );
    tri_oracle_residual_bank_adapter memory_adapter (
        .clk, .rst_n, .lease_granted(reserved), .req_valid(load_residual || in_valid),
        .req_write(load_residual), .req_token(load_residual ? load_row[8] : in_token[0]),
        .req_strip(load_residual ? load_row[7:0] : out_start[10:3]),
        .req_data(trained[load_row][231:0]), .req_ready,
        .rsp_valid(bypass_valid), .rsp_ready(bypass_ready), .rsp_data(bypass_data),
        .bank_ce_n, .bank_we_n, .bank_addr, .bank_d, .bank_q
    );
    tri_oracle_decoder_writeback_bridge writeback (
        .clk, .rst_n, .in_valid, .in_ready, .in_tag(32'h10), .in_token, .in_start,
        .in_count, .in_last, .in_data, .bypass_valid, .bypass_ready, .bypass_data,
        .down_shift(5'd11), .out_valid, .out_ready, .out_tag, .out_token, .out_start,
        .out_count, .out_last, .out_data
    );

    always @(posedge clk) if (rst_n) begin
        if (out_valid && out_ready) strips++;
        if (in_valid && in_ready) packets++;
        if (cmd_valid && cmd_ready) begin
            matrix_commands++;
            if (!bank_ce_n && bank_we_n) overlap_commands++;
        end
        for (int cluster = 0; cluster < 5; cluster++)
            if (matrix_valid[cluster]) begin
                int expected;
                expected = 16 * (16*cluster+10) * (matrix_results[cluster]+1);
                if (matrix_slots[4*cluster +: 4] !== 4'(matrix_results[cluster]) ||
                    matrix_data[1024*cluster +: 1024] !== {32{32'(expected)}})
                    $fatal(1, "RESIDUAL_FABRIC_MATRIX cluster=%0d slot=%0d got=%h expected=%d",
                           cluster, matrix_results[cluster], matrix_data[1024*cluster +: 32], expected);
                matrix_results[cluster]++;
            end
    end

    task automatic load_core_word(input int core, kind, address, input logic [2047:0] data);
        load_core = 5'(core);
        load_kind = 2'(kind);
        load_addr = 10'(address);
        load_data = data;
        load_valid = 1;
        @(negedge clk);
        if (load_error) $fatal(1, "RESIDUAL_FABRIC_LOAD core=%0d addr=%0d", core, address);
        load_valid = 0;
    endtask

    task automatic send_tile(input int token, start, count, input bit last);
        @(negedge clk);
        in_token = 4'(token);
        in_start = 16'(start);
        in_count = 8'(count);
        in_last = last;
        in_data = '0;
        for (int lane = 0; lane < count; lane++)
            in_data[32*lane +: 32] = trained[256*token + (start+lane)/8][232+32*(lane%8) +: 32];
        in_valid = 1;
        for (int offset = 0; offset < count; offset += 8) begin
            int row, issue_slot;
            logic [184:0] expected;
            row = 256*token + (start+offset)/8;
            issue_slot = offset/8;
            expected = {32'h10, 4'(token), 16'(start+offset), 4'd8,
                        1'(last && offset+8==count), trained[row][620:493]};
            cmd_valid = start == 0 && token == 0 && issue_slot < 16;
            cmd_activation = 10'(496+issue_slot);
            cmd_output = 4'(issue_slot);
            @(posedge clk);
            if (!req_ready || bank_ce_n || !bank_we_n || out_valid || (cmd_valid && !cmd_ready))
                $fatal(1, "RESIDUAL_FABRIC_READ_OR_COMMAND row=%0d", row);
            @(negedge clk);
            cmd_valid = 0;
            repeat (2) begin
                @(posedge clk);
                if (!bypass_valid || bypass_data !== trained[row][231:0])
                    $fatal(1, "RESIDUAL_FABRIC_BYPASS row=%0d", row);
                if (!out_valid || !bank_ce_n || in_ready ||
                    {out_tag, out_token, out_start, out_count, out_last, out_data} !== expected)
                    $fatal(1, "RESIDUAL_FABRIC_STALLED_OUTPUT row=%0d", row);
            end
            @(negedge clk);
            out_ready = 1;
            @(posedge clk);
            if (!out_valid || in_ready !== (offset+8==count) ||
                {out_tag, out_token, out_start, out_count, out_last, out_data} !== expected)
                $fatal(1, "RESIDUAL_FABRIC_RETIRED_OUTPUT row=%0d", row);
            @(negedge clk);
            out_ready = 0;
        end
        in_valid = 0;
    endtask

    initial begin
        if (!$value$plusargs("TRAINED=%s", fixture)) $fatal(1, "Missing trained vectors");
        $readmemh(fixture, trained);
        for (int row = 0; row < 512; row++)
            if (trained[row][492:488] !== 5'd11) $fatal(1, "Unknown shift for row %0d", row);
        repeat (3) @(negedge clk);
        if (input_macros != 40) $fatal(1, "RESIDUAL_FABRIC_INPUT_MACROS count=%0d", input_macros);
        rst_n = 1;
        for (int core = 0; core < 20; core++) begin
            load_core_word(core, 0, 0, {256{8'(core+1)}});
            load_core_word(core, 2, 0, {1792'd0, {256{1'b1}}});
            for (int slot = 0; slot < 16; slot++)
                load_core_word(core, 1, 496+slot, {1984'd0, {8{8'(2*(slot+1))}}});
        end
        reserved = 1;
        load_residual = 1;
        for (int row = 0; row < 512; row++) begin
            load_row = 9'(row);
            @(posedge clk);
            if (!req_ready || bank_ce_n || bank_we_n)
                $fatal(1, "RESIDUAL_FABRIC_FILL row=%0d", row);
            @(negedge clk);
        end
        load_residual = 0;
        for (int start = 0; start < 2048; start += 160)
            for (int token = 0; token < 2; token++)
                send_tile(token, start, start < 1920 ? 160 : 128, start == 1920 && token == 1);
        foreach (matrix_results[cluster])
            if (matrix_results[cluster] != 16) $fatal(1, "RESIDUAL_FABRIC_MISSING_RESULTS cluster=%0d", cluster);
        if (matrix_commands != 16 || overlap_commands != 16 || packets != 26 || strips != 512)
            $fatal(1, "RESIDUAL_FABRIC_CENSUS matrix=%0d overlap=%0d packets=%0d strips=%0d",
                   matrix_commands, overlap_commands, packets, strips);
        $display("RESIDUAL_FABRIC_PASS cores=20 input_macros=40 banks=4 concurrent_commands=16 matrix_values=2560 residual_values=4096");
        $finish;
    end

    initial begin
        #60000;
        $fatal(1, "RESIDUAL_FABRIC_TIMEOUT");
    end
endmodule

module tri_oracle_residual_fabric_input_count;
    initial begin
        #1;
        tri_oracle_residual_fabric_tb.input_macros++;
    end
endmodule
bind TS5N28HPCPSVTA512X64M4F tri_oracle_residual_fabric_input_count residual_fabric_input_count ();
