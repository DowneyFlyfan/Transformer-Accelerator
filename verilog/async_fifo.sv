module async_fifo #(
    parameter int BW = 8,
    parameter int SIMD = 1,
    parameter int MEM_SIZE = 16
) (
    input  logic               rd_clk,
    input  logic               wr_clk,
    input  logic               rd,
    input  logic               wr,
    input  logic               rst_n,
    input  logic [SIMD*BW-1:0] in,
    output logic [SIMD*BW-1:0] out,
    output logic               full,
    output logic               empty
);

  localparam int PtrWidth = $clog2(MEM_SIZE);

  logic [PtrWidth:0] rd_ptr;
  logic [PtrWidth:0] wr_ptr;
  logic [SIMD*BW-1:0] q[MEM_SIZE];

  always_comb begin
    empty = (wr_ptr == rd_ptr) ? 1'b1 : 1'b0;
    full = ((wr_ptr[PtrWidth-1:0] == rd_ptr[PtrWidth-1:0]) && (wr_ptr[PtrWidth] != rd_ptr[PtrWidth])) ? 1'b1 : 1'b0;
  end

  always_ff @(posedge rd_clk or negedge rst_n) begin : read_logic
    if (~rst_n) rd_ptr <= '0;
    else if ((rd == 1) && (empty == 0)) begin
      rd_ptr <= rd_ptr + 1;
      out <= q[rd_ptr[PtrWidth-1:0]];
    end
  end

  always_ff @(posedge wr_clk or negedge rst_n) begin : write_logic
    if (~rst_n) begin
      wr_ptr <= '0;
    end else begin
      if ((wr == 1) && (full == 0)) begin
        wr_ptr <= wr_ptr + 1;
        q[wr_ptr[PtrWidth-1:0]] <= in;
      end
    end
  end

endmodule
