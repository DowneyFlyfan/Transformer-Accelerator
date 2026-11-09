`timescale 1ns / 1ps
// Updated to modern SystemVerilog
// One memory port supplies raw statistics, raw/coefficient replay, then compute.
// Preparation errors discard reader streams until all owned reads have ended.
// Only then may the preparation-only compute context be reset and an error held.
// External memory remains stable for the token; global reset also resets its peer.
module tri_oracle_memory_feedforward_core (
    input logic clk,
    rst_n,
    cfg_valid,
    output logic cfg_ready,
    input logic [31:0] cfg_tag,
    cfg_epsilon_q16,
    input logic [63:0] cfg_raw_base,
    cfg_gamma_base,
    input logic [63:0] cfg_activation_base,
    cfg_weight_base,
    cfg_up_weight_base,
    input logic [63:0] cfg_down_weight_base,
    cfg_gate_sign_base,
    cfg_up_sign_base,
    input logic [5:0] cfg_gate_shift,
    cfg_up_shift,
    cfg_down_shift,
    cfg_activation_shift,
    input logic [9:0] cfg_features,
    input logic [16:0] cfg_dense_features,
    input logic [15:0] cfg_output_start,
    input logic [8:0] cfg_output_count,
    input logic group_valid,
    output logic group_ready,
    input logic [10:0] group_id,
    input logic group_last,
    output logic out_valid,
    input logic out_ready,
    output logic out_last,
    out_fallback,
    out_error,
    output logic [31:0] out_tag,
    output logic [5:0] out_count,
    output logic [511:0] out_channels,
    output logic [1023:0] out_data,
    output logic req_valid,
    input logic req_ready,
    output logic [63:0] req_address,
    output logic [4:0] req_length,
    input logic rsp_valid,
    rsp_last,
    rsp_error,
    output logic rsp_ready,
    input logic [63:0] rsp_data
);
  typedef enum logic [2:0] {
    Idle,
    CoreCheck,
    LoaderConfigure,
    Prepare,
    ResetCore,
    Run,
    Error
  } state_t;
  state_t state;
  logic [31:0] tag;
  logic [9:0] features;
  logic [63:0] raw_base, gamma_base;
  logic preparation_failed, discard_streams, core_rst_n;
  logic core_cfg_valid, core_cfg_ready, core_group_ready;
  logic core_stats_valid, core_stats_ready, core_replay_valid, core_replay_ready;
  logic core_out_valid, core_out_ready, core_out_last, core_out_error, core_out_fallback;
  logic [31:0] core_out_tag;
  logic [5:0] core_out_count;
  logic [511:0] core_out_channels;
  logic [1023:0] core_out_data;
  logic core_req_valid, core_req_ready, core_rsp_valid, core_rsp_ready;
  logic [63:0] core_req_address;
  logic [ 4:0] core_req_length;
  logic loader_cfg_ready, loader_stats_valid, loader_stats_ready, loader_stats_last;
  logic loader_replay_valid, loader_replay_ready, loader_replay_last;
  logic [127:0] loader_stats_data, loader_replay_data, loader_replay_gamma;
  logic loader_done_valid, loader_done_error;
  logic [31:0] loader_done_tag;
  logic loader_req_valid, loader_req_ready, loader_rsp_valid, loader_rsp_ready;
  logic [63:0] loader_req_address;
  logic [ 4:0] loader_req_length;

  always_comb begin
    cfg_ready = state == Idle && core_cfg_ready && loader_cfg_ready;
    group_ready = state == Run && core_group_ready;
    discard_streams = preparation_failed || core_out_valid;
    core_rst_n = rst_n && state != ResetCore;
    out_valid = state == Error || (state == Run && core_out_valid);
    out_last = state == Error || core_out_last;
    out_error = state == Error || core_out_error;
    out_fallback = state == Run && core_out_fallback;
    out_tag = state == Error ? tag : core_out_tag;
    out_count = state == Error ? 6'd0 : core_out_count;
    out_channels = state == Error ? 512'b0 : core_out_channels;
    out_data = state == Error ? 1024'b0 : core_out_data;
    loader_stats_ready = state == Prepare && (discard_streams || core_stats_ready);
    loader_replay_ready = state == Prepare && (discard_streams || core_replay_ready);
    req_valid = state == Prepare ? loader_req_valid : (state == Run && core_req_valid);
    req_address = state == Prepare ? loader_req_address : core_req_address;
    req_length = state == Prepare ? loader_req_length : core_req_length;
    rsp_ready = state == Prepare ? loader_rsp_ready : (state == Run && core_rsp_ready);
  end
  always_comb core_cfg_valid = cfg_valid && cfg_ready;
  always_comb core_stats_valid = state == Prepare && !discard_streams && loader_stats_valid;
  always_comb core_replay_valid = state == Prepare && !discard_streams && loader_replay_valid;
  always_comb core_out_ready = state == CoreCheck || (state == Run && out_ready);
  always_comb loader_req_ready = state == Prepare && req_ready;
  always_comb core_req_ready = state == Run && req_ready;
  always_comb loader_rsp_valid = state == Prepare && rsp_valid;
  always_comb core_rsp_valid = state == Run && rsp_valid;

  tri_oracle_activation_loader reader (
      .clk(clk),
      .rst_n(rst_n),
      .cfg_valid(state == LoaderConfigure),
      .cfg_ready(loader_cfg_ready),
      .cfg_tag(tag),
      .cfg_strips(features),
      .cfg_raw_base(raw_base),
      .cfg_gamma_base(gamma_base),
      .stats_valid(loader_stats_valid),
      .stats_ready(loader_stats_ready),
      .stats_last(loader_stats_last),
      .stats_data(loader_stats_data),
      .replay_valid(loader_replay_valid),
      .replay_ready(loader_replay_ready),
      .replay_last(loader_replay_last),
      .replay_data(loader_replay_data),
      .replay_gamma(loader_replay_gamma),
      .done_valid(loader_done_valid),
      .done_ready(state == Prepare),
      .done_error(loader_done_error),
      .done_tag(loader_done_tag),
      .req_valid(loader_req_valid),
      .req_ready(loader_req_ready),
      .req_address(loader_req_address),
      .req_length(loader_req_length),
      .rsp_valid(loader_rsp_valid),
      .rsp_ready(loader_rsp_ready),
      .rsp_last(rsp_last),
      .rsp_error(rsp_error),
      .rsp_data(rsp_data)
  );
  tri_oracle_cached_feedforward_core core (
      .clk(clk),
      .rst_n(core_rst_n),
      .cfg_valid(core_cfg_valid),
      .cfg_ready(core_cfg_ready),
      .cfg_tag(cfg_tag),
      .cfg_epsilon_q16(cfg_epsilon_q16),
      .cfg_activation_base(cfg_activation_base),
      .cfg_weight_base(cfg_weight_base),
      .cfg_up_weight_base(cfg_up_weight_base),
      .cfg_down_weight_base(cfg_down_weight_base),
      .cfg_gate_sign_base(cfg_gate_sign_base),
      .cfg_up_sign_base(cfg_up_sign_base),
      .cfg_gate_shift(cfg_gate_shift),
      .cfg_up_shift(cfg_up_shift),
      .cfg_down_shift(cfg_down_shift),
      .cfg_activation_shift(cfg_activation_shift),
      .cfg_features(cfg_features),
      .cfg_dense_features(cfg_dense_features),
      .cfg_output_start(cfg_output_start),
      .cfg_output_count(cfg_output_count),
      .group_valid(state == Run && group_valid),
      .group_ready(core_group_ready),
      .group_id(group_id),
      .group_last(group_last),
      .stats_valid(core_stats_valid),
      .stats_ready(core_stats_ready),
      .stats_last(loader_stats_last),
      .stats_data(loader_stats_data),
      .replay_valid(core_replay_valid),
      .replay_ready(core_replay_ready),
      .replay_last(loader_replay_last),
      .replay_data(loader_replay_data),
      .replay_gamma(loader_replay_gamma),
      .out_valid(core_out_valid),
      .out_ready(core_out_ready),
      .out_last(core_out_last),
      .out_error(core_out_error),
      .out_fallback(core_out_fallback),
      .out_tag(core_out_tag),
      .out_count(core_out_count),
      .out_channels(core_out_channels),
      .out_data(core_out_data),
      .req_valid(core_req_valid),
      .req_ready(core_req_ready),
      .req_address(core_req_address),
      .req_length(core_req_length),
      .rsp_valid(core_rsp_valid),
      .rsp_ready(core_rsp_ready),
      .rsp_last(rsp_last),
      .rsp_error(rsp_error),
      .rsp_data(rsp_data)
  );

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state <= Idle;
      tag <= '0;
      features <= '0;
      raw_base <= '0;
      gamma_base <= '0;
      preparation_failed <= 1'b0;
    end else begin
      case (state)
        Idle:
        if (cfg_valid && cfg_ready) begin
          tag <= cfg_tag;
          features <= cfg_features;
          raw_base <= cfg_raw_base;
          gamma_base <= cfg_gamma_base;
          preparation_failed <= 1'b0;
          state <= CoreCheck;
        end
        CoreCheck:
        if (core_out_valid) state <= Error;
        else state <= LoaderConfigure;
        LoaderConfigure: if (loader_cfg_ready) state <= Prepare;
        Prepare: begin
          if (core_out_valid) preparation_failed <= 1'b1;
          if (loader_done_valid) begin
            if (loader_done_error || loader_done_tag != tag || preparation_failed || core_out_valid)
              state <= ResetCore;
            else state <= Run;
          end
        end
        // No compute memory request is forwarded during preparation;
        // reader completion means every external read reached actual LAST.
        ResetCore: state <= Error;
        Run: if (core_out_valid && out_ready && core_out_last) state <= Idle;
        Error: if (out_ready) state <= Idle;
        default: state <= ResetCore;
      endcase
    end
  end
endmodule
