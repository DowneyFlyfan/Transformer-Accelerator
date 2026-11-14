`timescale 1ns/1ps
module tri_oracle_attention_residual_precision_tb;
    localparam int ROWS = 576;
    logic [279:0] residual_q32;
    logic [63:0] projection_codes;
    logic [4:0] projection_shift;
    logic [231:0] bypass_q26;
    logic [127:0] result_q13;
    logic [708:0] vectors [ROWS];
    logic [231:0] expected_bypass;
    logic [127:0] expected_normalization;
    string fixture;

`ifdef EARLY_ROUND
    logic [215:0] rounded_input;
    for (genvar lane = 0; lane < 8; lane++) begin : lane_input
        wire signed [34:0] full_value = residual_q32[35*lane +: 35];
        assign rounded_input[27*lane +: 27] = 27'(full_value >>> 7);
        assign bypass_q26[29*lane +: 29] = 29'($signed(rounded_input[27*lane +: 27])) <<< 1;
    end
    tri_oracle_residual_add dut (
        .residual_q25(rounded_input), .projection_codes,
        .projection_shift(projection_shift - 5'd1), .result_q13
    );
`else
    tri_oracle_attention_residual_precision dut (.*);
`endif

    initial begin
        if (!$value$plusargs("VECTORS=%s", fixture)) $fatal(1, "Missing residual operand vectors");
        $readmemh(fixture, vectors);
        for (int row = 0; row < ROWS; row++) begin
            {expected_normalization, expected_bypass, projection_shift, projection_codes, residual_q32} = vectors[row];
            #1;
            if (bypass_q26 !== expected_bypass || result_q13 !== expected_normalization)
                $fatal(1, "ATTENTION_RESIDUAL_PRECISION_MISMATCH row=%0d bypass=%h expected=%h norm=%h expected=%h",
                       row, bypass_q26, expected_bypass, result_q13, expected_normalization);
        end
        $display("ATTENTION_RESIDUAL_PRECISION_PASS trained_values=4096 edge_values=512");
        $finish;
    end
endmodule
