module ofifo #(
    parameter int COL  = 8,
    parameter int SIMD = 1,
    parameter int BW   = 24
) (
    input  logic                   clk,
    input  logic                   rst_n,
    input  logic                   rd,
    input  logic [        COL-1:0] wr,
    input  logic [SIMD*COL*BW-1:0] in,
    output logic [SIMD*COL*BW-1:0] out,
    output logic                   o_full,
    output logic                   o_valid
);

  logic [COL-1:0] full;
  logic [COL-1:0] empty;

  always_comb begin
    o_full  = full[7];
    o_valid = ~|empty;
  end

  for (genvar i = 0; i < COL; i++) begin : g_col_idx
    async_fifo #(
        .BW  (BW),
        .SIMD(SIMD)
    ) fifo_instance (
        .rd_clk(clk),
        .wr_clk(clk),
        .rst_n(rst_n),
        .rd(rd),
        .wr(wr[i]),
        .in(in[BW*SIMD*(i+1)-1:BW*SIMD*i]),
        .out(out[BW*SIMD*(i+1)-1:BW*SIMD*i]),
        .full(full[i]),
        .empty(empty[i])
    );
  end

endmodule
