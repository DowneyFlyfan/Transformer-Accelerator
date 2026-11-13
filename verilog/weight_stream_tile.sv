`timescale 1ns/1ps
// One tile holds 32 write addresses, each with four 64-byte row groups.
// A packed pair starts with {width0, body_bytes0, width1, body_bytes1}.
// It then contains both code-and-literal bodies in that order.
module weight_stream_tile  (
  input logic clk, rst_n,
  input logic cfg_valid, cfg_raw, cfg_short,
  input logic [13:0] cfg_bytes,
  output logic cfg_ready,
  input logic rsp_valid, rsp_last, rsp_error,
  input logic [511:0] rsp_data,
  output logic rsp_ready,
  output logic write_valid,
  input logic write_ready,
  output logic [4:0] write_word,
  output logic [2047:0] write_data,
  output logic status_valid, status_error,
  input logic status_ready
);
  logic short_tile;
  wire [6:0] PAIR_COUNT=short_tile ? 7'd32 : 7'd64;
  wire [4:0] LAST_WRITE=short_tile ? 5'd15 : 5'd31;
  wire [13:0] RAW_BYTES=cfg_short ? 14'd4096 : 14'd8192;
  wire [13:0] MIN_PACKED_BYTES=cfg_short ? 14'd2176 : 14'd4352;
  wire [13:0] MAX_PACKED_BYTES=cfg_short ? 14'd4224 : 14'd8448;
  typedef enum logic [1:0] {Idle, Run, Abort, Done} state_t;
  state_t state;
  logic raw, ended, next_pair, pop, push, pair_ready, pair_out;
  logic header_present, pair_present;
  logic header_error, parse_error, response_error, decode_error;
  logic [13:0] bytes_unreceived, bytes_unparsed;
  logic [6:0] pairs_issued;
  logic [7:0] buffered, kept, pair_bytes;
  logic [6:0] incoming;
  logic [511:0] beats[3];
  logic [1:0] head_bank, tail_bank;
  logic [5:0] head_byte;
  logic [1:0] following_bank, final_bank;
  logic [8:0] head_sum;
  logic [8:0] next_head;
  logic [1535:0] head_beats;
  logic [1055:0] pair_window;
  logic [1023:0] pair_bodies, shifted_bodies;
  logic [7:0] first_padded_bytes, second_padded_bytes;
  logic [4:0] produced_word;
  logic [1023:0] first_pair;
  logic [1:0] decoder_in_ready, decoder_out_valid, decoder_out_error;
  logic [1:0][7:0] record_width, record_bytes;
  logic [1:0][3:0] width;
  logic [1:0][6:0] literal_count;
  logic [1:0][8:0] code_bits;
  logic [1:0][511:0] body, literal_data, decoded;
  logic [1:0][7:0] minimum_bytes;
  logic [1:0] header_ready;

  assign cfg_ready = state == Idle;
  assign status_valid = state == Done;
  assign incoming = bytes_unreceived > 64 ? 7'd64 : bytes_unreceived[6:0];
  assign kept = buffered - (pop ? pair_bytes : 8'd0);
  assign rsp_ready = !ended && (state == Abort || (state == Run && kept <= 128));
  assign push = rsp_valid && rsp_ready;
  assign response_error = push && (rsp_error || rsp_last != (bytes_unreceived <= 64));

  // Four-byte alignment bounds the head offset at 60 and the largest
  // pair at 132 bytes. Three 64-byte banks cover the entire read window.
  assign head_sum = {1'b0,head_bank,head_byte}+9'(pair_bytes);
  assign next_head = head_sum >= 192 ? head_sum - 9'd192 : head_sum;
  assign following_bank = head_bank == 2 ? 2'd0 : head_bank + 2'd1;
  assign final_bank = head_bank == 0 ? 2'd2 : head_bank - 2'd1;
  assign head_beats = {beats[head_bank], beats[following_bank], beats[final_bank]};
  assign pair_window = 1056'((head_beats << {head_byte[5:2],5'b0}) >> 480);
  assign record_width[0] = pair_window[1055 -: 8];
  assign record_bytes[0] = pair_window[1047 -: 8];
  assign record_width[1] = pair_window[1039 -: 8];
  assign record_bytes[1] = pair_window[1031 -: 8];
  assign first_padded_bytes = (record_bytes[0]+8'd3) & 8'hfc;
  assign second_padded_bytes = (record_bytes[1]+8'd3) & 8'hfc;
  assign pair_bytes = raw ? 8'd128 : 8'd4 + first_padded_bytes + second_padded_bytes;
  assign pair_bodies = pair_window[1023:0];
  assign shifted_bodies = pair_bodies << {first_padded_bytes[6:2],5'b0};
  assign body[0] = raw ? pair_window[1055 -: 512] : pair_bodies[1023 -: 512];
  assign body[1] = raw ? pair_window[543 -: 512] : shifted_bodies[1023 -: 512];
  for (genvar index=0; index<2; index++) begin : word_decoder
    assign width[index] = raw ? 4'd8 : record_width[index][3:0];
    assign minimum_bytes[index] = {1'b0,width[index],3'b0};
    assign code_bits[index] = {minimum_bytes[index][5:0],3'b0};
    assign literal_count[index] = width[index] == 8 ? 7'd0 :
        7'(record_bytes[index]-minimum_bytes[index]);
    assign literal_data[index] = body[index] << code_bits[index];
    assign header_ready[index] = record_width[index] >= 4 && record_width[index] <= 8 &&
        record_bytes[index] >= minimum_bytes[index] && record_bytes[index] <= 64;
    weight_decode_flush decoder (
      .clk, .rst_n, .flush(state != Run),
      .in_valid(pop), .in_ready(decoder_in_ready[index]), .out_ready(pair_ready),
      .width(width[index]), .expected_escapes(literal_count[index]),
      .codes(body[index]), .escapes(literal_data[index]),
      .out_valid(decoder_out_valid[index]), .out_error(decoder_out_error[index]),
      .weights(decoded[index])
    );
  end

  // Empty banks can still contain bytes from an earlier pair. Only use a
  // packed pair's length when its complete header is buffered.
  assign header_present = raw || buffered >= 4;
  assign header_error = !raw && header_present && !(&header_ready);
  assign pair_present = header_present && !header_error && buffered >= pair_bytes;
  assign parse_error = state == Run && pairs_issued < PAIR_COUNT &&
      (header_error || (ended && (!pair_present || bytes_unparsed < 14'(pair_bytes))) ||
       (pair_present && ((pairs_issued == PAIR_COUNT-7'd1) != (bytes_unparsed == 14'(pair_bytes)))));
  assign pop = state == Run && pairs_issued < PAIR_COUNT && !parse_error &&
      pair_present && (&decoder_in_ready);
  // With four-byte alignment, any incomplete pair of at most 132
  // bytes leaves at most 128 pending bytes. Write only whole beats.
  for (genvar bank=0; bank<3; bank++) begin : storage
    always_ff @(posedge clk) begin
      if (state==Run && push && tail_bank==2'(bank)) beats[bank] <= rsp_data;
    end
  end
  assign pair_ready = state == Run && (!next_pair || !write_valid || write_ready);
  assign pair_out = pair_ready && (&decoder_out_valid);
  assign decode_error = pair_out && (|decoder_out_error);

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state <= Idle;
      raw <= 0;
      short_tile <= 0;
      ended <= 0;
      buffered <= 0;
      bytes_unreceived <= 0;
      bytes_unparsed <= 0;
      pairs_issued <= 0;
      head_bank <= 0;
      head_byte <= 0;
      tail_bank <= 0;
      status_error <= 0;
      next_pair <= 0;
      produced_word <= 0;
      first_pair <= '0;
      write_valid <= 0;
      write_word <= 0;
      write_data <= '0;
    end else begin
      case (state)
        Idle: if (cfg_valid) begin
          raw <= cfg_raw;
          short_tile <= cfg_short;
          ended <= 0;
          buffered <= 0;
          bytes_unreceived <= cfg_bytes;
          bytes_unparsed <= cfg_bytes;
          pairs_issued <= 0;
          head_bank <= 0;
          head_byte <= 0;
          tail_bank <= 0;
          next_pair <= 0;
          produced_word <= 0;
          write_valid <= 0;
          if ((cfg_raw && cfg_bytes != RAW_BYTES) ||
              (!cfg_raw && (cfg_bytes < MIN_PACKED_BYTES || cfg_bytes > MAX_PACKED_BYTES))) begin
            status_error <= 1;
            state <= Done;
          end else begin
            status_error <= 0;
            state <= Run;
          end
        end
        Run: begin
          if (push) begin
            ended <= rsp_last;
            tail_bank <= tail_bank == 2 ? 2'd0 : tail_bank + 2'd1;
            bytes_unreceived <= bytes_unreceived - 14'(incoming);
          end
          if (push || pop) begin
            buffered <= kept + (push ? 8'(incoming) : 8'd0);
          end
          if (pop) begin
            {head_bank,head_byte} <= next_head[7:0];
            pairs_issued <= pairs_issued + 1'b1;
            bytes_unparsed <= bytes_unparsed - 14'(pair_bytes);
          end
          if (write_valid && write_ready) begin
            write_valid <= 0;
            if (write_word == LAST_WRITE) state <= Done;
          end
          if (pair_out && !decode_error) begin
            next_pair <= !next_pair;
            if (!next_pair) first_pair <= {decoded[1], decoded[0]};
            else begin
              write_data <= {decoded[1], decoded[0], first_pair};
              write_word <= produced_word;
              write_valid <= 1;
              produced_word <= produced_word + 1'b1;
            end
          end
          if (response_error || parse_error || decode_error) begin
            status_error <= 1;
            write_valid <= 0;
            state <= ended || (push && rsp_last) ? Done : Abort;
          end
        end
        Abort: if (push && rsp_last) state <= Done;
        Done: if (status_ready) state <= Idle;
        default: state <= Idle;
      endcase
    end
  end
endmodule
