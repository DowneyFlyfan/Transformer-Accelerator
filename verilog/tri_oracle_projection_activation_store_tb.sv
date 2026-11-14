`timescale 1ns/1ps

module tri_oracle_projection_activation_store_tb #(
    parameter bit SHARED_BANK = 0
);
    logic clk = 0, rst_n = 0;
    always #5 clk = ~clk;

    logic in_valid = 0, in_ready;
    logic [2047:0] in_data;
    logic [4:0] in_shift;
    logic [5:0] in_row;
    logic frame_ready, fill_error, release_valid = 0, release_ready;
    logic req_valid = 0, req_ready;
    logic [8:0] req_word;
    logic [4:0] req_length;
    logic rsp_valid, rsp_ready = 0, rsp_last, rsp_error;
    logic [63:0] rsp_data;
    logic [2052:0] operands[64];
    logic [511:0] expected[64];
    string inputs, outputs;
    int checked = 0, errors = 0, stalls = 0;

    logic metadata_idle = 0, acquire_valid = 0, acquire_ready;
    logic metadata_ce_n = 1, metadata_we_n = 1;
    logic [8:0] metadata_address = 0;
    logic [63:0] metadata_write_data = 0, metadata_read_data;

    if (SHARED_BANK) begin : shared_test
        tri_oracle_projection_shared_bank dut (
            .clk, .rst_n, .metadata_idle, .acquire_valid, .acquire_ready,
            .release_valid, .release_ready, .row_valid(in_valid), .row_ready(in_ready),
            .row_data(in_data), .row_shift(in_shift), .row_index(in_row), .frame_ready,
            .fill_error, .req_valid, .req_ready, .req_word, .req_length,
            .rsp_valid, .rsp_ready, .rsp_last, .rsp_error, .rsp_data,
            .metadata_ce_n, .metadata_we_n, .metadata_address, .metadata_write_data,
            .metadata_read_data
        );
    end else begin : dedicated_test
        tri_oracle_projection_activation_store dut (
            .clk, .rst_n, .in_valid, .in_ready, .in_data, .in_shift, .in_row,
            .frame_ready, .fill_error, .release_valid, .release_ready,
            .req_valid, .req_ready, .req_word, .req_length, .rsp_valid, .rsp_ready,
            .rsp_last, .rsp_error, .rsp_data, .bank_ce_n(), .bank_we_n(),
            .bank_address(), .bank_write_data(), .bank_read_data('0)
        );
    end

    task automatic acquire_bank;
        if (SHARED_BANK) begin
            acquire_valid = 1;
            metadata_idle = 0;
            @(posedge clk);
            if (acquire_ready !== 0) $fatal(1, "ACTIVATION_STORE_METADATA_BUSY");
            @(negedge clk);
            metadata_idle = 1;
            metadata_ce_n = 0;
            @(posedge clk);
            if (acquire_ready !== 0) $fatal(1, "ACTIVATION_STORE_METADATA_ACCESS_ACTIVE");
            @(negedge clk);
            metadata_ce_n = 1;
            @(posedge clk);
            if (acquire_ready !== 1) $fatal(1, "ACTIVATION_STORE_ACQUIRE");
            @(negedge clk);
            acquire_valid = 0;
        end
    endtask

    task automatic metadata_roundtrip(input logic [63:0] data);
        if (SHARED_BANK) begin
            metadata_ce_n = 0;
            metadata_we_n = 0;
            metadata_address = 9'd504;
            metadata_write_data = data;
            @(negedge clk);
            metadata_we_n = 1;
            @(negedge clk);
            if (metadata_read_data !== data) $fatal(1, "ACTIVATION_STORE_METADATA_OWNERSHIP");
            metadata_ce_n = 1;
        end
    endtask

    task automatic offer(input int row);
        in_row = 6'(row);
        {in_shift, in_data} = operands[row];
        in_valid = 1;
        do @(posedge clk); while (in_ready !== 1'b1);
        @(negedge clk);
        in_valid = 0;
    endtask

    task automatic read_burst(input int first, length, input bit fault);
        req_word = 9'(first);
        req_length = 5'(length);
        req_valid = 1;
        @(posedge clk);
        if (req_ready !== 1'b1) $fatal(1, "ACTIVATION_STORE_READ_NOT_ACCEPTED");
        @(negedge clk);
        req_valid = 0;
        for (int beat = 0; beat < (fault ? 1 : length); beat++) begin
            logic [63:0] word_value;
            bit last;
            word_value = fault ? '0 : expected[(first+beat)/8][64*((first+beat)%8) +: 64];
            last = fault || beat + 1 == length;
            repeat (1 + ((first+beat)%3)) begin
                @(posedge clk);
                if ({rsp_valid, rsp_error, rsp_last, rsp_data, req_ready, release_ready} !==
                    {1'b1, fault, last, word_value, 2'b00})
                    $fatal(1, "ACTIVATION_STORE_HELD_RESPONSE first=%0d beat=%0d", first, beat);
                stalls++;
                @(negedge clk);
            end
            rsp_ready = 1;
            @(posedge clk);
            if ({rsp_valid, rsp_error, rsp_last, rsp_data} !== {1'b1, fault, last, word_value})
                $fatal(1, "ACTIVATION_STORE_RESPONSE first=%0d beat=%0d", first, beat);
            @(negedge clk);
            rsp_ready = 0;
            if (fault) errors++;
            else checked++;
        end
        if (rsp_valid) $fatal(1, "ACTIVATION_STORE_EXTRA_RESPONSE");
    endtask

    task automatic reset_now;
        rst_n = 0;
        repeat (2) @(negedge clk);
        rst_n = 1;
        #1;
        if ({frame_ready, fill_error, req_ready, rsp_valid} !== '0)
            $fatal(1, "ACTIVATION_STORE_RESET_STATE");
    endtask

    initial begin
        if (!$value$plusargs("OPERANDS=%s", inputs) || !$value$plusargs("EXPECTED=%s", outputs))
            $fatal(1, "ACTIVATION_STORE_ARGUMENTS");
        $readmemh(inputs, operands);
        $readmemh(outputs, expected);
        reset_now();
        metadata_roundtrip(64'h0123456789abcdef);
        acquire_bank();
        offer(63);
        if (frame_ready || req_ready || fill_error) $fatal(1, "ACTIVATION_STORE_PREMATURE_COMMIT");
        offer(63);
        if (!fill_error || frame_ready || req_ready) $fatal(1, "ACTIVATION_STORE_DUPLICATE");
        release_valid = 1;
        @(posedge clk);
        if (!release_ready) $fatal(1, "ACTIVATION_STORE_ERROR_RELEASE");
        @(negedge clk);
        release_valid = 0;
        #1;
        if ({frame_ready, fill_error, req_ready, rsp_valid} !== '0)
            $fatal(1, "ACTIVATION_STORE_ERROR_RELEASE_STATE");

        // The permutation covers both tokens and interleaves logical rows.
        @(negedge clk);
        acquire_bank();
        for (int i = 0; i < 64; i++) begin
            offer((17*i+63)%64);
            if (frame_ready !== (i==63) || req_ready !== (i==63) || fill_error)
                $fatal(1, "ACTIVATION_STORE_COMMIT row=%0d", i);
        end
        read_burst(0, 0, 1);
        read_burst(0, 17, 1);
        read_burst(511, 2, 1);
        if (SHARED_BANK) begin
            // Writes from the parked metadata side must never reach the bank.
            metadata_ce_n = 0;
            metadata_we_n = 0;
            metadata_write_data = '0;
        end
        for (int first = 0; first < 512; first += 16)
            read_burst(first, 16, 0);
        read_burst(511, 1, 0);
        read_burst(7, 3, 0);

        release_valid = 1;
        req_valid = 1;
        @(posedge clk);
        if (!release_ready || req_ready) $fatal(1, "ACTIVATION_STORE_RELEASE_PRIORITY");
        @(negedge clk);
        release_valid = 0;
        req_valid = 0;
        metadata_ce_n = 1;
        if (frame_ready || req_ready || fill_error || checked != 516 || errors != 3)
            $fatal(1, "ACTIVATION_STORE_INVENTORY");
        metadata_roundtrip(64'hfedcba9876543210);
        if (SHARED_BANK) $display("ACTIVATION_STORE_SHARED_BANK_PASS");
        $display("ACTIVATION_STORE_PASS rows=64 beats=%0d errors=%0d stalls=%0d", checked, errors, stalls);
        $finish;
    end

    initial begin
        #200000;
        $fatal(1, "ACTIVATION_STORE_TIMEOUT");
    end
endmodule
