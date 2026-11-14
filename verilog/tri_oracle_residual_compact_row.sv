`timescale 1ns/1ps

// For a down shift of at least 11, every rounding boundary of write-back
// lands on a multiple of 2048 in the residual's integer units. Preserve
// exact multiples and map open intervals to their first integer. The caller
// must use full precision if the configured down shift is below 11.
module tri_oracle_residual_compact_row (
    input logic [231:0] write_bypass,
    input logic [15:0] write_correction,
    output logic [191:0] write_row,
    input logic [191:0] read_row,
    output logic [231:0] read_bypass,
    output logic [15:0] read_correction
);
    assign write_row[191:168] = '0;
    for (genvar lane=0; lane<8; lane++) begin : lanes
        wire [28:0] bypass = write_bypass[29*lane +: 29];
        wire [20:0] stored = read_row[21*lane +: 21];
        assign write_row[21*lane +: 21] =
            {write_correction[2*lane +: 2], bypass[28:11], (|bypass[10:0])};
        assign read_bypass[29*lane +: 29] = {stored[18:1], 10'd0, stored[0]};
        assign read_correction[2*lane +: 2] = stored[20:19];
    end
endmodule
