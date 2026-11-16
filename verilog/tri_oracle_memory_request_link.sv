`timescale 1ns/1ps

// Send least-significant flits first. The header is {length, lane, compact}.
// The two-flit format carries a 36-bit address in 64-byte units. The four-flit
// format carries the complete byte address and pads its final flit with zeros.
// Lane zero occupies the low slice of each packed request port.
module tri_oracle_memory_request_tx (
  input logic clk, rst_n,
  input logic [1:0] req_valid,
  output logic [1:0] req_ready,
  input logic [127:0] req_address,
  input logic [11:0] req_length,
  output logic tx_valid,
  input logic tx_ready,
  output logic [21:0] tx_data
);
  logic prefer_lane, lane_on_wire, chosen_lane, compact;
  logic [2:0] flits_left;
  logic [63:0] address, address_field;
  logic [71:0] packet, remaining_packet;

  assign chosen_lane = req_valid[prefer_lane] ? prefer_lane : !prefer_lane;
  assign address = chosen_lane ? req_address[127:64] : req_address[63:0];
  assign compact = address[63:42] == '0 && address[5:0] == '0;
  assign address_field = compact ? {28'd0, address[41:6]} : address;
  assign packet = {address_field, (chosen_lane ? req_length[11:6] : req_length[5:0]), chosen_lane, compact};
  assign tx_valid = rst_n && ((flits_left != 0) || (|req_valid));
  assign tx_data = flits_left != 0 ? remaining_packet[21:0] : packet[21:0];
  assign req_ready = rst_n && tx_ready && flits_left == 1 ? (2'b01 << lane_on_wire) : '0;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      prefer_lane <= 0;
      lane_on_wire <= 0;
      flits_left <= 0;
    end else if (flits_left == 0 && |req_valid) begin
      lane_on_wire <= chosen_lane;
      prefer_lane <= !chosen_lane;
      flits_left <= (compact ? 3'd2 : 3'd4) - 3'(tx_ready);
    end else if (flits_left != 0 && tx_ready) begin
      flits_left <= flits_left - 3'd1;
    end
  end

  always_ff @(posedge clk) begin
    if (flits_left == 0 && |req_valid) begin
      remaining_packet <= tx_ready ? {22'd0, packet[71:22]} : packet;
    end else if (flits_left != 0 && tx_ready) begin
      remaining_packet <= {22'd0, remaining_packet[71:22]};
    end
  end
endmodule

// One recovered request can wait for the memory port while the next packet
// begins arriving. A stalled recovered request holds its lane, address and length.
module tri_oracle_memory_request_rx (
  input logic clk, rst_n,
  input logic rx_valid,
  output logic rx_ready,
  input logic [21:0] rx_data,
  output logic [1:0] req_valid,
  input logic [1:0] req_ready,
  output logic [127:0] req_address,
  output logic [11:0] req_length
);
  logic [1:0] offset;
  logic [21:0] header_flit, middle_flit, upper_flit;
  logic [63:0] address, incoming_address, selected_address;
  logic [5:0] length;
  logic [5:0] selected_length;
  logic lane, pending, compact, final_flit, retire_request, receive_flit, capture_request;

  assign compact = header_flit[0];
  assign final_flit = offset == 3 || (offset == 1 && compact);
  assign retire_request = pending && req_ready[lane];
  assign rx_ready = rst_n && (!final_flit || !pending || retire_request);
  assign receive_flit = rx_valid && rx_ready;
  assign capture_request = receive_flit && final_flit && (pending || !req_ready[header_flit[1]]);
  assign req_valid = !rst_n ? '0 : pending ? (2'b01 << lane) :
                     (rx_valid && final_flit ? (2'b01 << header_flit[1]) : '0);
  assign incoming_address = compact ? {22'd0, rx_data, header_flit[21:8], 6'd0} :
                                      {rx_data[5:0], upper_flit, middle_flit, header_flit[21:8]};
  assign selected_address = pending ? address : incoming_address;
  assign selected_length = pending ? length : header_flit[7:2];
  assign req_address = {selected_address, selected_address};
  assign req_length = {selected_length, selected_length};

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      offset <= 0;
      pending <= 0;
      lane <= 0;
    end else begin
      if (retire_request) pending <= 0;
      if (receive_flit)
        offset <= final_flit ? 2'd0 : offset + 2'd1;
      if (capture_request) begin
        pending <= 1;
        lane <= header_flit[1];
      end
    end
  end

  always_ff @(posedge clk) begin
    if (receive_flit) begin
      case (offset)
        0: header_flit <= rx_data;
        1: middle_flit <= rx_data;
        2: upper_flit <= rx_data;
        default: ;
      endcase
    end
    if (capture_request) begin
      length <= header_flit[7:2];
      address <= incoming_address;
    end
  end
endmodule
