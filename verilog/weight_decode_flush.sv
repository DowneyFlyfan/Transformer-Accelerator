`timescale 1ns/1ps
module weight_decode_flush (
  input logic clk, rst_n, flush, in_valid, out_ready,
  input logic [3:0] width,
  input logic [6:0] expected_escapes,
  input logic [511:0] codes, escapes,
  output logic in_ready, out_valid, out_error,
  output logic [511:0] weights
);
  logic valid, window_valid, advance;
  logic [511:0] decoded_window_stage;
  logic [63:0] flags_window_stage;
  logic [63:0][2:0] rank_window_stage;
  logic [7:0][63:0] group_literals, literals_window_stage;
  logic window_error;
  logic [511:0] decoded, literals, decoded_stage, literals_stage, assembled;
  logic [63:0] escape_flags, flags_stage;
  logic [63:0][2:0] local_rank, rank_stage;
  logic [7:0][3:0] group_count, group_count_stage;
  logic [7:0][6:0] group_offset;
  logic [6:0] total, expected_stage;
  logic valid_width, invalid_width_stage;

  assign advance = !out_valid || out_ready;
  assign in_ready = rst_n && !flush && advance;

  always_comb begin
    valid_width = width >= 4 && width <= 8;
    decoded = '0;
    escape_flags = '0;
    for (int lane = 0; lane < 64; lane++) begin
      // Invert the sign bit and sign-extend, then add one. This is
      // code minus the positive bias for every packed width.
      logic [7:0] signed_code;
      logic all_ones;
      signed_code=0;
      all_ones=0;
      case (width)
        4: begin
          signed_code=8'($signed(codes[511-4*lane -: 4]^4'h8));
          all_ones=&codes[511-4*lane -: 4];
        end
        5: begin
          signed_code=8'($signed(codes[511-5*lane -: 5]^5'h10));
          all_ones=&codes[511-5*lane -: 5];
        end
        6: begin
          signed_code=8'($signed(codes[511-6*lane -: 6]^6'h20));
          all_ones=&codes[511-6*lane -: 6];
        end
        7: begin
          signed_code=8'($signed(codes[511-7*lane -: 7]^7'h40));
          all_ones=&codes[511-7*lane -: 7];
        end
        8: signed_code=codes[511-8*lane -: 8];
        default: signed_code=0;
      endcase
      decoded[511-8*lane -: 8]=signed_code+8'(width<8);
      escape_flags[lane]=all_ones;
    end
    literals = escapes;
    for (int group = 0; group < 8; group++) begin
      group_count[group] = 0;
      for (int lane = 0; lane < 8; lane++) begin
        local_rank[group*8+lane] = 3'(group_count[group]);
        group_count[group] += 4'(escape_flags[group*8+lane]);
      end
    end
  end

  always_comb begin
    total = 0;
    for (int group = 0; group < 8; group++) begin
      group_offset[group] = total;
      total += 7'(group_count_stage[group]);
    end
    // Each group consumes at most eight consecutive literals. Share the
    // stream alignment across its eight lanes before indexing local ranks.
    for (int group = 0; group < 8; group++) begin
      logic [127:0] pair;
      case (group_offset[group][5:3])
        0: pair = literals_stage[511:384];
        1: pair = literals_stage[447:320];
        2: pair = literals_stage[383:256];
        3: pair = literals_stage[319:192];
        4: pair = literals_stage[255:128];
        5: pair = literals_stage[191:64];
        6: pair = literals_stage[127:0];
        7: pair = {literals_stage[63:0],64'b0};
        default: pair = '0;
      endcase
      pair <<= {group_offset[group][2:0],3'b0};
      group_literals[group] = pair[127:64];
    end
  end

  always_comb begin
    assembled = decoded_window_stage;
    for (int lane = 0; lane < 64; lane++) begin
      if (flags_window_stage[lane])
        assembled[511-8*lane -: 8] =
          literals_window_stage[lane/8][{~rank_window_stage[lane],3'b000} +: 8];
    end
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      valid <= 0;
      window_valid <= 0;
      decoded_window_stage <= '0;
      flags_window_stage <= '0;
      rank_window_stage <= '0;
      literals_window_stage <= '0;
      window_error <= 0;
      out_valid <= 0;
      out_error <= 0;
      weights <= '0;
      decoded_stage <= '0;
      literals_stage <= '0;
      flags_stage <= '0;
      rank_stage <= '0;
      group_count_stage <= '0;
      invalid_width_stage <= 0;
      expected_stage <= '0;
    end else if (flush) begin
      valid <= 0;
      window_valid <= 0;
      decoded_window_stage <= '0;
      flags_window_stage <= '0;
      rank_window_stage <= '0;
      literals_window_stage <= '0;
      window_error <= 0;
      out_valid <= 0;
      out_error <= 0;
      weights <= '0;
      decoded_stage <= '0;
      literals_stage <= '0;
      flags_stage <= '0;
      rank_stage <= '0;
      group_count_stage <= '0;
      invalid_width_stage <= 0;
      expected_stage <= '0;
    end else if (advance) begin
      valid <= in_valid;
      window_valid <= valid;
      out_valid <= window_valid;
      if (in_valid) begin
        decoded_stage <= decoded;
        literals_stage <= literals;
        flags_stage <= escape_flags;
        rank_stage <= local_rank;
        group_count_stage <= group_count;
        invalid_width_stage <= !valid_width;
        expected_stage <= expected_escapes;
      end
      if (valid) begin
        decoded_window_stage <= decoded_stage;
        flags_window_stage <= flags_stage;
        rank_window_stage <= rank_stage;
        literals_window_stage <= group_literals;
        window_error <= invalid_width_stage || total != expected_stage;
      end
      if (window_valid) begin
        out_error <= window_error;
        weights <= window_error ? '0 : assembled;
      end
    end
  end
endmodule
