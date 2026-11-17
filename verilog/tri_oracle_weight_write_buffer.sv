`timescale 1ns/1ps
// Replace the two registered write lanes in place. A blocked entry retains its
// metadata and payload. The producer observes load_ready before advancing its
// response or decoder; write_ready reflects the destination's weight ownership.
module tri_oracle_weight_write_buffer (
  input logic clk, rst_n,
  input logic [1:0] load_valid,
  output logic [1:0] load_ready, pending,
  input logic [1:0][4:0] load_core,
  input logic [1:0][9:0] load_addr,
  input logic [1:0][31:0] load_row_enable,
  input logic [1:0][1023:0] load_payload,
  input logic [1:0] write_ready,
  output logic [1:0] write_valid,
  output logic [1:0][4:0] write_core,
  output logic [1:0][9:0] write_addr,
  output logic [1:0][31:0] write_row_enable,
  output logic [1:0][1023:0] write_payload,
  input logic loader_done_valid, loader_done_error,
  output logic loader_done_ready,
  input logic done_ready,
  output logic done_valid, done_error
);
  logic [1:0] write_grant;

  weight_stream_write_arbiter arbiter (
    .clk, .rst_n, .offered(pending), .core(write_core), .memory_ready(write_ready),
    .granted(write_grant)
  );

  assign write_valid = {2{rst_n}} & pending & write_grant;
  assign load_ready = {2{rst_n}} & (~pending | write_valid);
  assign done_valid = rst_n && loader_done_valid && !(|pending) && !(|load_valid);
  assign done_error = done_valid && loader_done_error;
  assign loader_done_ready = done_valid && done_ready;

  for (genvar lane = 0; lane < 2; lane++) begin : gen_write_lane
    always_ff @(posedge clk or negedge rst_n) begin
      if (!rst_n) pending[lane] <= 0;
      else if (load_ready[lane]) pending[lane] <= load_valid[lane];
    end

    always_ff @(posedge clk) begin
      if (load_valid[lane] && load_ready[lane]) begin
        write_core[lane] <= load_core[lane];
        write_addr[lane] <= load_addr[lane];
        write_row_enable[lane] <= load_row_enable[lane];
        write_payload[lane] <= load_payload[lane];
      end
    end
  end
endmodule
