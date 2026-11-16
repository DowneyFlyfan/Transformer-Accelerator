`timescale 1ns/1ps

// Capture a coherent sideband snapshot on a boundary control handshake.
// Request actions are 0: poll, 1: release override, 2: assert override.
// Replies are A684, snapshot low, snapshot high, and the action. The
// residual override is bit 27, and the sticky writeback error is bit 26.
// The other bits preserve the parallel projection/normalization status.
module tri_oracle_host_status_link (
  input logic clk, rst_n,
  input logic control_valid,
  input logic [1:0] control_action,
  output logic control_ready,
  input logic [26:0] chip_status,
  output logic residual_lease,
  input logic source_valid, source_last,
  input logic [15:0] source_data,
  output logic source_ready,
  input logic tx_ready,
  output logic tx_valid, tx_last,
  output logic [15:0] tx_data
);
  logic sticky_error, pending, source_in_progress;
  logic lease_after_request, accept_control, send_status;
  logic [1:0] word_index, action;
  logic [27:0] snapshot;

  assign control_ready = rst_n && !pending;
  assign accept_control = control_valid && control_ready;
  assign lease_after_request = control_action == 2'd2 ||
                              (control_action != 2'd1 && residual_lease);
  assign send_status = pending && !source_in_progress;
  assign source_ready = rst_n && !send_status && tx_ready;
  assign tx_valid = rst_n && (send_status || source_valid);
  assign tx_last = tx_valid && (send_status ? word_index == 2'd3 : source_last);

  always_comb begin
    tx_data = source_data;
    if (send_status) begin
      case (word_index)
        2'd0: tx_data = 16'ha684;
        2'd1: tx_data = snapshot[15:0];
        2'd2: tx_data = {4'b0, snapshot[27:16]};
        default: tx_data = {14'b0, action};
      endcase
    end
  end

  always_ff @(posedge clk)
    if (accept_control) begin
      snapshot <= {lease_after_request, sticky_error || chip_status[26], chip_status[25:0]};
      action <= control_action;
    end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      sticky_error <= 1'b0;
      residual_lease <= 1'b0;
      pending <= 1'b0;
      source_in_progress <= 1'b0;
      word_index <= '0;
    end else begin
      if (!send_status && source_valid)
        source_in_progress <= !(tx_ready && source_last);
      if (accept_control) begin
        sticky_error <= 1'b0;
        residual_lease <= lease_after_request;
        pending <= 1'b1;
      end else begin
        sticky_error <= sticky_error || chip_status[26];
        if (send_status && tx_ready) begin
          word_index <= word_index + 1'b1;
          if (tx_last) pending <= 1'b0;
        end
      end
    end
  end
endmodule
