`timescale 1ns/1ps

// A write uses four flits with type in bits [74:73], which read packets leave
// zero. The low flit still has the existing compact flag clear. Write headers
// carry a five-bit length and a byte address. Write words carry the byte mask,
// data and last flag. Arbitration can switch streams at every packet boundary.
module tri_oracle_memory_write_link_tx (
  input logic clk, rst_n,
  input logic rd_valid,
  output logic rd_ready,
  input logic [21:0] rd_data,
  input logic write_valid,
  output logic write_ready,
  input logic [63:0] write_address,
  input logic [4:0] write_length,
  input logic word_valid,
  output logic word_ready,
  input logic [63:0] write_data,
  input logic [7:0] write_strobe,
  input logic write_last,
  output logic tx_valid,
  input logic tx_ready,
  output logic [21:0] tx_data
);
  logic [2:0] flits_left;
  logic write_open, prefer_write, writing, word_on_wire, more_words;
  logic write_available, select_write, use_write, send_flit;
  logic [75:0] write_packet, write_shift;

  assign write_available = write_open ? word_valid : write_valid;
  assign select_write = write_available && (!rd_valid || prefer_write);
  assign use_write = flits_left != 0 ? writing : select_write;
  assign write_packet = write_open ? {write_last, 2'd2, write_data, write_strobe, 1'b0} :
                                     {1'b0, 2'd1, write_address, 3'd0, write_length, 1'b0};
  assign tx_valid = rst_n && (use_write ? (flits_left != 0 || write_available) : rd_valid);
  assign tx_data = use_write ? (flits_left != 0 ? write_shift[21:0] : write_packet[21:0]) : rd_data;
  assign send_flit = tx_valid && tx_ready;
  assign rd_ready = rst_n && !use_write && tx_ready;
  assign write_ready = send_flit && writing && flits_left == 1 && !word_on_wire;
  assign word_ready = send_flit && writing && flits_left == 1 && word_on_wire;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      flits_left <= 0;
      write_open <= 0;
      prefer_write <= 0;
      writing <= 0;
      word_on_wire <= 0;
      more_words <= 0;
    end else if (flits_left == 0 && tx_valid) begin
      flits_left <= (!select_write && rd_data[0] ? 3'd2 : 3'd4) - 3'(send_flit);
      prefer_write <= !select_write;
      writing <= select_write;
      word_on_wire <= write_open;
      more_words <= write_open ? !write_last : write_length != 0;
    end else if (send_flit) begin
      flits_left <= flits_left - 3'd1;
      if (writing && flits_left == 1) write_open <= more_words;
    end
  end

  always_ff @(posedge clk) begin
    if (flits_left == 0 && tx_valid && select_write)
      write_shift <= send_flit ? {22'd0, write_packet[75:22]} : write_packet;
    else if (send_flit && writing)
      write_shift <= {22'd0, write_shift[75:22]};
  end
endmodule
