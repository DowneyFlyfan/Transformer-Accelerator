`timescale 1ns/1ps
module tri_oracle_residual_format_bank_tb;
    logic clk=0, rst_n=0, lease_granted=0;
    always #5 clk=~clk;
    logic cfg_valid=0, cfg_token, cfg_ready;
    logic [4:0] cfg_down_shift;
    logic req_valid=0, req_write, req_token, req_ready;
    logic [7:0] req_strip;
    logic [231:0] req_bypass, rsp_bypass;
    logic [127:0] req_normalization, rsp_normalization;
    logic rsp_valid, rsp_ready=0;
    logic [4:0] rsp_down_shift;
    logic [3:0] bank_ce_n, bank_we_n;
    logic [8:0] bank_addr;
    logic [255:0] bank_d, bank_q;
    logic [620:0] trained[512];
    logic [708:0] operands[576];
    logic [255:0] down_codes;
    logic [127:0] actual, expected, expected_normalization;
    logic [231:0] reference_bypass;
    logic [4:0] reference_shift;
    string fixture, precision_fixture;
    int compact_accesses, full_accesses;

    tri_oracle_residual_format_bank dut (.*);
    tri_oracle_decoder_residual_writeback result (
        .residual_q26(rsp_bypass), .down_codes, .down_shift(rsp_down_shift), .result_q13(actual)
    );
    tri_oracle_decoder_residual_writeback reference (
        .residual_q26(reference_bypass), .down_codes, .down_shift(reference_shift), .result_q13(expected)
    );
    for (genvar bank=0; bank<4; bank++) begin : banks
        TS5N28HPCPSVTA512X64M4F memory (
            .CLK(clk), .CEB(bank_ce_n[bank]), .WEB(bank_we_n[bank]), .A(bank_addr),
            .D(bank_d[64*bank +: 64]), .Q(bank_q[64*bank +: 64])
        );
    end

    task automatic configure(input bit token, input logic [4:0] shift);
        cfg_token=token;
        cfg_down_shift=shift;
        cfg_valid=1;
        @(posedge clk);
        if (!cfg_ready) $fatal(1,"RESIDUAL_FORMAT_CFG");
        @(negedge clk);
        cfg_valid=0;
    endtask

    task automatic request_row(input int row, input bit write);
        req_valid=1;
        req_write=write;
        req_token=1'(row/256);
        req_strip=8'(row);
        @(posedge clk);
        if (!req_ready || bank_addr !== 9'(row) ||
            bank_ce_n !== (row<256 ? 4'b1000 : 4'b0000) ||
            bank_we_n !== (write ? bank_ce_n : 4'b1111))
            $fatal(1,"RESIDUAL_FORMAT_BANK_SELECT row=%0d",row);
        if (row<256) compact_accesses++;
        else full_accesses++;
        @(negedge clk);
        req_valid=0;
    endtask

    initial begin
        if (!$value$plusargs("TRAINED=%s",fixture) || !$value$plusargs("PRECISION=%s",precision_fixture))
            $fatal(1,"Missing trained residual data");
        $readmemh(fixture,trained);
        $readmemh(precision_fixture,operands);
        repeat (3) @(negedge clk);
        rst_n=1;
        req_token=1;
        req_valid=1;
        req_write=0;
        @(posedge clk);
        if (req_ready || cfg_ready || bank_ce_n !== 4'b1111) $fatal(1,"RESIDUAL_FORMAT_NO_LEASE");
        @(negedge clk);
        lease_granted=1;
        @(posedge clk);
        if (req_ready || bank_ce_n !== 4'b1111) $fatal(1,"RESIDUAL_FORMAT_UNCONFIGURED");
        @(negedge clk);
        req_valid=0;
        configure(0,5'd11);
        configure(1,5'd10);
        for (int row=0; row<512; row++) begin
            req_bypass=row==256 ? 232'd3073 : trained[row][231:0];
            req_normalization=row==256 ? '0 : operands[row][708:581];
            request_row(row,1);
        end
        for (int index=0; index<512; index++) begin
            int row;
            row=(149*index)%512;
            reference_bypass=row==256 ? 232'd3073 : trained[row][231:0];
            expected_normalization=row==256 ? '0 : operands[row][708:581];
            reference_shift=row<256 ? 5'd11 : 5'd10;
            down_codes=row==256 ? 256'd1 : trained[row][487:232];
            request_row(row,0);
            cfg_valid=1;
            cfg_token=req_token;
            cfg_down_shift=5'd31;
            req_token=!req_token;
            repeat (2) begin
                @(posedge clk);
                if (!rsp_valid || req_ready || cfg_ready || bank_ce_n !== 4'b1111 ||
                    rsp_normalization !== expected_normalization || rsp_down_shift !== reference_shift ||
                    actual !== expected || (row<256 && actual !== trained[row][620:493]) ||
                    (row>=256 && rsp_bypass !== reference_bypass))
                    $fatal(1,"RESIDUAL_FORMAT_READBACK row=%0d got=%h expected=%h",row,actual,expected);
            end
            @(negedge clk);
            cfg_valid=0;
            rsp_ready=1;
            @(negedge clk);
            rsp_ready=0;
        end
        if (compact_accesses!=512 || full_accesses!=512) $fatal(1,"RESIDUAL_FORMAT_COUNTS");
        $display("RESIDUAL_FORMAT_PASS compact_rows=256 full_rows=256 values=4096 held_cycles=1024");
        $finish;
    end
    initial begin #60000; $fatal(1,"RESIDUAL_FORMAT_TIMEOUT"); end
endmodule
