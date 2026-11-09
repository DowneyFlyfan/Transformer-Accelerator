`timescale 1ns/1ps
// One owner for projection slot0 and down-projection slots1..15. The external
// cluster is shared; this module contains control and one bounded result
// packet, never another arithmetic datapath or a hidden-tensor cache.
// Child completion implies its accepted memory traffic has drained. Capture
// the packet before a fatal-frame reset so output backpressure remains safe.
module tri_oracle_shared_cluster_executor (
    input logic clk, rst_n, in_valid, in_is_down, in_last, in_fallback,
    input logic in_accumulate, out_ready,
    input logic [31:0] in_tag,
    input logic [5:0] in_count, in_output_count, in_shift,
    input logic [511:0] in_channels,
    input logic [1023:0] in_data,
    input logic [63:0] in_activation_base, in_weight_base,
    input logic [9:0] in_features,
    input logic [16:0] in_dense_features,
    input logic [15:0] in_output_start,
    input logic [3:0] in_slot,
    output logic in_ready, out_valid, out_is_down, out_last, out_fallback, out_error,
    output logic [31:0] out_tag,
    output logic [5:0] out_count,
    output logic [511:0] out_channels,
    output logic [15:0] out_start,
    output logic [3:0] out_slot,
    output logic [1023:0] out_data,
    output logic req_valid,
    input logic req_ready,
    output logic [63:0] req_address,
    output logic [4:0] req_length,
    input logic rsp_valid, rsp_last, rsp_error,
    output logic rsp_ready,
    input logic [63:0] rsp_data,
    output logic cluster_rst_n,
    output logic cluster_load_valid,
    output logic [1:0] cluster_load_core, cluster_load_kind,
    output logic [9:0] cluster_load_address,
    output logic [2047:0] cluster_load_data,
    output logic [31:0] cluster_load_rows,
    input logic cluster_load_error,
    output logic cluster_cmd_valid,
    input logic cluster_cmd_ready,
    output logic [4:0] cluster_cmd_weight, cluster_cmd_mask,
    output logic [9:0] cluster_cmd_activation,
    output logic [3:0] cluster_cmd_output,
    output logic cluster_cmd_accumulate,
    input logic cluster_out_valid,
    output logic cluster_out_ready,
    input logic [3:0] cluster_out_output,
    input logic [1023:0] cluster_out_data
);
  typedef enum logic [2:0] {IDLE, PROJECTION, DOWN, FLUSH, RESULT} state_t;
  state_t state;
  logic controller_reset_n, down_cluster_reset_n, flush_second_cycle;
  logic p_ready, p_valid, p_last, p_fallback, p_error;
  logic [31:0] p_tag;
  logic [5:0] p_count;
  logic [511:0] p_channels;
  logic [1023:0] p_data;
  logic d_ready, d_valid, d_last, d_error;
  logic [31:0] d_tag;
  logic [5:0] d_count;
  logic [15:0] d_start;
  logic [3:0] d_slot;
  logic [1023:0] d_data;
  logic p_req_valid, p_rsp_ready, d_req_valid, d_rsp_ready;
  logic [63:0] p_req_address, d_req_address;
  logic [4:0] p_req_length, d_req_length;
  logic p_load_valid, d_load_valid, p_cmd_valid, d_cmd_valid;
  logic [1:0] p_load_core, d_load_core, p_load_kind, d_load_kind;
  logic [9:0] p_load_address, d_load_address;
  logic [2047:0] p_load_data, d_load_data;
  logic [31:0] p_load_rows, d_load_rows;
  logic [4:0] p_cmd_weight, d_cmd_weight, d_cmd_mask;
  logic [9:0] p_cmd_activation, d_cmd_activation;
  logic [3:0] p_cmd_output, d_cmd_output;
  logic p_cmd_accumulate, d_cmd_accumulate, p_out_ready, d_out_ready;

  always_comb begin
    in_ready = state == IDLE && controller_reset_n && down_cluster_reset_n && p_ready && d_ready;
    out_valid = state == RESULT;
    // This registered root is asynchronously cleared by the owner's reset
    // flop and synchronously released by the down controller's reset flop.
    cluster_rst_n = down_cluster_reset_n;
    req_valid = 0; req_address = 0; req_length = 0; rsp_ready = 0;
    cluster_load_valid = 0; cluster_load_core = 0; cluster_load_kind = 0;
    cluster_load_address = 0; cluster_load_data = 0; cluster_load_rows = 0;
    cluster_cmd_valid = 0; cluster_cmd_weight = 0; cluster_cmd_mask = 0;
    cluster_cmd_activation = 0; cluster_cmd_output = 0;
    cluster_cmd_accumulate = 0; cluster_out_ready = 0;
    if (state == PROJECTION) begin
      req_valid = p_req_valid; req_address = p_req_address; req_length = p_req_length;
      rsp_ready = p_rsp_ready;
      cluster_load_valid = p_load_valid; cluster_load_core = p_load_core;
      cluster_load_kind = p_load_kind; cluster_load_address = p_load_address;
      cluster_load_data = p_load_data; cluster_load_rows = p_load_rows;
      cluster_cmd_valid = p_cmd_valid; cluster_cmd_weight = p_cmd_weight;
      cluster_cmd_activation = p_cmd_activation; cluster_cmd_output = p_cmd_output;
      cluster_cmd_accumulate = p_cmd_accumulate; cluster_out_ready = p_out_ready;
    end else if (state == DOWN) begin
      req_valid = d_req_valid; req_address = d_req_address; req_length = d_req_length;
      rsp_ready = d_rsp_ready;
      cluster_load_valid = d_load_valid; cluster_load_core = d_load_core;
      cluster_load_kind = d_load_kind; cluster_load_address = d_load_address;
      cluster_load_data = d_load_data; cluster_load_rows = d_load_rows;
      cluster_cmd_valid = d_cmd_valid; cluster_cmd_weight = d_cmd_weight;
      cluster_cmd_mask = d_cmd_mask; cluster_cmd_activation = d_cmd_activation;
      cluster_cmd_output = d_cmd_output; cluster_cmd_accumulate = d_cmd_accumulate;
      cluster_out_ready = d_out_ready;
    end
  end

  tri_oracle_cluster_projection_executor projection (
      .clk(clk), .rst_n(controller_reset_n),
      .in_valid(in_valid && in_ready && !in_is_down), .in_ready(p_ready),
      .in_last(in_last), .in_fallback(in_fallback), .in_tag(in_tag),
      .in_channels(in_channels), .in_count(in_count), .in_activation_base(in_activation_base),
      .in_weight_base(in_weight_base), .in_features(in_features),
      .out_ready(state == PROJECTION), .out_valid(p_valid), .out_last(p_last),
      .out_fallback(p_fallback), .out_error(p_error), .out_tag(p_tag),
      .out_count(p_count), .out_channels(p_channels), .out_data(p_data),
      .req_valid(p_req_valid), .req_ready(state == PROJECTION && req_ready),
      .req_address(p_req_address), .req_length(p_req_length),
      .rsp_valid(state == PROJECTION && rsp_valid), .rsp_last(rsp_last),
      .rsp_error(rsp_error), .rsp_ready(p_rsp_ready), .rsp_data(rsp_data),
      .cluster_load_valid(p_load_valid), .cluster_load_core(p_load_core),
      .cluster_load_kind(p_load_kind), .cluster_load_address(p_load_address),
      .cluster_load_data(p_load_data), .cluster_load_rows(p_load_rows),
      .cluster_load_error(state == PROJECTION && cluster_load_error),
      .cluster_cmd_valid(p_cmd_valid), .cluster_cmd_ready(state == PROJECTION && cluster_cmd_ready),
      .cluster_cmd_weight(p_cmd_weight), .cluster_cmd_activation(p_cmd_activation),
      .cluster_cmd_output(p_cmd_output), .cluster_cmd_accumulate(p_cmd_accumulate),
      .cluster_out_valid(state == PROJECTION && cluster_out_valid),
      .cluster_out_ready(p_out_ready), .cluster_out_output(cluster_out_output),
      .cluster_out_data(cluster_out_data)
  );

  tri_oracle_cluster_down_executor down (
      .clk(clk), .rst_n(controller_reset_n),
      .in_valid(in_valid && in_ready && in_is_down), .in_ready(d_ready),
      .in_last(in_last), .in_accumulate(in_accumulate), .in_tag(in_tag), .in_count(in_count),
      .in_output_count(in_output_count), .in_shift(in_shift), .in_channels(in_channels),
      .in_data(in_data), .in_weight_base(in_weight_base), .in_dense_features(in_dense_features),
      .in_output_start(in_output_start), .in_slot(in_slot),
      .out_ready(state == DOWN), .out_valid(d_valid), .out_last(d_last), .out_error(d_error),
      .out_tag(d_tag), .out_count(d_count), .out_start(d_start), .out_slot(d_slot), .out_data(d_data),
      .req_valid(d_req_valid), .req_ready(state == DOWN && req_ready),
      .req_address(d_req_address), .req_length(d_req_length),
      .rsp_valid(state == DOWN && rsp_valid), .rsp_last(rsp_last), .rsp_error(rsp_error),
      .rsp_ready(d_rsp_ready), .rsp_data(rsp_data), .cluster_rst_n(down_cluster_reset_n),
      .cluster_load_valid(d_load_valid), .cluster_load_core(d_load_core),
      .cluster_load_kind(d_load_kind), .cluster_load_address(d_load_address),
      .cluster_load_data(d_load_data), .cluster_load_rows(d_load_rows),
      .cluster_load_error(state == DOWN && cluster_load_error),
      .cluster_cmd_valid(d_cmd_valid), .cluster_cmd_ready(state == DOWN && cluster_cmd_ready),
      .cluster_cmd_weight(d_cmd_weight), .cluster_cmd_mask(d_cmd_mask),
      .cluster_cmd_activation(d_cmd_activation), .cluster_cmd_output(d_cmd_output),
      .cluster_cmd_accumulate(d_cmd_accumulate), .cluster_out_valid(state == DOWN && cluster_out_valid),
      .cluster_out_ready(d_out_ready), .cluster_out_output(cluster_out_output),
      .cluster_out_data(cluster_out_data)
  );

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state <= IDLE;
      controller_reset_n <= 0;
      flush_second_cycle <= 0;
      out_is_down <= 0; out_last <= 0; out_fallback <= 0; out_error <= 0;
      out_tag <= 0; out_count <= 0; out_channels <= 0;
      out_start <= 0; out_slot <= 0; out_data <= 0;
    end else begin
      controller_reset_n <= 1;
      case (state)
        IDLE: if (in_valid && in_ready) begin
          out_is_down <= in_is_down;
          state <= in_is_down ? DOWN : PROJECTION;
        end
        PROJECTION: if (p_valid) begin
          out_last <= p_last; out_fallback <= p_fallback; out_error <= p_error;
          out_tag <= p_tag; out_count <= p_count; out_channels <= p_channels;
          out_start <= 0; out_slot <= 0; out_data <= p_data;
          if (p_error) begin
            controller_reset_n <= 0;
            flush_second_cycle <= 0;
            state <= FLUSH;
          end else state <= RESULT;
        end
        DOWN: if (d_valid) begin
          out_last <= d_last; out_fallback <= 0; out_error <= d_error;
          out_tag <= d_tag; out_count <= d_count; out_channels <= 0;
          out_start <= d_start; out_slot <= d_slot; out_data <= d_data;
          if (d_error) begin
            controller_reset_n <= 0;
            flush_second_cycle <= 0;
            state <= FLUSH;
          end else state <= RESULT;
        end
        FLUSH: begin
          if (flush_second_cycle) state <= RESULT;
          else begin
            controller_reset_n <= 0;
            flush_second_cycle <= 1;
          end
        end
        RESULT: if (out_ready) state <= IDLE;
        default: begin
          controller_reset_n <= 0;
          flush_second_cycle <= 0;
          out_error <= 1; out_count <= 0; out_data <= 0;
          state <= FLUSH;
        end
      endcase
    end
  end
endmodule
