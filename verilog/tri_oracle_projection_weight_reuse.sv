`timescale 1ns/1ps
// Protect resident weights while an in-order, strip-major projection reads them.
// A strip is released on acceptance of its last token's memory read. The write
// port can use that address starting on the next cycle, even with results pending.
// The loader must still complete all writes before reserving those new weights.
module tri_oracle_projection_weight_reuse (
  input logic clk, rst_n,
  input logic discard,
  input logic reserve,
  input logic [4:0] reserve_base,
  input logic [5:0] reserve_strips,
  input logic last_read,
  input logic [4:0] read_word,
  input logic [4:0] write_word,
  output logic write_allowed
);
  logic [5:0] first_unread, end_exclusive;
  logic [6:0] requested_end;
  logic invalid_reservation, reserved_word, incoming_word;

  assign requested_end = 7'(reserve_base) + 7'(reserve_strips);
  assign invalid_reservation = reserve_strips == 0 || requested_end > 7'd32 ||
                               first_unread < end_exclusive;
  assign reserved_word = 6'(write_word) >= first_unread && 6'(write_word) < end_exclusive;
  assign incoming_word = write_word >= reserve_base && 7'(write_word) < requested_end;
  assign write_allowed = rst_n && !discard && !reserved_word &&
                         !(reserve && (invalid_reservation || incoming_word));

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      first_unread <= '0;
      end_exclusive <= '0;
    end else if (discard) begin
      first_unread <= '0;
      end_exclusive <= '0;
    end else if (reserve) begin
      // Until discard, a malformed or overlapping reservation protects all words.
      first_unread <= invalid_reservation ? 6'd0 : 6'(reserve_base);
      end_exclusive <= invalid_reservation ? 6'd63 : 6'(requested_end);
    end else if (last_read && first_unread == 6'(read_word) &&
                 first_unread < end_exclusive && end_exclusive <= 6'd32) begin
      first_unread <= first_unread + 6'd1;
    end
  end
endmodule
