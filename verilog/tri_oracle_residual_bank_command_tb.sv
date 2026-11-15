`timescale 1ns/1ps
module tri_oracle_residual_bank_command_tb;
    logic clk = 0, rst_n = 0;
    always #5 clk = ~clk;

    logic residual_request = 0, residual_granted;
    logic [3:0] probability_grant = '1;
    logic grouped_valid = 0, grouped_ready, grouped_core_valid, grouped_core_ready = 0;
    logic grouped_done_valid = 0, grouped_done_ready = 0;
    logic projection_cfg_valid = 0, projection_cfg_ready = 1;
    logic residual_read_valid = 0, residual_read_ready = 0, residual_response_valid = 0;
    logic writeback_cfg_valid = 0, writeback_cfg_ready = 1, writeback_active = 0;
    int grouped_starts = 0;

`ifdef CHECK_UNARBITRATED
    assign grouped_ready = grouped_core_ready;
    assign grouped_core_valid = grouped_valid;
    assign residual_granted = residual_request;
`else
    tri_oracle_residual_bank_command dut (.*);
`endif

    always @(posedge clk) if (grouped_core_valid && grouped_core_ready) grouped_starts++;

    task automatic blocked_group(input bit grant, input string phase);
        #1;
        if ({residual_granted, grouped_core_valid, grouped_ready} !== {grant, 2'b00})
            $fatal(1, "COMMAND_%s grant=%b valid=%b ready=%b",
                   phase, residual_granted, grouped_core_valid, grouped_ready);
    endtask

    initial begin
        repeat (3) @(negedge clk);
        rst_n = 1;
        grouped_valid = 1;
        @(negedge clk);
        if (!grouped_core_valid || grouped_ready || grouped_starts != 0)
            $fatal(1, "GROUPED_BACKPRESSURE");
        grouped_core_ready = 1;
        @(negedge clk);
        if (grouped_starts != 1) $fatal(1, "GROUPED_FIRST_ACCEPT");

        residual_request = 1;
        blocked_group(0, "ACTIVE_GROUP");
        grouped_done_valid = 1;
        repeat (2) begin
            @(negedge clk);
            blocked_group(0, "HELD_GROUP_RESPONSE");
        end
        grouped_done_ready = 1;
        probability_grant = 4'b0111;
        @(negedge clk);
        grouped_done_valid = 0;
        @(negedge clk);
        blocked_group(0, "LAST_NATIVE_OWNER");
        probability_grant = '1;
        @(negedge clk);
        blocked_group(1, "RESIDUAL_ACQUIRE");

        // Each of these can independently keep the residual bank live.
        residual_request = 0;
        projection_cfg_valid = 1;
        @(negedge clk);
        blocked_group(1, "PROJECTION_START");
        projection_cfg_valid = 0;
        projection_cfg_ready = 0;
        @(negedge clk);
        blocked_group(1, "PROJECTION_BUSY");
        projection_cfg_ready = 1;
        writeback_cfg_valid = 1;
        @(negedge clk);
        blocked_group(1, "WRITEBACK_START");
        writeback_cfg_valid = 0;
        writeback_active = 1;
        @(negedge clk);
        blocked_group(1, "WRITEBACK_ACTIVE");
        writeback_active = 0;
        residual_read_valid = 1;
        residual_read_ready = 1;
        @(negedge clk);
        blocked_group(1, "BANK_READ_START");
        residual_read_valid = 0;
        residual_read_ready = 0;
        residual_response_valid = 1;
        @(negedge clk);
        blocked_group(1, "BANK_RESPONSE_HELD");
        residual_response_valid = 0;
        @(negedge clk);
        if (residual_granted || !grouped_ready || !grouped_core_valid || grouped_starts != 1)
            $fatal(1, "RESIDUAL_RELEASE");
        @(negedge clk);
        if (grouped_starts != 2) $fatal(1, "GROUPED_SECOND_ACCEPT");
        $display("RESIDUAL_BANK_COMMAND_PASS grouped_accepts=%0d", grouped_starts);
        $finish;
    end
endmodule
