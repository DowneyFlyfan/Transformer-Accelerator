`timescale 1ns/1ps

// The peer uses response lane zero for primary and projection reads and for
// terminal write acknowledgments. Lane one carries auxiliary read responses.
// A write takes lane zero after any offered or accepted read has drained.
module tri_oracle_memory_io_link (
  input logic clk, rst_n,
  input logic [2:0] req_valid,
  output logic [2:0] req_ready,
  input logic [191:0] req_address,
  input logic [17:0] req_length,
  input logic primary_wide,
  output logic [2:0] rsp_valid,
  input logic [2:0] rsp_ready,
  output logic [2:0] rsp_last, rsp_error,
  output logic [1087:0] rsp_data,
  input logic wr_req_valid,
  output logic wr_req_ready,
  input logic [63:0] wr_address,
  input logic [4:0] wr_length,
  input logic wr_data_valid,
  output logic wr_data_ready,
  input logic [63:0] wr_data,
  input logic [7:0] wr_strobe,
  input logic wr_data_last,
  output logic wr_rsp_valid,
  input logic wr_rsp_ready,
  output logic wr_rsp_error,
  output logic tx_valid,
  input logic tx_ready,
  output logic [21:0] tx_data,
  input logic [1:0] mem_rsp_valid,
  output logic [1:0] mem_rsp_ready,
  input logic [1:0] mem_rsp_last, mem_rsp_error,
  input logic [1023:0] mem_rsp_data
);
  typedef enum logic [1:0] {ReadAvailable, ReserveWrite, WriteData, WriteAck} write_state_t;
  write_state_t state;
  logic prefer_write, write_intent, block_new_shared, shared_can_write, write_owns_response;
  logic rd_valid, rd_ready, header_valid;
  logic [21:0] rd_data;
  logic [1:0] read_rsp_ready, read_rsp_valid;

  assign write_intent = state == ReadAvailable && wr_req_valid &&
                        (prefer_write || !(req_valid[0] || req_valid[2]));
  assign block_new_shared = state != ReadAvailable || write_intent;
  assign header_valid = shared_can_write && wr_req_valid && (write_intent || state == ReserveWrite);
  assign write_owns_response = state == WriteData || state == WriteAck;
  assign read_rsp_valid = {mem_rsp_valid[1], mem_rsp_valid[0] && !write_owns_response};
  assign mem_rsp_ready = {read_rsp_ready[1], write_owns_response ?
                          (state == WriteAck && mem_rsp_last[0] && wr_rsp_ready) : read_rsp_ready[0]};
  assign wr_rsp_valid = state == WriteAck && mem_rsp_valid[0] && mem_rsp_last[0];
  assign wr_rsp_error = mem_rsp_error[0];

  tri_oracle_shared_read_core reads (
    .clk, .rst_n, .req_valid, .req_ready, .req_address, .req_length, .primary_wide,
    .rsp_valid, .rsp_ready, .rsp_last, .rsp_error, .rsp_data,
    .tx_valid(rd_valid), .tx_ready(rd_ready), .tx_data(rd_data),
    .mem_rsp_valid(read_rsp_valid), .mem_rsp_ready(read_rsp_ready),
    .mem_rsp_last, .mem_rsp_error, .mem_rsp_data, .block_new_shared, .shared_can_write
  );
  tri_oracle_memory_write_link_tx forward (
    .clk, .rst_n, .rd_valid, .rd_ready, .rd_data,
    .write_valid(header_valid), .write_ready(wr_req_ready), .write_address(wr_address),
    .write_length(wr_length), .word_valid(wr_data_valid), .word_ready(wr_data_ready),
    .write_data(wr_data), .write_strobe(wr_strobe), .write_last(wr_data_last),
    .tx_valid, .tx_ready, .tx_data
  );

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state <= ReadAvailable;
      prefer_write <= 0;
    end else begin
      if ((req_valid[0] && req_ready[0]) || (req_valid[2] && req_ready[2])) prefer_write <= 1;
      case (state)
        ReadAvailable: if (write_intent) state <= ReserveWrite;
        ReserveWrite: if (wr_req_ready) begin
          prefer_write <= 0;
          state <= wr_length == 0 ? WriteAck : WriteData;
        end
        WriteData: if (wr_data_valid && wr_data_ready && wr_data_last) state <= WriteAck;
        WriteAck: if (wr_rsp_valid && wr_rsp_ready) state <= ReadAvailable;
      endcase
    end
  end
endmodule
