`timescale 1ns/1ps

module tri_oracle_compact_bank_traffic #(
    parameter string MASTER = "",
    parameter int ADDRESS_BITS = 9
) (
    input logic clk, chip_enable_n, write_enable_n,
    input logic [ADDRESS_BITS-1:0] address
);
    longint unsigned cycle = 0;
    longint unsigned reads = 0, writes = 0;
    logic [63:0] signature = 64'hcbf29ce484222325;

    always @(posedge clk) begin
        cycle++;
        if (chip_enable_n === 1'b0) begin
            if ($isunknown({write_enable_n, address}))
                $fatal(1, "COMPACT_BANK_UNKNOWN_REQUEST %m");
            if (write_enable_n) reads++;
            else writes++;
            signature = (signature ^ {cycle[53:0], write_enable_n, 9'(address)}) *
                        64'h00000100000001b3;
        end
    end

    final $display("COMPACT_BANK %s %m %0d %0d %016h", MASTER, reads, writes, signature);
endmodule

bind TS5N28HPCPSVTA32X128M2FW tri_oracle_compact_bank_traffic #(
    .MASTER("TS5N28HPCPSVTA32X128M2FW"), .ADDRESS_BITS(5)
) traffic (.clk(CLK), .chip_enable_n(CEB), .write_enable_n(WEB), .address(A));

bind TS5N28HPCPSVTA512X64M4F tri_oracle_compact_bank_traffic #(
    .MASTER("TS5N28HPCPSVTA512X64M4F"), .ADDRESS_BITS(9)
) traffic (.clk(CLK), .chip_enable_n(CEB), .write_enable_n(WEB), .address(A));
