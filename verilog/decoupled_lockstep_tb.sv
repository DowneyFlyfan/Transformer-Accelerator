`timescale 1ns/1ps
module decoupled_lockstep_tb;
    parameter int LINES = 32;
    parameter int LANES = 8;
    localparam int DATA_W = 8, STAGES = $clog2(LANES);
    localparam int SUM_W = 2*DATA_W+STAGES, BITS = LINES*SUM_W;
    logic clk = 0, rst_n = 0, in_valid = 0, out_ready = 0;
    logic [LINES*LANES*DATA_W-1:0] operand_a = '0, operand_b = '0;
    logic [LINES*LANES-1:0] lane_enable = '0;
    wire in_ready, out_valid, ref_ready, ref_valid;
    wire [BITS-1:0] out_sums, ref_sums;
    logic [BITS-1:0] expected[$];
    int accepted = 0, delivered = 0, checked = 0, dropped = 0, peak_pending = 0;
    logic [31:0] rng = 32'h85279437;
    always #5 clk = ~clk;

    tri_oracle_pe_array_decoupled #(.LINES(LINES), .LANES(LANES)) dut (.*);
    tri_oracle_pe_array #(.LINES(LINES), .LANES(LANES)) reference_array(
        .clk, .rst_n, .in_valid, .in_ready(ref_ready),
        .operand_a, .operand_b, .lane_enable,
        .out_valid(ref_valid), .out_ready, .out_sums(ref_sums));

    task automatic operands(input int code);
        for (int i = 0; i < LINES*LANES; i++) begin
            rng = rng*32'd1664525+32'd1013904223;
            operand_a[i*DATA_W+:DATA_W] = code < 0 ? 8'd27 : rng[31:24];
            rng = rng*32'd1664525+32'd1013904223;
            operand_b[i*DATA_W+:DATA_W] = code < 0 ? 8'd9 : rng[31:24];
            lane_enable[i] = code < 0 || ((i+code)%5 != 4);
        end
    endtask

    task automatic tick(input bit check_running = 0);
        logic [BITS-1:0] dot, result;
        int v;
        @(posedge clk);
        if ({in_ready, out_valid} !== {ref_ready,ref_valid})
            $fatal(1,"Handshakes differ at cycle %0d",checked);
        if (out_valid) begin
            if (expected.size() == 0 || out_sums !== ref_sums || out_sums !== expected[0])
                $fatal(1,"Payload differs at cycle %0d, buffered %0d",checked,expected.size());
            if (out_ready) begin
                result = expected.pop_front();
                delivered++;
            end
        end
        if (in_ready && in_valid) begin
            for (int line = 0; line < LINES; line++) begin
                v = 0;
                for (int lane = 0; lane < LANES; lane++)
                    if (lane_enable[line*LANES+lane])
                        v += int'($signed(operand_a[(line*LANES+lane)*DATA_W+:DATA_W]))*
                             int'($signed(operand_b[(line*LANES+lane)*DATA_W+:DATA_W]));
                dot[line*SUM_W+:SUM_W] = SUM_W'(v);
            end
            expected.push_back(dot);
            accepted++;
            if (expected.size() > peak_pending)
                peak_pending = expected.size();
        end
        checked++;
        #1;
        if (check_running && dut.product[0].value !== 16'd243)
            $fatal(1,"FREE_RUNNING_PRODUCT_DID_NOT_ADVANCE");
    endtask

    task automatic fill_stalled(input bit verify_datapath);
        for (int index = 0; index <= STAGES; index++) begin
            @(negedge clk); in_valid = 1; out_ready = 0; operands(index);
            tick();
        end
        if (expected.size() != STAGES+1) $fatal(1,"Directed fill did not reach capacity");
        repeat (STAGES+6) begin
            @(negedge clk); in_valid = 0; operands(-1);
            tick(verify_datapath);
        end
    endtask

    initial begin
        repeat (2) @(negedge clk);
        rst_n = 1;
        fill_stalled(1);
        for (int i = 0; i < 10; i++) begin
            @(negedge clk); in_valid = 0; out_ready = 1; tick();
        end
        if (expected.size() != 0) $fatal(1,"Full queue failed to drain");
        fill_stalled(1);
        @(negedge clk); rst_n = 0; in_valid = 0; out_ready = 0;
        dropped += expected.size(); expected.delete();
        repeat (2) tick();
        @(negedge clk); rst_n = 1;
        for (int i = 0; i < 1100; i++) begin
            @(negedge clk);
            if (!in_valid || in_ready) begin
                operands(i);
                in_valid = (i<190 || rng[23:21] != 0);
            end
            rng = rng*32'd1664525+32'd1013904223;
            out_ready = (i<190 || (i%91<75 && rng[13:11]!=0));
            tick();
        end
        for (int i = 0; i < 20; i++) begin
            @(negedge clk); in_valid = 0; out_ready = 1; tick();
        end
        if (expected.size()!=0 || accepted!=delivered+dropped || peak_pending!=STAGES+1 || delivered<700)
            $fatal(1,"Coverage or drain failed pending=%0d accepted=%0d delivered=%0d dropped=%0d peak=%0d", expected.size(),accepted,delivered,dropped,peak_pending);
        $display("DECOUPLED_ARRAY_PASS lines=%0d lanes=%0d edges=%0d accepted=%0d delivered=%0d reset_discarded=%0d peak_pending=%0d",
                 LINES,LANES,checked,accepted,delivered,dropped,peak_pending);
        $finish;
    end
endmodule
