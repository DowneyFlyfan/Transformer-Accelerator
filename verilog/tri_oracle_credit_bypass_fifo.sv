// A synchronous queue with a registered output. An input arriving to an
// empty queue can load the output register directly when a read is requested.
module tri_oracle_credit_bypass_fifo #(
  parameter int WIDTH = 454,
  parameter int DEPTH = 8
) (
  input logic clk, rst_n,
  input logic read_enable, write_enable,
  input logic [WIDTH-1:0] write_data,
  output logic [WIDTH-1:0] read_data,
  output logic full, empty
);
  localparam int ADDRESS_BITS = $clog2(DEPTH);
  logic [ADDRESS_BITS:0] read_ptr, write_ptr;
  logic [WIDTH-1:0] entries [DEPTH];
  wire bypass = empty && read_enable && write_enable;
  wire store = write_enable && !full && !bypass;
  wire pop = read_enable && !empty;

  assign empty = write_ptr == read_ptr;
  assign full = write_ptr[ADDRESS_BITS] != read_ptr[ADDRESS_BITS] &&
                write_ptr[ADDRESS_BITS-1:0] == read_ptr[ADDRESS_BITS-1:0];

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      read_ptr <= 0;
      write_ptr <= 0;
    end else begin
      if (pop) read_ptr <= read_ptr + 1'b1;
      if (store) write_ptr <= write_ptr + 1'b1;
    end
  end

  always_ff @(posedge clk) begin
    if (store) entries[write_ptr[ADDRESS_BITS-1:0]] <= write_data;
    if (bypass) read_data <= write_data;
    else if (pop) read_data <= entries[read_ptr[ADDRESS_BITS-1:0]];
  end
endmodule
