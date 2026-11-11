`timescale 1ns/1ps
module tri_oracle_wac_shared_imem_tb;
    logic clk = 0;
    always #5 clk = ~clk;
    logic rst_n = 0;
    logic load_valid = 0, load_ready, load_error;
    logic [1:0] load_kind = 0;
    logic [9:0] load_addr = 0;
    logic [2047:0] load_data = 0;
    logic [31:0] load_row_enable = '1;
    logic cmd_valid = 0, cmd_ready, cmd_accumulate = 0;
    logic [4:0] cmd_weight = 0, cmd_mask = 0;
    logic [9:0] cmd_activation = 0;
    logic [3:0] cmd_output = 0, done_output, read_output = 0;
    logic done_valid, read_valid = 0, result_valid;
    logic [1023:0] result_data;
    logic softmax_cfg_valid = 0, softmax_cfg_ready, softmax_cfg_error;
    logic [10:0] softmax_cfg_length = 0;
    logic softmax_in_valid = 0, softmax_in_ready;
    logic signed [15:0] softmax_in_score = 0;
    logic [9:0] softmax_in_size = 0;
    logic softmax_out_valid, softmax_out_ready = 0, softmax_out_last;
    logic [15:0] softmax_out_probability;
    logic activation_reloaded = 0, activation_reload_required;
    int issued, completed;
    logic [3:0] slots [8];

    tri_oracle_wac_compute_softmax dut (.*);

    always @(posedge clk) if (rst_n) begin
        if (cmd_valid && cmd_ready) begin
            slots[issued] = cmd_output;
            issued++;
        end
        if (done_valid) begin
            if (completed >= issued || done_output !== slots[completed])
                $fatal(1, "WAC_IMEM_COMPLETION_ORDER");
            completed++;
        end
        if (softmax_cfg_valid && softmax_cfg_ready && completed != issued)
            $fatal(1, "WAC_IMEM_EARLY_GRANT issued=%0d completed=%0d", issued, completed);
    end

    task automatic load_word(input logic [1:0] kind, input logic [9:0] address,
                             input logic [2047:0] data);
        @(negedge clk);
        load_valid = 1;
        load_kind = kind;
        load_addr = address;
        load_data = data;
        @(posedge clk);
        if (!load_ready || cmd_ready) $fatal(1, "WAC_IMEM_LOAD_HANDSHAKE");
        #2;
        if (load_error) $fatal(1, "WAC_IMEM_LOAD_ERROR");
        @(negedge clk);
        load_valid = 0;
    endtask

    task automatic issue(input logic [3:0] slot, input logic bank);
        cmd_valid = 1;
        cmd_output = slot;
        cmd_activation = {bank, 9'd0};
        @(posedge clk);
        if (!cmd_ready) $fatal(1, "WAC_IMEM_ISSUE_HANDSHAKE");
        @(negedge clk);
        cmd_valid = 0;
    endtask

    task automatic acknowledge_tile;
        activation_reloaded = 1;
        @(negedge clk);
        activation_reloaded = 0;
        if (activation_reload_required) $fatal(1, "WAC_IMEM_RELOAD_ACK");
    endtask

    task automatic check_result(input logic [3:0] slot, input logic [31:0] expected);
        @(negedge clk);
        read_valid = 1;
        read_output = slot;
        @(posedge clk);
        #2;
        if (!result_valid || result_data !== {32{expected}})
            $fatal(1, "WAC_IMEM_COMPUTE_DATA slot=%0d got=%0d expected=%0d",
                   slot, result_data[31:0], expected);
        @(negedge clk);
        read_valid = 0;
    endtask

    initial begin
        repeat (2) @(negedge clk);
        rst_n = 1;
        load_word(0, 0, {256{8'd2}});
        load_word(1, 0, 2048'({8{8'd3}}));
        load_word(1, 512, 2048'({8{8'd4}}));
        load_word(2, 0, 2048'({256{1'b1}}));
        acknowledge_tile();
        issue(14, 0);
        issue(15, 1);
        wait (completed == 2);
        @(negedge clk);

        // Non-recent result reads occupy the result port and stall the array.
        read_valid = 1;
        read_output = 14;
        for (int slot = 0; slot < 4; slot++) issue(4'(slot), 1'(slot));
        cmd_valid = 1;
        cmd_output = 4;
        cmd_activation = 0;
        load_valid = 1;
        load_kind = 1;
        load_addr = 0;
        load_data = '0;
        softmax_cfg_valid = 1;
        softmax_cfg_length = 3;
        repeat (6) begin
            @(posedge clk);
            if (cmd_ready || load_ready || softmax_cfg_ready || completed != 2)
                $fatal(1, "WAC_IMEM_DRAIN_WHILE_STALLED");
            @(negedge clk);
        end
        read_valid = 0;
        do @(posedge clk); while (!softmax_cfg_ready);
        @(negedge clk);
        if (issued != 6 || completed != 6 || softmax_cfg_error)
            $fatal(1, "WAC_IMEM_DRAIN_LOST_COMPUTE");
        softmax_cfg_valid = 0;
        load_valid = 0;

        for (int key = 0; key < 3; key++) begin
            softmax_in_valid = 1;
            softmax_in_size = key == 1 ? 10'd2 : 10'd1;
            @(posedge clk);
            if (!softmax_in_ready || cmd_ready || load_ready)
                $fatal(1, "WAC_IMEM_SOFTMAX_EXCLUSIVITY");
            @(negedge clk);
        end
        softmax_in_valid = 0;
        // Result reads stay available while softmax owns the input banks.
        for (int slot = 0; slot < 4; slot++) check_result(4'(slot), slot[0] ? 64 : 48);
        for (int key = 0; key < 3; key++) begin
            do @(negedge clk); while (!softmax_out_valid);
            repeat (4) begin
                @(posedge clk);
                if (!softmax_out_valid || softmax_out_last !== (key == 2) || cmd_ready || load_ready ||
                    softmax_out_probability !== (key == 1 ? 16'd32768 : 16'd16384))
                    $fatal(1, "WAC_IMEM_STALLED_SOFTMAX key=%0d got=%0d", key, softmax_out_probability);
            end
            @(negedge clk);
            softmax_out_ready = 1;
            @(posedge clk);
            @(negedge clk);
            softmax_out_ready = 0;
        end
        repeat (3) begin
            @(posedge clk);
            if (!activation_reload_required || cmd_ready || !load_ready || issued != 6)
                $fatal(1, "WAC_IMEM_COMPUTE_BEFORE_RELOAD");
        end
        load_word(1, 0, 2048'({8{8'd5}}));
        load_word(1, 512, 2048'({8{8'd6}}));
        acknowledge_tile();
        issue(4, 0);
        issue(5, 1);
        wait (completed == 8);
        check_result(4, 80);
        check_result(5, 96);
        // Abort a later softmax after it has clobbered part of the input tile.
        softmax_cfg_valid = 1;
        softmax_cfg_length = 1;
        do @(posedge clk); while (!softmax_cfg_ready);
        @(negedge clk);
        softmax_cfg_valid = 0;
        softmax_in_valid = 1;
        @(posedge clk);
        if (!softmax_in_ready) $fatal(1, "WAC_IMEM_RESET_CASE_SETUP");
        @(negedge clk);
        softmax_in_valid = 0;
        rst_n = 0;
        repeat (2) @(negedge clk);
        rst_n = 1;
        @(posedge clk);
        if (cmd_ready || softmax_out_valid || !load_ready || !activation_reload_required)
            $fatal(1, "WAC_IMEM_RESET_RELEASED_STALE_ACTIVATIONS");
        $display("WAC_IMEM_HANDOFF_PASS drained=4 retained_results=4 softmax_outputs=3 resumed_results=2");
        $finish;
    end

    initial begin
        #10000;
        $fatal(1, "WAC_IMEM_WATCHDOG");
    end
endmodule
