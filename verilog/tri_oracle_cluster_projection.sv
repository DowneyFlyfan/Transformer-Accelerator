`timescale 1ns / 1ps
// Updated to modern SystemVerilog
// Memory-fed projection over the four real cores and their sum aggregator.
// Contiguous feature shards,16-command tiles and this bus are local choices.
// Padding is explicitly zero loaded; no external padding words are fetched.
module tri_oracle_cluster_projection (
    input logic clk,
    rst_n,
    in_valid,
    in_last,
    in_fallback,
    out_ready,
    input logic [31:0] in_tag,
    input logic [511:0] in_channels,
    input logic [5:0] in_count,
    input logic [63:0] in_activation_base,
    in_weight_base,
    input logic [9:0] in_features,
    output logic in_ready,
    out_valid,
    out_last,
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
  localparam int Cores = 4;
  localparam int Rows = 32;
  localparam int Lanes = 8;
  localparam int SumBits = 32;
  localparam int IdBits = 16;
  localparam int TileStrips = 16;
  localparam int MaxStrips = 512;
  localparam logic [64:0] LastAddress = 65'h0ffffffffffffffff;
  typedef enum logic [3:0] {
    Idle,
    Masks,
    PadActivation,
    PadWeight,
    ActivationStart,
    ActivationWait,
    WeightStart,
    WeightWait,
    NextCore,
    Issue,
    Drain,
    Result
  } state_t;
  state_t state;
  logic [31:0] tag;
  logic [511:0] channels;
  logic [5:0] count;
  logic last, fallback, bank, fault, result_error;
  logic [63:0] activation_base, weight_base;
  logic [9:0] features, shard_length, tile_start, next_tile;
  logic [1:0] core_index;
  logic [4:0] tile_length, real_length, pad_index, issued_count, retired_count;
  logic [3:0] issue_index;
  logic [10:0] global_start, remaining;
  logic [1023:0] sums;
  logic [  31:0] kept_rows;
  logic [ 255:0] lane_mask;
  logic [64:0] activation_end, weight_end, input_bytes;
  logic invalid_shape, wait_transfer, consume, bad_result, unexpected_result;
  logic [5:0] completed_next;
  logic dma_in_ready, dma_done_valid, dma_done_error, dma_load_valid;
  logic [4:0] dma_load_address;
  logic [31:0] dma_load_rows;
  logic [2047:0] dma_load_data;
  logic cluster_load_valid, cluster_load_error;
  logic [1:0] cluster_load_kind;
  logic [9:0] cluster_load_address;
  logic [2047:0] cluster_load_data;
  logic [31:0] cluster_load_rows;
  logic cluster_cmd_valid, cluster_cmd_ready, cluster_out_valid, cluster_out_ready;
  logic [4:0] cluster_cmd_weight;
  logic [9:0] cluster_cmd_activation;
  logic [3:0] cluster_cmd_output, cluster_out_output;
  logic [1023:0] cluster_out_data;

  always_comb begin
    input_bytes = 65'(in_features) * Lanes;
    activation_end = {1'b0, in_activation_base} + input_bytes - 1;
    invalid_shape = in_count > 6'(Rows) || in_features == 0 || in_features > 10'(MaxStrips) ||
                    in_activation_base[2:0] != 0 || in_weight_base[2:0] != 0 ||
                    activation_end > LastAddress;
    weight_end = 0;
    for (int row = 0; row < Rows; row++) begin
      weight_end = {1'b0, in_weight_base} +
                   (65'(in_channels[row*IdBits+:IdBits]) + 1) * input_bytes - 1;
      if (row < int'(in_count) && weight_end > LastAddress) invalid_shape = 1;
    end
    remaining = 11'(shard_length) - 11'(tile_start);
    tile_length = remaining > 11'(TileStrips) ? 5'(TileStrips) : remaining[4:0];
    next_tile = tile_start + 10'(tile_length);
    global_start = 11'(core_index) * 11'(shard_length) + 11'(tile_start);
    if (global_start >= 11'(features)) real_length = 0;
    else if (11'(features) - global_start < 11'(tile_length))
      real_length = 5'(11'(features) - global_start);
    else real_length = tile_length;
    kept_rows = 0;
    lane_mask = 0;
    for (int row = 0; row < Rows; row++) begin
      if (row < int'(count)) begin
        kept_rows[row] = 1;
        lane_mask[row*Lanes+:Lanes] = '1;
      end
    end
    in_ready = state == Idle;
    out_valid = state == Result;
    out_tag = tag;
    out_count = result_error ? 0 : count;
    out_channels = channels;
    out_last = last;
    out_fallback = fallback;
    out_error = result_error;
    out_data = result_error ? 1024'b0 : sums;
    wait_transfer = state == ActivationWait || state == WeightWait;
    cluster_out_ready = state == Issue || state == Drain;
    consume = cluster_out_valid && cluster_out_ready;
    bad_result = consume && (retired_count >= issued_count ||
                             cluster_out_output != retired_count[3:0]);
    unexpected_result = cluster_out_valid && !cluster_out_ready;
    completed_next = 6'(retired_count) + 6'(consume);
    cluster_cmd_valid = state == Issue && !fault && !cluster_load_error && !bad_result;
    cluster_cmd_weight = {bank, issue_index};
    cluster_cmd_activation = tile_start + 10'(issue_index);
    cluster_cmd_output = issue_index;
  end

  always_comb begin
    cluster_load_valid = 0;
    cluster_load_kind = 0;
    cluster_load_address = 0;
    cluster_load_data = 0;
    cluster_load_rows = kept_rows;
    if (state == Masks) begin
      cluster_load_valid = 1;
      cluster_load_kind = 2;
      cluster_load_data[Rows*Lanes-1:0] = lane_mask;
    end else if (state == PadActivation) begin
      if (pad_index >= real_length && pad_index < tile_length) begin
        cluster_load_valid = 1;
        cluster_load_kind = 1;
        cluster_load_address = tile_start + 10'(pad_index);
      end
    end else if (state == PadWeight) begin
      cluster_load_valid   = 1;
      cluster_load_address = 10'({bank, pad_index[3:0]});
    end else if (wait_transfer && dma_load_valid) begin
      cluster_load_valid = 1;
      cluster_load_kind = state == ActivationWait ? 2'd1 : 2'd0;
      cluster_load_address = state == ActivationWait ?
          tile_start + 10'(dma_load_address[3:0]) : 10'(dma_load_address);
      cluster_load_data = dma_load_data;
      cluster_load_rows = dma_load_rows;
    end
  end

  tri_oracle_sparse_weight_dma transfer (
      .clk(clk),
      .rst_n(rst_n),
      .in_valid((state == ActivationStart || state == WeightStart) &&
                real_length != 0 && !fault && !cluster_load_error),
      .in_ready(dma_in_ready),
      .in_bank(bank),
      .in_channels(state == ActivationStart ? 512'b0 : channels),
      .in_count(state == ActivationStart ? 6'd1 : count),
      .in_base(state == ActivationStart ? activation_base : weight_base),
      .in_features(features),
      .in_start(global_start[8:0]),
      .in_length(real_length),
      .done_ready(wait_transfer),
      .done_valid(dma_done_valid),
      .done_error(dma_done_error),
      .req_valid(req_valid),
      .req_ready(req_ready),
      .req_address(req_address),
      .req_length(req_length),
      .rsp_valid(rsp_valid),
      .rsp_last(rsp_last),
      .rsp_error(rsp_error),
      .rsp_ready(rsp_ready),
      .rsp_data(rsp_data),
      .load_valid(dma_load_valid),
      .load_ready(1'b1),
      .load_address(dma_load_address),
      .load_row_enable(dma_load_rows),
      .load_data(dma_load_data)
  );

  tri_oracle_compute_cluster cluster (
      .clk(clk),
      .rst_n(rst_n),
      .load_valid(cluster_load_valid),
      .load_core(core_index),
      .load_kind(cluster_load_kind),
      .load_addr(cluster_load_address),
      .load_data(cluster_load_data),
      .load_row_enable(cluster_load_rows),
      .load_error(cluster_load_error),
      .cmd_valid(cluster_cmd_valid),
      .cmd_ready(cluster_cmd_ready),
      .cmd_weight(cluster_cmd_weight),
      .cmd_mask(5'd0),
      .cmd_activation(cluster_cmd_activation),
      .cmd_output(cluster_cmd_output),
      .cmd_accumulate(1'b0),
      .cmd_reduce(2'd0),
      .out_valid(cluster_out_valid),
      .out_ready(cluster_out_ready),
      .out_output(cluster_out_output),
      .out_data(cluster_out_data)
  );

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state <= Idle;
      tag <= 0;
      channels <= 0;
      count <= 0;
      last <= 0;
      fallback <= 0;
      bank <= 0;
      fault <= 0;
      result_error <= 0;
      activation_base <= 0;
      weight_base <= 0;
      features <= 0;
      shard_length <= 0;
      tile_start <= 0;
      core_index <= 0;
      pad_index <= 0;
      issue_index <= 0;
      issued_count <= 0;
      retired_count <= 0;
      sums <= 0;
    end else begin
      if (state != Idle && state != Result &&
          (cluster_load_error || bad_result || unexpected_result))
        fault <= 1;
      if (consume) begin
        retired_count <= retired_count + 1'b1;
        for (int row = 0; row < Rows; row++)
        sums[row*SumBits+:SumBits] <= sums[row*SumBits+:SumBits] +
                                      cluster_out_data[row*SumBits+:SumBits];
      end
      if (state != Idle && state != Result && !wait_transfer &&
          state != Issue && state != Drain &&
          (fault || cluster_load_error || unexpected_result)) begin
        result_error <= 1;
        state <= Result;
      end else
        case (state)
          Idle:
          if (in_valid) begin
            tag <= in_tag;
            channels <= in_channels;
            count <= in_count;
            last <= in_last;
            fallback <= in_fallback;
            activation_base <= in_activation_base;
            weight_base <= in_weight_base;
            features <= in_features;
            shard_length <= 10'((11'(in_features) + 11'(Cores - 1)) >> 2);
            tile_start <= 0;
            core_index <= 0;
            pad_index <= 0;
            issue_index <= 0;
            issued_count <= 0;
            retired_count <= 0;
            bank <= 0;
            fault <= 0;
            result_error <= 0;
            sums <= 0;
            if (in_count == 0) state <= Result;
            else if (invalid_shape) begin
              result_error <= 1;
              state <= Result;
            end else state <= Masks;
          end
          Masks: begin
            if (core_index == 2'(Cores - 1)) begin
              core_index <= 0;
              state <= PadActivation;
            end else core_index <= core_index + 1'b1;
          end
          PadActivation: begin
            if (pad_index < real_length) pad_index <= real_length;
            else if (pad_index >= tile_length) state <= ActivationStart;
            else state <= PadWeight;
          end
          PadWeight: begin
            pad_index <= pad_index + 1'b1;
            state <= PadActivation;
          end
          ActivationStart: begin
            if (real_length == 0) state <= NextCore;
            else if (dma_in_ready) state <= ActivationWait;
          end
          WeightStart: if (dma_in_ready) state <= WeightWait;
          ActivationWait, WeightWait:
          if (dma_done_valid) begin
            if (dma_done_error || fault || cluster_load_error) begin
              result_error <= 1;
              state <= Result;
            end else if (state == ActivationWait) state <= WeightStart;
            else state <= NextCore;
          end
          NextCore: begin
            if (core_index == 2'(Cores - 1)) begin
              issue_index <= 0;
              issued_count <= 0;
              retired_count <= 0;
              state <= Issue;
            end else begin
              core_index <= core_index + 1'b1;
              pad_index <= 0;
              state <= PadActivation;
            end
          end
          Issue: begin
            if (fault || cluster_load_error || bad_result) state <= Drain;
            else if (cluster_cmd_ready) begin
              issued_count <= issued_count + 1'b1;
              if (5'(issue_index) + 5'd1 == tile_length) state <= Drain;
              else issue_index <= issue_index + 1'b1;
            end
          end
          Drain:
          if (completed_next == 6'(issued_count)) begin
            if (fault || cluster_load_error || bad_result) begin
              result_error <= 1;
              state <= Result;
            end else if (next_tile == shard_length) state <= Result;
            else begin
              tile_start <= next_tile;
              core_index <= 0;
              pad_index <= 0;
              bank <= !bank;
              state <= PadActivation;
            end
          end
          Result: if (out_ready) state <= Idle;
          default: begin
            result_error <= 1;
            state <= Result;
          end
        endcase
    end
  end
endmodule
