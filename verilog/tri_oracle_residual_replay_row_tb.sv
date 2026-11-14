`timescale 1ns/1ps
module tri_oracle_residual_replay_row_tb;
    logic [231:0] write_bypass;
    logic [127:0] write_normalization;
    logic [23:0] write_padding, read_padding;
    logic [231:0] read_bypass;
    logic [127:0] read_normalization;
    logic [708:0] vectors [576];
    string fixture;

`ifdef DROP_CORRECTION
    assign write_padding = '0;
    tri_oracle_decoder_residual_writeback codec (
        .residual_q26(read_bypass), .down_codes(256'd0), .down_shift(5'd0),
        .result_q13(read_normalization)
    );
`else
    tri_oracle_residual_replay_row codec (.*);
`endif

    task automatic check_row(input int row);
        #1;
        read_bypass = write_bypass;
`ifdef DROP_CORRECTION
        read_padding = '0;
`else
        read_padding = write_padding;
`endif
        #1;
        if (read_normalization !== write_normalization || write_padding[23:16] !== 0)
            $fatal(1, "RESIDUAL_REPLAY_ROW_MISMATCH row=%0d got=%h expected=%h",
                   row, read_normalization, write_normalization);
        for (int lane=0; lane<8; lane++)
            if (write_padding[2*lane +: 2] === 2'b10)
                $fatal(1, "RESIDUAL_REPLAY_RESERVED_CORRECTION row=%0d lane=%0d", row, lane);
    endtask

    initial begin
        if (!$value$plusargs("VECTORS=%s", fixture)) $fatal(1, "Missing residual fixture");
        $readmemh(fixture, vectors);
        for (int row=0; row<576; row++) begin
            write_bypass = vectors[row][580:349];
            write_normalization = vectors[row][708:581];
            check_row(row);
        end
        // Just below each signed halfway point in the full-precision value.
        // Both bypass lanes already rounded to the corresponding halfway point.
        write_bypass = {174'd0, -29'sd4096, 29'sd4096};
        write_normalization = '0;
        check_row(576);
        if (write_padding !== 24'h000007) $fatal(1, "RESIDUAL_REPLAY_WRONG_CORRECTION");
        $display("RESIDUAL_REPLAY_ROW_PASS trained_values=4096 edge_values=514");
        $finish;
    end
endmodule
