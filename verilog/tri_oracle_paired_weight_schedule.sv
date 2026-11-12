`timescale 1ns/1ps

// A paired tile has sixteen logical channels per cluster. Gate weights
// occupy physical rows 0–15 and up weights occupy rows 16–31. The same
// sparse word schedule is replayed at the up matrix base.
module tri_oracle_paired_weight_schedule (
  input  logic clk, rst_n,
  input  logic cfg_valid, cfg_paired,
  output logic cfg_ready,
  input  logic [63:0] cfg_base, cfg_up_base,
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
  typedef enum logic [2:0] {Idle, First, UpStart, Up, Done} state_t;
  state_t state;
  logic paired;
  logic [63:0] saved_up_base;
  logic [15:0] saved_first_row;
  logic [16:0] saved_dense_rows;
  logic [9:0] saved_feature_words;
  logic [7:0] saved_count, saved_tile_start;
  logic [159:0] saved_keep;
  logic [127:0] saved_active_words;
  logic invalid_pair, schedule_valid, schedule_ready, schedule_done, schedule_error;
  logic [4:0] raw_core, logical_group;
  logic [1:0] raw_group;

  assign invalid_pair = cfg_paired && (cfg_count > 80 || cfg_up_base[5:0] != 0);
  assign cfg_ready = rst_n && state == Idle && schedule_ready;
  assign schedule_valid = (cfg_valid && cfg_ready && !invalid_pair) || state == UpStart;
  assign done_valid = rst_n && state == Done;
  assign logical_group = {raw_core[4:2], raw_group};
  assign load_cfg_core = paired ? {logical_group[3:1], raw_core[1:0]} : raw_core;
  assign load_cfg_row_group = paired ? {state == Up, logical_group[0]} : raw_group;

  tri_oracle_packed_weight_schedule schedule (
    .clk, .rst_n, .cfg_valid(schedule_valid), .cfg_ready(schedule_ready),
    .cfg_base(state == UpStart ? saved_up_base : cfg_base),
    .cfg_first_row(state == UpStart ? saved_first_row : cfg_first_row),
    .cfg_dense_rows(state == UpStart ? saved_dense_rows : cfg_dense_rows),
    .cfg_feature_words(state == UpStart ? saved_feature_words : cfg_feature_words),
    .cfg_count(state == UpStart ? saved_count : cfg_count),
    .cfg_tile_start(state == UpStart ? saved_tile_start : cfg_tile_start),
    .cfg_keep(state == UpStart ? saved_keep : cfg_keep),
    .cfg_active_words(state == UpStart ? saved_active_words : cfg_active_words),
    .load_cfg_valid, .load_cfg_ready, .load_cfg_address, .load_cfg_core(raw_core),
    .load_cfg_first_word, .load_cfg_row_group(raw_group), .load_cfg_row_enable, .load_cfg_words,
    .load_done_valid, .load_done_error, .load_done_ready,
    .done_valid(schedule_done), .done_ready(state == First || state == Up), .done_error(schedule_error)
  );

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state <= Idle;
      paired <= 0;
      done_error <= 0;
      saved_up_base <= 0;
      saved_first_row <= 0;
      saved_dense_rows <= 0;
      saved_feature_words <= 0;
      saved_count <= 0;
      saved_tile_start <= 0;
      saved_keep <= 0;
      saved_active_words <= 0;
    end else begin
      case (state)
        Idle: if (cfg_valid && cfg_ready) begin
          paired <= cfg_paired;
          saved_up_base <= cfg_up_base;
          saved_first_row <= cfg_first_row;
          saved_dense_rows <= cfg_dense_rows;
          saved_feature_words <= cfg_feature_words;
          saved_count <= cfg_count;
          saved_tile_start <= cfg_tile_start;
          saved_keep <= cfg_keep;
          saved_active_words <= cfg_active_words;
          done_error <= invalid_pair;
          state <= invalid_pair ? Done : First;
        end
        First: if (schedule_done) begin
          done_error <= schedule_error;
          state <= paired && !schedule_error ? UpStart : Done;
        end
        UpStart: if (schedule_ready) state <= Up;
        Up: if (schedule_done) begin
          done_error <= schedule_error;
          state <= Done;
        end
        Done: if (done_ready) state <= Idle;
        default: state <= Idle;
      endcase
    end
  end
endmodule
