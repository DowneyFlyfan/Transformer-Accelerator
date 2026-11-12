`timescale 1ns/1ps

// Lane zero writes clusters 0 and 1 and the first two cores of cluster 2.
// Lane one writes the last two cores of cluster 2 and clusters 3 and 4.
// The shared cluster accepts a single write per cycle.
module tri_oracle_parallel_weight_loader (
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

  output logic [1:0] req_valid,
  input  logic [1:0] req_ready,
  output logic [1:0][63:0] req_address,
  output logic [1:0][5:0] req_length,
  input  logic [1:0] rsp_valid, rsp_last, rsp_error,
  output logic [1:0] rsp_ready,
  output logic [1:0] load_valid,
  output logic [1:0][4:0] load_core,
  output logic [1:0][9:0] load_addr,
  output logic [1:0][31:0] load_row_enable,

  output logic done_valid,
  input  logic done_ready,
  output logic done_error
);
  typedef enum logic [2:0] {StartFirst, WaitFirst, StartSecond, WaitSecond, Finished} lane_state_t;

  logic active, accept_config;
  logic saved_paired;
  logic [63:0] saved_base, saved_up_base;
  logic [15:0] saved_first_row;
  logic [16:0] saved_dense_rows;
  logic [9:0] saved_feature_words;
  logic [7:0] saved_count, saved_tile_start;
  logic [159:0] saved_keep, low_rows, middle_rows, high_rows;
  logic [127:0] saved_active_words;
  logic [1:0] lane_finished, lane_error, raw_load_valid, write_grant;
  logic conflict, next_grant;

  assign cfg_ready = rst_n && !active;
  assign accept_config = cfg_valid && cfg_ready;
  assign done_valid = rst_n && active && (&lane_finished);
  assign done_error = |lane_error;

  assign low_rows = saved_paired ? 160'hffffffff : 160'hffffffffffffffff;
  assign middle_rows = saved_paired ? 160'hffff << 32 : 160'hffffffff << 64;
  assign high_rows = saved_paired ? {112{1'b1}} << 48 : {64{1'b1}} << 96;

  assign conflict = (&raw_load_valid) && load_core[0][4:2] == load_core[1][4:2];
  assign write_grant = conflict ? (next_grant ? 2'b10 : 2'b01) : 2'b11;
  assign load_valid = raw_load_valid & write_grant;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      active <= 0;
      next_grant <= 0;
      saved_paired <= 0;
      saved_base <= 0;
      saved_up_base <= 0;
      saved_first_row <= 0;
      saved_dense_rows <= 0;
      saved_feature_words <= 0;
      saved_count <= 0;
      saved_tile_start <= 0;
      saved_keep <= 0;
      saved_active_words <= 0;
    end else begin
      if (conflict) next_grant <= !next_grant;
      if (accept_config) begin
        active <= 1;
        saved_paired <= cfg_paired;
        saved_base <= cfg_base;
        saved_up_base <= cfg_up_base;
        saved_first_row <= cfg_first_row;
        saved_dense_rows <= cfg_dense_rows;
        saved_feature_words <= cfg_feature_words;
        saved_count <= cfg_count;
        saved_tile_start <= cfg_tile_start;
        saved_keep <= cfg_keep;
        saved_active_words <= cfg_active_words;
      end else if (done_valid && done_ready) active <= 0;
    end
  end

  for (genvar lane = 0; lane < 2; lane++) begin : read_lane
    lane_state_t state;
    logic split_cluster, scheduler_valid, scheduler_ready, scheduler_done, scheduler_error;
    logic [159:0] row_mask;
    logic [127:0] word_mask;
    logic descriptor_valid, descriptor_ready, burst_done, burst_done_ready, burst_error;
    logic [63:0] descriptor_address;
    logic [4:0] descriptor_core, descriptor_first_word;
    logic [1:0] descriptor_group;
    logic [7:0] descriptor_row_enable;
    logic [5:0] descriptor_words;

    // Send lane one to the shared cluster first. Lane zero reaches it after
    // the lower clusters, so dense traffic rarely needs arbitration.
    assign split_cluster = lane == 0 ? state == StartSecond : state == StartFirst;
    assign row_mask = split_cluster ? middle_rows : lane == 0 ? low_rows : high_rows;
    assign word_mask = split_cluster ?
      (lane == 0 ? {64'b0, saved_active_words[63:0]} : {saved_active_words[127:64], 64'b0}) :
      saved_active_words;
    assign scheduler_valid = active && (state == StartFirst || state == StartSecond);
    assign lane_finished[lane] = state == Finished;

    tri_oracle_paired_weight_schedule schedule (
      .clk, .rst_n, .cfg_valid(scheduler_valid), .cfg_ready(scheduler_ready),
      .cfg_paired(saved_paired), .cfg_base(saved_base), .cfg_up_base(saved_up_base),
      .cfg_first_row(saved_first_row), .cfg_dense_rows(saved_dense_rows),
      .cfg_feature_words(saved_feature_words), .cfg_count(saved_count), .cfg_tile_start(saved_tile_start),
      .cfg_keep(saved_keep & row_mask), .cfg_active_words(word_mask),
      .load_cfg_valid(descriptor_valid), .load_cfg_ready(descriptor_ready),
      .load_cfg_address(descriptor_address), .load_cfg_core(descriptor_core),
      .load_cfg_first_word(descriptor_first_word), .load_cfg_row_group(descriptor_group),
      .load_cfg_row_enable(descriptor_row_enable), .load_cfg_words(descriptor_words),
      .load_done_valid(burst_done), .load_done_ready(burst_done_ready), .load_done_error(burst_error),
      .done_valid(scheduler_done), .done_ready(state == WaitFirst || state == WaitSecond),
      .done_error(scheduler_error)
    );

    tri_oracle_wide_weight_loader loader (
      .clk, .rst_n, .cfg_valid(descriptor_valid), .cfg_ready(descriptor_ready),
      .cfg_address(descriptor_address), .cfg_core(descriptor_core), .cfg_first_word(descriptor_first_word),
      .cfg_row_group(descriptor_group), .cfg_row_enable(descriptor_row_enable), .cfg_words(descriptor_words),
      .done_valid(burst_done), .done_ready(burst_done_ready), .done_error(burst_error),
      .req_valid(req_valid[lane]), .req_ready(req_ready[lane]), .req_address(req_address[lane]),
      .req_length(req_length[lane]), .rsp_valid(rsp_valid[lane]), .rsp_ready(rsp_ready[lane]),
      .rsp_last(rsp_last[lane]), .rsp_error(rsp_error[lane]), .rsp_data('0),
      .load_valid(raw_load_valid[lane]), .load_ready(write_grant[lane]), .load_core(load_core[lane]),
      .load_addr(load_addr[lane]), .load_row_enable(load_row_enable[lane]), .load_data()
    );

    always_ff @(posedge clk or negedge rst_n) begin
      if (!rst_n) begin
        state <= StartFirst;
        lane_error[lane] <= 0;
      end else if (accept_config) begin
        state <= StartFirst;
        lane_error[lane] <= 0;
      end else if (active) begin
        case (state)
          StartFirst: if (scheduler_ready) state <= WaitFirst;
          WaitFirst: if (scheduler_done) begin
            lane_error[lane] <= scheduler_error;
            state <= scheduler_error ? Finished : StartSecond;
          end
          StartSecond: if (scheduler_ready) state <= WaitSecond;
          WaitSecond: if (scheduler_done) begin
            lane_error[lane] <= scheduler_error;
            state <= Finished;
          end
          Finished: ;
          default: state <= Finished;
        endcase
      end
    end
  end
endmodule
