`timescale 1ns/1ps
module tri_oracle_residual_compact_row_tb;
    logic clk=0;
    always #5 clk=~clk;
    logic [231:0] write_bypass, read_bypass;
    logic [15:0] read_correction;
    logic [191:0] write_row, read_row;
    logic [23:0] write_padding;
    logic [127:0] direct_norm, replay_norm, wide_result, compact_result;
    logic [255:0] down_codes;
    logic [4:0] down_shift;
    logic ce_n=1, we_n=1;
    logic [8:0] address;
    logic [620:0] trained[512];
    logic [708:0] operands[576];
    string fixture, precision_fixture;

    tri_oracle_residual_compact_row codec (.*, .write_correction(write_padding[15:0]));
    tri_oracle_residual_replay_row correction (
        .write_bypass, .write_normalization(direct_norm), .write_padding,
        .read_bypass, .read_padding({8'd0,read_correction}), .read_normalization(replay_norm)
    );
    tri_oracle_decoder_residual_writeback reference (
        .residual_q26(write_bypass), .down_codes, .down_shift, .result_q13(wide_result)
    );
    tri_oracle_decoder_residual_writeback compact (
        .residual_q26(read_bypass), .down_codes, .down_shift, .result_q13(compact_result)
    );
    for (genvar bank=0; bank<3; bank++) begin : memory
        TS5N28HPCPSVTA512X64M4F bank_model (
            .CLK(clk), .CEB(ce_n), .WEB(we_n), .A(address),
            .D(write_row[64*bank +: 64]), .Q(read_row[64*bank +: 64])
        );
    end

    initial begin
        if (!$value$plusargs("TRAINED=%s",fixture) || !$value$plusargs("PRECISION=%s",precision_fixture))
            $fatal(1,"Missing trained residual data");
        $readmemh(fixture,trained);
        $readmemh(precision_fixture,operands);
        @(negedge clk);
        ce_n=0;
        we_n=0;
        for (int row=0; row<512; row++) begin
            address=9'(row);
            write_bypass=trained[row][231:0];
            direct_norm=operands[row][708:581];
            @(negedge clk);
        end
        we_n=1;
        for (int index=0; index<512; index++) begin
            int row;
            row=(149*index+1)%512;
            address=9'(row);
            write_bypass=trained[row][231:0];
            direct_norm=operands[row][708:581];
            down_codes=trained[row][487:232];
            down_shift=trained[row][492:488];
            @(negedge clk);
            if (down_shift<11 || wide_result !== trained[row][620:493] ||
                compact_result !== trained[row][620:493] || replay_norm !== direct_norm)
                $fatal(1,"COMPACT_RESIDUAL_TRAINED row=%0d",row);
        end

        // A negative value just above the halfway point must round to zero.
        // The interval flag keeps it distinct from the halfway point itself.
        we_n=0;
        address=0;
        write_bypass={-29'sd268435456,29'sd268435455,-29'sd4097,-29'sd4096,
                      -29'sd4095,29'sd4095,29'sd4096,29'sd4097};
        direct_norm={16'h8000,16'h7fff,16'hffff,16'hffff,16'h0000,16'h0000,16'h0001,16'h0001};
        @(negedge clk);
        we_n=1;
        @(negedge clk);
        for (int shift=11; shift<32; shift++) begin
            down_shift=5'(shift);
            for (int code=-3; code<=3; code++) begin
                down_codes={8{32'(code)}};
                #1;
                if (compact_result !== wide_result || replay_norm !== direct_norm)
                    $fatal(1,"COMPACT_RESIDUAL_BOUNDARY shift=%0d code=%0d",shift,code);
            end
        end
        // At shift ten the boundary can split one encoded interval.
        // This explicitly tests the limit on use of the compact format.
        @(negedge clk);
        we_n=0;
        write_bypass=232'd3073;
        direct_norm='0;
        @(negedge clk);
        we_n=1;
        down_shift=5'd10;
        down_codes=256'd1;
        @(negedge clk);
        if (wide_result !== 128'd1 || compact_result !== 128'd0)
            $fatal(1,"COMPACT_RESIDUAL_UNSUPPORTED_SHIFT_CONTROL");
        $display("COMPACT_RESIDUAL_PASS banks=3 trained_values=4096 shift_code_cases=147 unsupported_shift_control=1");
        $finish;
    end
    initial begin #30000; $fatal(1,"COMPACT_RESIDUAL_TIMEOUT"); end
endmodule
