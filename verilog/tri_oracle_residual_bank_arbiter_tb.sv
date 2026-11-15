`timescale 1ns/1ps
module tri_oracle_residual_bank_arbiter_tb;
    logic clk = 0, rst_n = 0;
    always #5 clk = ~clk;

    logic grouped_accept = 0, grouped_retire = 0, grouped_enable;
    logic residual_request = 0, native_idle = 1;
    logic residual_inflight = 0, residual_granted;

`ifdef CHECK_UNARBITRATED
    assign grouped_enable = rst_n;
    assign residual_granted = rst_n && residual_request;
`else
    tri_oracle_residual_bank_arbiter dut (.*);
`endif

    task automatic expect_access(
        input bit expect_grouped, expect_residual,
        input string phase
    );
        #1;
        if ({grouped_enable, residual_granted} !== {expect_grouped, expect_residual})
            $fatal(1, "ARBITER_%s grouped=%b residual=%b", phase, grouped_enable, residual_granted);
    endtask

    initial begin
        repeat (3) @(negedge clk);
        rst_n = 1;
        expect_access(1, 0, "IDLE");
        grouped_accept = 1;
        @(negedge clk);
        grouped_accept = 0;

        // The idle memory ports between normalization and draining still hold
        // the grouped command's data. A residual request must wait.
        residual_request = 1;
        repeat (3) begin
            expect_access(0, 0, "GROUPED_LIVE_ROWS");
            @(negedge clk);
        end
        grouped_retire = 1;
        native_idle = 0;
        @(negedge clk);
        grouped_retire = 0;
        expect_access(0, 0, "NATIVE_DRAIN");
        @(negedge clk);
        native_idle = 1;
        @(negedge clk);
        expect_access(0, 1, "RESIDUAL_ACQUIRED");

        // Hold the grant while data returned by the bank still awaits retirement.
        residual_inflight = 1;
        residual_request = 0;
        repeat (3) begin
            expect_access(0, 1, "RESIDUAL_DRAIN");
            @(negedge clk);
        end
        residual_inflight = 0;
        @(negedge clk);
        expect_access(1, 0, "GROUPED_REOPENS");

        // When both clients arrive in idle, block the grouped launch that cycle.
        residual_request = 1;
        expect_access(0, 0, "SAME_CYCLE_RESERVATION");
        @(negedge clk);
        expect_access(0, 1, "RESIDUAL_PRIORITY");
        rst_n = 0;
        expect_access(0, 0, "RESET");
        residual_request = 0;
        @(negedge clk);
        rst_n = 1;
        expect_access(1, 0, "RESET_RECOVERY");
        $display("RESIDUAL_BANK_ARBITER_PASS");
        $finish;
    end
endmodule
