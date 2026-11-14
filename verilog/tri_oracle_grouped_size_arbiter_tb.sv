`timescale 1ns/1ps

module tri_oracle_grouped_size_arbiter_tb;
    logic clk = 0, rst_n = 0;
    always #5 clk = ~clk;
    logic [4:0] query_valid = '0, query_ready;
    logic [4:0][9:0] query_position = '{10'd85, 10'd84, 10'd83, 10'd82, 10'd81};
    logic [4:0] size_valid, size_ready = '0, size_last, error;
    logic [9:0] size_count;
    logic native_query_valid, native_query_ready = 0;
    logic [9:0] native_query_position;
    logic native_size_valid = 0, native_size_ready, native_size_last = 0, native_error = 0;
    logic [9:0] native_size_count = 0;
    int requests = 0, delivered = 0, stalled = 0, errors = 0;

    tri_oracle_grouped_size_arbiter dut (.*);

    task automatic check_query(input int client);
        logic [4:0] mask;
        mask = 5'b1 << client;
        @(posedge clk);
        if (query_ready !== mask || error !== '0 || native_query_valid !== 1'b1 ||
            native_query_position !== query_position[client])
            $fatal(1, "GROUPED_SIZE_REQUEST client=%0d ready=%b error=%b", client, query_ready, error);
        requests++;
        @(negedge clk);
        query_valid[client] = 0;
        native_query_ready = 0;
    endtask

    task automatic check_beat(input int client, beat, input bit last, ready);
        logic [4:0] mask;
        mask = 5'b1 << client;
        native_size_valid = 1;
        native_size_last = last;
        native_size_count = 10'(31 * client + beat + 1);
        size_ready = ready ? '1 : ~mask;
        @(posedge clk);
        if (size_valid !== mask || size_last !== (last ? mask : 5'b0) ||
            size_count !== native_size_count || native_size_ready !== ready ||
            error !== '0 || query_ready !== '0 || native_query_valid !== 1'b0)
            $fatal(1, "GROUPED_SIZE_WRONG_OWNER client=%0d beat=%0d", client, beat);
        if (ready) delivered++;
        else stalled++;
        @(negedge clk);
    endtask

    initial begin
        repeat (3) @(negedge clk);
        rst_n = 1;
        native_query_ready = 1;
        query_valid = '1;
        for (int client = 0; client < 5; client++) begin
            check_query(client);
            repeat (3) begin
                @(posedge clk);
                if (query_ready !== '0 || error !== '0 || size_valid !== '0 || native_query_valid !== 1'b0)
                    $fatal(1, "GROUPED_SIZE_BUSY_FRAME client=%0d", client);
                @(negedge clk);
            end
            check_beat(client, 0, 0, 1);
            check_beat(client, 1, 1, 0);
            check_beat(client, 1, 1, 0);
            check_beat(client, 1, 1, 1);
            native_size_valid = 0;
            native_size_last = 0;
            native_query_ready = 1;
        end
        // One error on an in-flight walk is delivered only to its owner.
        query_valid = 5'b00011;
        check_query(0);
        native_error = 1;
        @(posedge clk);
        if (error !== 5'b00001 || size_valid !== '0 || native_size_ready !== 0)
            $fatal(1, "GROUPED_SIZE_ERROR_OWNER");
        errors++;
        @(negedge clk);
        native_error = 0;
        // The next waiter sees the missing-frame error after the walk aborts.
        @(posedge clk);
        if (error !== 5'b00010 || query_ready !== '0 || native_query_valid !== 1'b0)
            $fatal(1, "GROUPED_SIZE_MISSING_FRAME");
        errors++;
        @(negedge clk);
        query_valid = 0;
        native_query_ready = 1;
        query_valid[2] = 1;
        check_query(2);
        check_beat(2, 0, 1, 1);
        native_size_valid = 0;
        native_size_last = 0;
        if (requests != 7 || delivered != 11 || stalled != 10 || errors != 2)
            $fatal(1, "GROUPED_SIZE_INVENTORY");
        $display("GROUPED_SIZE_ARBITER_PASS clients=5 requests=%0d beats=%0d stalled=%0d errors=%0d",
                 requests, delivered, stalled, errors);
        $finish;
    end

    initial begin
        #10000;
        $fatal(1, "GROUPED_SIZE_ARBITER_TIMEOUT");
    end
endmodule
