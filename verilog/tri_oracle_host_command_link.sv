`timescale 1ns/1ps

// Synchronous 16-bit host interface for the existing command dispatcher.
// Send the lowest word first. A command comprises {13'b0, opcode, tag}
// in three transfers. A payload record comprises one 64-bit word in four
// transfers. Only the first transfer uses rx_is_payload and rx_payload_last.
// Responses comprise {12'b0, error, opcode, tag} in three transfers.
module tri_oracle_host_command_link (
  input logic clk, rst_n,
  input logic rx_valid,
  output logic rx_ready,
  input logic rx_is_payload, rx_payload_last,
  input logic [15:0] rx_data,
  output logic tx_valid,
  input logic tx_ready,
  output logic tx_last,
  output logic [15:0] tx_data,
  output logic command_valid,
  input logic command_ready,
  output logic [2:0] command_opcode,
  output logic [31:0] command_tag,
  output logic payload_valid,
  input logic payload_ready,
  output logic [63:0] payload_data,
  output logic payload_last,
  input logic response_valid,
  output logic response_ready,
  input logic response_error,
  input logic [2:0] response_opcode,
  input logic [31:0] response_tag
);
  logic [1:0] receive_index, transmit_index;
  logic [63:0] receive_record;
  logic record_ready, payload_record, last_payload_record;
  logic receive_transfer, current_record_accepted;

  assign rx_ready = rst_n && !record_ready;
  assign receive_transfer = rx_valid && rx_ready;
  assign command_valid = record_ready && !payload_record;
  assign {command_opcode, command_tag} = receive_record[34:0];
  assign payload_valid = record_ready && payload_record;
  assign payload_data = receive_record;
  assign payload_last = last_payload_record;
  assign current_record_accepted = (command_valid && command_ready) ||
                                   (payload_valid && payload_ready);

  // An incomplete record is never valid. Each record writes all its used
  // bits before setting record_ready.
  always_ff @(posedge clk) begin
    if (receive_transfer) receive_record[{receive_index, 4'b0} +: 16] <= rx_data;
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      receive_index <= 0;
      record_ready <= 0;
      payload_record <= 0;
      last_payload_record <= 0;
    end else if (receive_transfer) begin
      if (receive_index == 0) begin
        payload_record <= rx_is_payload;
        last_payload_record <= rx_payload_last;
      end
      if (receive_index == (payload_record ? 2'd3 : 2'd2)) begin
        record_ready <= 1;
        receive_index <= 0;
      end else begin
        receive_index <= receive_index + 1'b1;
      end
    end else if (current_record_accepted) begin
      record_ready <= 0;
    end
  end

  // The dispatcher holds the response stable until ready. Acknowledge it
  // when the last transfer leaves the link, preserving command ownership.
  assign tx_valid = rst_n && response_valid;
  assign tx_last = tx_valid && transmit_index == 2;
  assign response_ready = tx_last && tx_ready;
  always_comb begin
    case (transmit_index)
      2'd0: tx_data = response_tag[15:0];
      2'd1: tx_data = response_tag[31:16];
      default: tx_data = {12'd0, response_error, response_opcode};
    endcase
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) transmit_index <= 0;
    else if (tx_valid && tx_ready) begin
      transmit_index <= tx_last ? 2'd0 : transmit_index + 1'b1;
    end
  end
endmodule
