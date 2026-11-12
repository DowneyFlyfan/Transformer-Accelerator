`timescale 1ns/1ps

// Schedules a contiguous output tile from the packed down-projection matrix.
// The caller owns the fabric until completion. An error invalidates staged
// weights. The activation mask has 32 bits per input partition in core order.
module tri_oracle_packed_weight_schedule (
  input  logic clk, rst_n,
  input  logic cfg_valid,
  output logic cfg_ready,
  input  logic [63:0] cfg_base,
  input  logic [15:0] cfg_first_row,
  input  logic [16:0] cfg_dense_rows,
  input  logic [9:0] cfg_feature_words,
  input  logic [7:0] cfg_count, cfg_tile_start,
  input  logic [159:0] cfg_keep,
  input  logic [127:0] cfg_active_words,

  output logic load_cfg_valid,
  input  logic load_cfg_ready,
  output logic [63:0] load_cfg_address,
  output logic [4:0] load_cfg_core, load_cfg_first_word,
  output logic [1:0] load_cfg_row_group,
  output logic [7:0] load_cfg_row_enable,
  output logic [5:0] load_cfg_words,
  input  logic load_done_valid, load_done_error,
  output logic load_done_ready,

  output logic done_valid,
  input  logic done_ready,
  output logic done_error
);
  typedef enum logic [2:0] {Idle, Initialize, Find, Offer, Await, Done} state_t;
  state_t state;

  logic [63:0] group_base, part_base;
  logic [29:0] first_byte_offset;
  logic [15:0] group_stride;
  logic [13:0] part_stride;
  logic [127:0] active_words;
  logic [159:0] keep;
  logic [4:0] group_index;
  logic [1:0] part_index;
  logic [5:0] word_index, group_count;
  logic [7:0] row_enable;
  logic [31:0] remaining_active;

  logic [23:0] first_beat, matrix_beats;
  logic [8:0] remaining_part_words;
  logic [5:0] tile_words;
  logic [31:0] tile_mask;
  logic [64:0] matrix_end;
  logic invalid;

  function automatic logic [5:0] active_run(input logic [31:0] mask);
    active_run = 6'd32;
    for (int word = 31; word >= 0; word--)
      if (!mask[word]) active_run = 6'(word);
  endfunction

  assign first_beat = 24'(cfg_first_row[15:3]) * 24'(cfg_feature_words) + 24'(cfg_tile_start);
  assign matrix_beats = 24'(cfg_dense_rows[16:3]) * 24'(cfg_feature_words);
  assign matrix_end = {1'b0, cfg_base} + (65'(matrix_beats) << 6) - 65'd1;
  assign remaining_part_words = 9'(cfg_feature_words[9:2]) - 9'(cfg_tile_start);
  assign tile_words = remaining_part_words > 32 ? 6'd32 : 6'(remaining_part_words);
  assign tile_mask = 32'hffffffff >> (6'd32 - tile_words);
  assign invalid = cfg_base[5:0] != 0 || cfg_first_row[2:0] != 0 ||
                   cfg_dense_rows == 0 || cfg_dense_rows > 17'd65536 || cfg_dense_rows[2:0] != 0 ||
                   cfg_count == 0 || cfg_count > 160 ||
                   17'(cfg_first_row) + 17'(cfg_count) > cfg_dense_rows ||
                   cfg_feature_words < 4 || cfg_feature_words[1:0] != 0 ||
                   cfg_tile_start >= cfg_feature_words[9:2] || matrix_end[64];

  assign row_enable = keep[{group_index, 3'b000} +: 8];
  assign remaining_active = active_words[{part_index, 5'b00000} +: 32] >> word_index;
  assign cfg_ready = rst_n && state == Idle;
  assign load_cfg_valid = rst_n && state == Offer;
  assign load_done_ready = rst_n && state == Await;
  assign done_valid = rst_n && state == Done;
  assign load_cfg_core = {group_index[4:2], part_index};
  assign load_cfg_row_group = group_index[1:0];
  assign load_cfg_row_enable = row_enable;
  assign load_cfg_first_word = word_index[4:0];

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state <= Idle;
      group_base <= 0;
      part_base <= 0;
      first_byte_offset <= 0;
      group_stride <= 0;
      part_stride <= 0;
      active_words <= 0;
      keep <= 0;
      group_index <= 0;
      part_index <= 0;
      word_index <= 0;
      group_count <= 0;
      load_cfg_address <= 0;
      load_cfg_words <= 0;
      done_error <= 0;
    end else begin
      case (state)
        Idle: if (cfg_valid) begin
          group_base <= cfg_base;
          first_byte_offset <= {first_beat, 6'b0};
          group_stride <= {cfg_feature_words, 6'b0};
          part_stride <= {cfg_feature_words[9:2], 6'b0};
          active_words <= cfg_active_words & {4{tile_mask}};
          for (int row = 0; row < 160; row++) keep[row] <= row < int'(cfg_count) && cfg_keep[row];
          group_count <= 6'((9'(cfg_count) + 9'd7) >> 3);
          group_index <= 0;
          part_index <= 0;
          word_index <= 0;
          done_error <= invalid;
          state <= invalid ? Done : Initialize;
        end
        Initialize: begin
          group_base <= group_base + 64'(first_byte_offset);
          part_base <= group_base + 64'(first_byte_offset);
          state <= Find;
        end
        Find: begin
          if (row_enable == 0 || (remaining_active == 0 && part_index == 3)) begin
            if (6'(group_index) + 6'd1 == group_count) state <= Done;
            else begin
              group_index <= group_index + 5'd1;
              group_base <= group_base + 64'(group_stride);
              part_base <= group_base + 64'(group_stride);
              part_index <= 0;
              word_index <= 0;
            end
          end else if (remaining_active == 0) begin
            part_base <= part_base + 64'(part_stride);
            part_index <= part_index + 2'd1;
            word_index <= 0;
          end else if (!remaining_active[0]) word_index <= word_index + 6'd1;
          else begin
            load_cfg_address <= part_base + (64'(word_index) << 6);
            load_cfg_words <= active_run(remaining_active);
            state <= Offer;
          end
        end
        Offer: if (load_cfg_ready) state <= Await;
        Await: if (load_done_valid) begin
          if (load_done_error) begin
            done_error <= 1;
            state <= Done;
          end else begin
            word_index <= word_index + load_cfg_words;
            state <= Find;
          end
        end
        Done: if (done_ready) state <= Idle;
        default: state <= Idle;
      endcase
    end
  end
endmodule
