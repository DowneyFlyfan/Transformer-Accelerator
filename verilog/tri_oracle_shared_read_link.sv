`timescale 1ns/1ps

// Primary and projection reads share response lane zero. The auxiliary port
// keeps lane one. The remote endpoint must use that same fixed mapping.
// Projection consumes the low 64 bits of lane zero.
module tri_oracle_shared_read_link (
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
  output logic tx_valid,
  input logic tx_ready,
  output logic [21:0] tx_data,
  input logic [1:0] mem_rsp_valid,
  output logic [1:0] mem_rsp_ready,
  input logic [1:0] mem_rsp_last, mem_rsp_error,
  input logic [1023:0] mem_rsp_data
);
  tri_oracle_shared_read_core reads (
    .clk, .rst_n, .req_valid, .req_ready, .req_address, .req_length, .primary_wide,
    .rsp_valid, .rsp_ready, .rsp_last, .rsp_error, .rsp_data, .tx_valid, .tx_ready, .tx_data,
    .mem_rsp_valid, .mem_rsp_ready, .mem_rsp_last, .mem_rsp_error, .mem_rsp_data,
    .block_new_shared(1'b0), .shared_can_write()
  );
endmodule

module tri_oracle_shared_read_core (
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
  output logic tx_valid,
  input logic tx_ready,
  output logic [21:0] tx_data,
  input logic [1:0] mem_rsp_valid,
  output logic [1:0] mem_rsp_ready,
  input logic [1:0] mem_rsp_last, mem_rsp_error,
  input logic [1023:0] mem_rsp_data,
  input logic block_new_shared,
  output logic shared_can_write
);
  logic shared_active, auxiliary_active, projection_owner, prefer_projection;
  logic offer_pending, pending_projection, offer_projection;
  logic shared_tail, auxiliary_tail, shared_available, shared_read_permitted;
  logic [2:0] permitted_valid, request_transfer;

  assign mem_rsp_ready[0] = shared_active && (projection_owner ? rsp_ready[2] : rsp_ready[0]);
  assign mem_rsp_ready[1] = auxiliary_active && rsp_ready[1];
  assign rsp_valid[0] = shared_active && !projection_owner && mem_rsp_valid[0];
  assign rsp_valid[1] = auxiliary_active && mem_rsp_valid[1];
  assign rsp_valid[2] = shared_active && projection_owner && mem_rsp_valid[0];
  assign rsp_last = {mem_rsp_last[0], mem_rsp_last};
  assign rsp_error = {mem_rsp_error[0], mem_rsp_error};
  assign rsp_data = {mem_rsp_data[63:0], mem_rsp_data};

  assign shared_tail = mem_rsp_valid[0] && mem_rsp_ready[0] && mem_rsp_last[0];
  assign auxiliary_tail = mem_rsp_valid[1] && mem_rsp_ready[1] && mem_rsp_last[1];
  assign shared_available = !shared_active || shared_tail;
  assign shared_can_write = shared_available && !offer_pending;
  assign shared_read_permitted = shared_available && (!block_new_shared || offer_pending);
  assign offer_projection = offer_pending ? pending_projection :
                            (req_valid[2] && (!req_valid[0] || prefer_projection));
  assign permitted_valid[0] = shared_read_permitted && !offer_projection && req_valid[0];
  assign permitted_valid[1] = (!auxiliary_active || auxiliary_tail) && req_valid[1];
  assign permitted_valid[2] = shared_read_permitted && offer_projection && req_valid[2];
  assign request_transfer = permitted_valid & req_ready;

  tri_oracle_memory_request_tx request_tx (
    .clk, .rst_n, .req_valid(permitted_valid), .req_ready, .req_address, .req_length,
    .primary_wide, .tx_valid, .tx_ready, .tx_data
  );

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      shared_active <= 0;
      auxiliary_active <= 0;
      projection_owner <= 0;
      prefer_projection <= 0;
      offer_pending <= 0;
      pending_projection <= 0;
    end else begin
      if (shared_tail) shared_active <= 0;
      if (auxiliary_tail) auxiliary_active <= 0;
      if (request_transfer[1]) auxiliary_active <= 1;
      if (request_transfer[0] || request_transfer[2]) begin
        shared_active <= 1;
        projection_owner <= request_transfer[2];
        prefer_projection <= request_transfer[0];
        offer_pending <= 0;
      end else if (!offer_pending && (permitted_valid[0] || permitted_valid[2])) begin
        offer_pending <= 1;
        pending_projection <= offer_projection;
      end
    end
  end
endmodule
