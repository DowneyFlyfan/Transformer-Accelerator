`timescale 1ns/1ps

// At a record boundary, rx_is_payload=0 and rx_payload_last=1 allow a
// rotary header (A670, or A671 for the last vector). Its 64 data transfers
// carry the cosine bits first, then the sine bits, least significant word first.
// Commands and payloads keep the framing of tri_oracle_host_command_link.
module tri_oracle_host_rotary_rx (
  input logic clk, rst_n,
  input logic rx_valid,
  output logic rx_ready,
  input logic rx_is_payload, rx_payload_last,
  input logic [15:0] rx_data,
  output logic link_valid,
  input logic link_ready,
  output logic angle_valid,
  input logic angle_ready,
  output logic angle_last,
  output logic [1023:0] angle_data
);
  typedef enum logic [1:0] {RecordStart, HostBody, RotaryBody, RotaryPending} state_t;
  state_t state;
  logic [1:0] host_words_left;
  logic [5:0] rotary_index;
  logic rotary_header, ordinary, transfer;

  assign rotary_header = !rx_is_payload && rx_payload_last && rx_data[15:1] == 15'h5338;
  assign ordinary = state == HostBody || (state == RecordStart && !rotary_header);
  assign link_valid = rst_n && ordinary && rx_valid;
  assign rx_ready = rst_n && (ordinary ? link_ready : state != RotaryPending);
  assign angle_valid = rst_n && state == RotaryPending;
  assign transfer = rx_valid && rx_ready;

  // Each word is filled before publication. The pending vector stays stable
  // until the projection engine accepts it, with no reset needed on data bits.
  for (genvar word = 0; word < 64; word++) begin : words
    always_ff @(posedge clk)
      if (state == RotaryBody && transfer && rotary_index == 6'(word))
        angle_data[word * 16 +: 16] <= rx_data;
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state <= RecordStart;
      host_words_left <= 0;
      rotary_index <= 0;
      angle_last <= 0;
    end else case (state)
      RecordStart: if (transfer) begin
        if (rotary_header) begin
          rotary_index <= 0;
          angle_last <= rx_data[0];
          state <= RotaryBody;
        end else begin
          host_words_left <= rx_is_payload ? 2'd3 : 2'd2;
          state <= HostBody;
        end
      end
      HostBody: if (transfer) begin
        host_words_left <= host_words_left - 1'b1;
        if (host_words_left == 1) state <= RecordStart;
      end
      RotaryBody: if (transfer) begin
        rotary_index <= rotary_index + 1'b1;
        if (rotary_index == 63) state <= RotaryPending;
      end
      RotaryPending: if (angle_ready) state <= RecordStart;
      default: state <= RecordStart;
    endcase
  end
endmodule
