`timescale 1ns/1ps
module tri_oracle_sram_residual_overlap_tb;
    logic clk = 0, rst_n = 0;
    always #5 clk = ~clk;

    logic load_valid = 0, cmd_valid = 0, read_valid = 0;
    logic [1:0] load_kind;
    logic [9:0] load_addr, cmd_activation;
    logic [2047:0] load_data;
    logic [3:0] cmd_output, read_output;
    logic load_error, cmd_ready, done_valid, result_valid;
    logic [3:0] done_output;
    logic [1023:0] result_data;

    logic residual_reserved = 0, residual_ce_n = 1, residual_we_n = 1;
    logic [8:0] residual_addr;
    logic [63:0] residual_d, residual_q;
    logic [620:0] trained [512];
    string fixture;
    int completed = 0;

`ifdef RESIDUAL_PORTS
    tri_oracle_sram_residual_core
`else
    tri_oracle_sram_memory_compute
`endif
    dut (
        .clk, .rst_n, .load_valid, .load_kind, .load_addr, .load_data,
        .load_row_enable(32'hffffffff), .load_error, .cmd_valid,
        .cmd_ready, .cmd_weight(5'd0), .cmd_activation, .cmd_mask(5'd0),
        .cmd_output, .cmd_accumulate(1'b0), .done_valid, .done_output,
        .read_valid, .read_output, .result_valid, .result_data
`ifdef RESIDUAL_PORTS
        , .residual_reserved, .residual_ce_n, .residual_we_n, .residual_addr,
        .residual_d, .residual_q
`endif
    );
`ifndef RESIDUAL_PORTS
    assign residual_q = '0;
`endif

    task automatic load_word(input int kind, address, input logic [2047:0] data,
                              input bit error_expected = 0);
        load_valid = 1;
        load_kind = 2'(kind);
        load_addr = 10'(address);
        load_data = data;
        @(negedge clk);
        if (load_error !== error_expected)
            $fatal(1, "SRAM_RESIDUAL_LOAD address=%0d error=%0b expected=%0b",
                   address, load_error, error_expected);
        load_valid = 0;
    endtask

    always @(posedge clk) if (rst_n && done_valid) begin
        if (done_output !== 4'(completed))
            $fatal(1, "SRAM_RESIDUAL_COMPLETION index=%0d output=%0d", completed, done_output);
        completed++;
    end

    task automatic compare_result(input int slot, expected);
        read_valid = 1;
        read_output = 4'(slot);
        @(negedge clk);
        read_valid = 0;
        if (!result_valid || result_data !== {32{32'(expected)}})
            $fatal(1, "SRAM_RESIDUAL_MATRIX slot=%0d actual=%0d expected=%0d",
                   slot, $signed(result_data[31:0]), expected);
    endtask

    initial begin
        if (!$value$plusargs("TRAINED=%s", fixture)) $fatal(1, "Missing trained vectors");
        $readmemh(fixture, trained);
        repeat (3) @(negedge clk);
        rst_n = 1;
        load_word(0, 0, {256{8'h02}});
        load_word(2, 0, {1792'd0, {256{1'b1}}});
        for (int row = 0; row < 16; row++)
            load_word(1, 496+row, {1984'd0, {8{8'(row+1)}}});

        residual_reserved = 1;
        residual_we_n = 0;
        for (int row = 0; row < 512; row++) begin
            residual_ce_n = 0;
            residual_addr = 9'(row);
            residual_d = trained[row][63:0];
            @(negedge clk);
        end
        residual_ce_n = 1;
        residual_we_n = 1;
        load_word(1, 1023, '0, 1);

        cmd_valid = 1;
        cmd_activation = 10'd1023;
        cmd_output = 0;
        repeat (2) begin
            @(posedge clk);
            if (cmd_ready !== 0) $fatal(1, "SRAM_RESIDUAL_NATIVE_UPPER_CONFLICT");
            @(negedge clk);
        end
        cmd_valid = 0;

        // Different addresses in the two banks expose an accidentally shared bus.
        for (int index = 0; index < 512; index++) begin
            int row;
            row = 511-index;
            residual_ce_n = 0;
            residual_addr = 9'(row);
            cmd_valid = index < 16;
            cmd_activation = 10'(496+index);
            cmd_output = 4'(index);
            @(posedge clk);
            if (index < 16 && cmd_ready !== 1)
                $fatal(1, "SRAM_RESIDUAL_MATRIX_STALLED row=%0d", row);
            @(negedge clk);
            if (residual_q !== trained[row][63:0])
                $fatal(1, "SRAM_RESIDUAL_READ row=%0d", row);
        end
        residual_ce_n = 1;
        if (completed != 16) $fatal(1, "SRAM_RESIDUAL_COMPLETION_COUNT count=%0d", completed);
        for (int slot = 0; slot < 16; slot++) compare_result(slot, 16*(slot+1));

        residual_reserved = 0;
        load_word(1, 1023, {1984'd0, {8{8'hf9}}});
        cmd_valid = 1;
        cmd_activation = 10'd1023;
        cmd_output = 0;
        @(posedge clk);
        if (cmd_ready !== 1) $fatal(1, "SRAM_RESIDUAL_NATIVE_UPPER_RESTORE");
        @(negedge clk);
        cmd_valid = 0;
        wait (completed == 17);
        @(negedge clk);
        compare_result(0, -112);
        $display("SRAM_RESIDUAL_OVERLAP_PASS residual_rows=512 concurrent_commands=16 exact_matrix_values=544");
        $finish;
    end

    initial begin
        #40000;
        $fatal(1, "SRAM_RESIDUAL_TIMEOUT");
    end
endmodule
