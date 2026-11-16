`timescale 1ns/1ps

// Send least-significant flits first. The header is {length, port_class, compact}.
// Classes 0–3 are primary wide, auxiliary wide, primary narrow and projection.
// Two flits carry a 35-bit address in 64-byte units for wide reads and eight-byte
// units for narrow reads. Four flits carry any byte address.
// Lane zero occupies the low slice of each packed request port.
module tri_oracle_memory_request_tx (
  input logic clk, rst_n,
  input logic [2:0] req_valid,
  output logic [2:0] req_ready,
  input logic [191:0] req_address,
  input logic [17:0] req_length,
  input logic primary_wide,
  output logic tx_valid,
  input logic tx_ready,
  output logic [21:0] tx_data
);
  logic [1:0] prefer_lane, lane_on_wire, chosen_lane, port_class;
  logic [5:0] length;
  logic compact;
  logic [2:0] flits_left;
  logic [63:0] address, address_field;
  logic [72:0] packet, remaining_packet;

  always_comb begin
    case (prefer_lane)
      0: chosen_lane = req_valid[0] ? 2'd0 : (req_valid[1] ? 2'd1 : 2'd2);
      1: chosen_lane = req_valid[1] ? 2'd1 : (req_valid[2] ? 2'd2 : 2'd0);
      default: chosen_lane = req_valid[2] ? 2'd2 : (req_valid[0] ? 2'd0 : 2'd1);
    endcase
    case (chosen_lane)
      0: begin
        address = req_address[63:0];
        length = req_length[5:0];
        port_class = primary_wide ? 2'd0 : 2'd2;
      end
      1: begin
        address = req_address[127:64];
        length = req_length[11:6];
        port_class = 2'd1;
      end
      default: begin
        address = req_address[191:128];
        length = req_length[17:12];
        port_class = 2'd3;
      end
    endcase
  end

  assign compact = port_class[1] ? (address[63:38] == '0 && address[2:0] == '0) :
                                   (address[63:41] == '0 && address[5:0] == '0);
  assign address_field = !compact ? address :
                         (port_class[1] ? {29'd0, address[37:3]} : {29'd0, address[40:6]});
  assign packet = {address_field, length, port_class, compact};
  assign tx_valid = rst_n && ((flits_left != 0) || (|req_valid));
  assign tx_data = flits_left != 0 ? remaining_packet[21:0] : packet[21:0];
  assign req_ready = rst_n && tx_ready && flits_left == 1 ? (3'b001 << lane_on_wire) : '0;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      prefer_lane <= 0;
      lane_on_wire <= 0;
      flits_left <= 0;
    end else if (flits_left == 0 && |req_valid) begin
      lane_on_wire <= chosen_lane;
      prefer_lane <= chosen_lane == 2 ? 2'd0 : chosen_lane + 2'd1;
      flits_left <= (compact ? 3'd2 : 3'd4) - 3'(tx_ready);
    end else if (flits_left != 0 && tx_ready) begin
      flits_left <= flits_left - 3'd1;
    end
  end

  always_ff @(posedge clk) begin
    if (flits_left == 0 && |req_valid) begin
      remaining_packet <= tx_ready ? {22'd0, packet[72:22]} : packet;
    end else if (flits_left != 0 && tx_ready) begin
      remaining_packet <= {22'd0, remaining_packet[72:22]};
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
  output logic [2:0] req_valid,
  input logic [2:0] req_ready,
  output logic [191:0] req_address,
  output logic [17:0] req_length,
  output logic req_wide
);
  tri_oracle_memory_forward_rx read_only (
    .clk, .rst_n, .rx_valid, .rx_ready, .rx_data,
    .req_valid, .req_ready, .req_address, .req_length, .req_wide,
    .write_valid(), .write_ready(1'b1), .write_address(), .write_length(),
    .word_valid(), .word_ready(1'b1), .write_data(), .write_strobe(), .write_last()
  );
endmodule

module tri_oracle_memory_forward_rx (
  input logic clk, rst_n,
  input logic rx_valid,
  output logic rx_ready,
  input logic [21:0] rx_data,
  output logic [2:0] req_valid,
  input logic [2:0] req_ready,
  output logic [191:0] req_address,
  output logic [17:0] req_length,
  output logic req_wide,
  output logic write_valid,
  input logic write_ready,
  output logic [63:0] write_address,
  output logic [4:0] write_length,
  output logic word_valid,
  input logic word_ready,
  output logic [63:0] write_data,
  output logic [7:0] write_strobe,
  output logic write_last
);
  localparam logic [1:0] READ = 0, WRITE_HEADER = 1, WRITE_WORD = 2;
  logic [1:0] offset;
  logic [21:0] header_flit, middle_flit, upper_flit;
  logic [63:0] payload, incoming_payload, selected_payload;
  logic [7:0] attributes, selected_attributes;
  logic [1:0] lane, incoming_lane, selected_lane;
  logic [1:0] kind, incoming_kind, selected_kind;
  logic wide, incoming_wide, last, pending, compact, final_flit, retire_request, receive_flit, capture_request;
  logic incoming_ready, selected_ready, packet_valid;

  assign compact = header_flit[0];
  assign incoming_wide = !header_flit[2];
  assign incoming_lane = !header_flit[1] ? 2'd0 : (incoming_wide ? 2'd1 : 2'd2);
  assign incoming_kind = compact ? READ : rx_data[8:7];
  assign final_flit = offset == 3 || (offset == 1 && compact);
  assign incoming_ready = incoming_kind == WRITE_HEADER ? write_ready :
                          incoming_kind == WRITE_WORD ? word_ready : req_ready[incoming_lane];
  assign selected_ready = selected_kind == WRITE_HEADER ? write_ready :
                          selected_kind == WRITE_WORD ? word_ready : req_ready[selected_lane];
  assign retire_request = pending && selected_ready;
  assign rx_ready = rst_n && (!final_flit || !pending || retire_request);
  assign receive_flit = rx_valid && rx_ready;
  assign capture_request = receive_flit && final_flit && (pending || !incoming_ready);
  assign packet_valid = rst_n && (pending || (rx_valid && final_flit));
  assign selected_lane = pending ? lane : incoming_lane;
  assign selected_kind = pending ? kind : incoming_kind;
  assign req_valid = packet_valid && selected_kind == READ ? 3'b001 << selected_lane : '0;
  assign write_valid = packet_valid && selected_kind == WRITE_HEADER;
  assign word_valid = packet_valid && selected_kind == WRITE_WORD;
  assign incoming_payload = !compact ? {rx_data[6:0], upper_flit, middle_flit, header_flit[21:9]} :
                            incoming_wide ? {23'd0, rx_data, header_flit[21:9], 6'd0} :
                                            {26'd0, rx_data, header_flit[21:9], 3'd0};
  assign selected_payload = pending ? payload : incoming_payload;
  assign selected_attributes = pending ? attributes : header_flit[8:1];
  assign req_address = {3{selected_payload}};
  assign req_length = {3{selected_attributes[7:2]}};
  assign req_wide = pending ? wide : incoming_wide;
  assign write_address = selected_payload;
  assign write_length = selected_attributes[4:0];
  assign write_data = selected_payload;
  assign write_strobe = selected_attributes;
  assign write_last = pending ? last : rx_data[9];

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
        lane <= incoming_lane;
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
      attributes <= header_flit[8:1];
      payload <= incoming_payload;
      wide <= incoming_wide;
      kind <= incoming_kind;
      last <= rx_data[9];
    end
  end
endmodule
