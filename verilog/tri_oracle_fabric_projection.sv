`timescale 1ns / 1ps
// Five real four-core partial-sum clusters share one memory transaction port.
// Packet widths, round-robin arbitration and abort protocol are local choices.
module tri_oracle_fabric_projection (
    input logic clk,
    rst_n,
    in_valid,
    in_last,
    in_fallback,
    out_ready,
    input logic [31:0] in_tag,
    input logic [2559:0] in_channels,
    input logic [7:0] in_count,
    input logic [63:0] in_activation_base,
    in_weight_base,
    input logic [9:0] in_features,
    output logic in_ready,
    out_valid,
    out_last,
    out_fallback,
    out_error,
    output logic [31:0] out_tag,
    output logic [7:0] out_count,
    output logic [2559:0] out_channels,
    output logic [5119:0] out_data,
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
  localparam int Clusters = 5;
  localparam int RowsPerCluster = 32;
  localparam int Rows = 160;
  localparam logic [64:0] LastAddress = 65'h0ffffffffffffffff;
  typedef enum logic [2:0] {
    Idle,
    Start,
    Collect,
    AbortDrain,
    ResetChildren,
    Result
  } state_t;
  state_t state;
  logic child_rst_n, last, fallback, result_error;
  logic [31:0] tag;
  logic [7:0] count;
  logic [2559:0] channels;
  logic [5119:0] sums;
  logic [63:0] activation_base, weight_base;
  logic [9:0] features;
  logic [4:0] started, received;
  logic [4:0] child_in_valid, child_in_ready, child_out_valid, child_out_ready;
  logic [4:0] child_out_error, child_req_valid, child_req_ready, child_rsp_valid;
  logic [4:0] child_rsp_ready;
  logic [5:0] child_count[Clusters];
  logic [4:0] child_last, child_fallback;
  logic [31:0] child_tag[Clusters];
  logic [5:0] child_result_count[Clusters];
  logic [511:0] child_channels[Clusters];
  logic [1023:0] child_out_data[Clusters];
  logic [63:0] child_req_address[Clusters];
  logic [63:0] child_rsp_data[Clusters];
  logic [4:0] child_req_length[Clusters];
  logic [64:0] input_bytes, activation_end, weight_end;
  logic invalid_shape, fault_now;
  logic offer, busy, candidate_valid;
  logic [2:0] offer_owner, response_owner, round_robin, candidate;
  logic [63:0] offered_address;
  logic [ 4:0] offered_length;

  always_comb begin
    input_bytes = 65'(in_features) * 65'd8;
    activation_end = {1'b0, in_activation_base} + input_bytes - 1;
    invalid_shape = in_count > 8'(Rows) || in_features == 0 || in_features > 10'd512 ||
                    in_activation_base[2:0] != 0 || in_weight_base[2:0] != 0 ||
                    activation_end > LastAddress;
    weight_end = 0;
    for (int row = 0; row < Rows; row++) begin
      weight_end = {1'b0, in_weight_base} + (65'(in_channels[row*16+:16]) + 1) * input_bytes - 1;
      if (row < int'(in_count) && weight_end > LastAddress) invalid_shape = 1;
    end
    in_ready = state == Idle;
    out_valid = state == Result;
    out_last = last;
    out_fallback = fallback;
    out_error = result_error;
    out_tag = tag;
    out_count = result_error ? 8'b0 : count;
    out_channels = channels;
    out_data = result_error ? 5120'b0 : sums;
    child_in_valid = 0;
    child_out_ready = 0;
    for (int cluster = 0; cluster < Clusters; cluster++) begin
      child_in_valid[cluster]  = state == Start && !started[cluster] && !fault_now;
      child_out_ready[cluster] = state == Collect && !received[cluster] && !fault_now;
    end
  end

  // Shape depends only on captured count, independently of metadata errors.
  // Keep it out of the control block which consumes the fault comparison.
  always_comb begin
    for (int cluster = 0; cluster < Clusters; cluster++) begin
      child_count[cluster] = 0;
      if (int'(count) > cluster * RowsPerCluster) begin
        if (int'(count) - cluster * RowsPerCluster > RowsPerCluster)
          child_count[cluster] = 6'(RowsPerCluster);
        else child_count[cluster] = 6'(int'(count) - cluster * RowsPerCluster);
      end
    end
  end

  always_comb begin
    fault_now = |(child_out_valid & child_out_error);
    for (int cluster = 0; cluster < Clusters; cluster++) begin
      if (child_out_valid[cluster] &&
          (child_tag[cluster] != tag || child_result_count[cluster] != child_count[cluster] ||
           child_channels[cluster] != channels[cluster*512+:512] ||
           child_last[cluster] != last || child_fallback[cluster] != fallback))
        fault_now = 1;
      child_rsp_data[cluster] = busy && response_owner == 3'(cluster) ? rsp_data : 64'b0;
    end
  end

  always_comb begin : arbitrate_memory
    int index;
    candidate = 0;
    candidate_valid = 0;
    index = 0;
    for (int offset = 0; offset < Clusters; offset++) begin
      index = int'(round_robin) + offset;
      if (index >= Clusters) index -= Clusters;
      if (!candidate_valid && child_req_valid[index]) begin
        candidate = 3'(index);
        candidate_valid = 1;
      end
    end
    req_valid = offer;
    req_address = offered_address;
    req_length = offered_length;
    child_req_ready = 0;
    child_rsp_valid = 0;
    rsp_ready = 0;
    if (offer) child_req_ready[offer_owner] = req_ready;
    if (busy) begin
      child_rsp_valid[response_owner] = rsp_valid;
      rsp_ready = child_rsp_ready[response_owner];
    end
  end

  for (genvar cluster = 0; cluster < Clusters; cluster++) begin : clusters
    tri_oracle_cluster_projection unit (
        .clk(clk),
        .rst_n(child_rst_n),
        .in_valid(child_in_valid[cluster]),
        .in_ready(child_in_ready[cluster]),
        .in_last(last),
        .in_fallback(fallback),
        .in_tag(tag),
        .in_channels(channels[cluster*512+:512]),
        .in_count(child_count[cluster]),
        .in_activation_base(activation_base),
        .in_weight_base(weight_base),
        .in_features(features),
        .out_valid(child_out_valid[cluster]),
        .out_ready(child_out_ready[cluster]),
        .out_error(child_out_error[cluster]),
        .out_data(child_out_data[cluster]),
        .out_last(child_last[cluster]),
        .out_fallback(child_fallback[cluster]),
        .out_tag(child_tag[cluster]),
        .out_count(child_result_count[cluster]),
        .out_channels(child_channels[cluster]),
        .req_valid(child_req_valid[cluster]),
        .req_ready(child_req_ready[cluster]),
        .req_address(child_req_address[cluster]),
        .req_length(child_req_length[cluster]),
        .rsp_valid(child_rsp_valid[cluster]),
        .rsp_ready(child_rsp_ready[cluster]),
        .rsp_last(rsp_last),
        .rsp_error(rsp_error),
        .rsp_data(child_rsp_data[cluster])
    );
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      offer <= 0;
      busy <= 0;
      offer_owner <= 0;
      response_owner <= 0;
      round_robin <= 0;
      offered_address <= 0;
      offered_length <= 0;
    end else begin
      if (state == Idle) round_robin <= 0;
      if (offer && req_ready) begin
        offer <= 0;
        busy <= 1;
        response_owner <= offer_owner;
        round_robin <= offer_owner == 3'(Clusters - 1) ? 3'b0 : offer_owner + 1'b1;
      end
      if (busy && rsp_valid && rsp_ready && rsp_last) busy <= 0;
      // Once visible externally, an offer survives a later global error.
      if (!offer && !busy && (state == Start || state == Collect) &&
          !fault_now && candidate_valid) begin
        offer <= 1;
        offer_owner <= candidate;
        offered_address <= child_req_address[candidate];
        offered_length <= child_req_length[candidate];
      end
    end
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state <= Idle;
      child_rst_n <= 0;
      tag <= 0;
      count <= 0;
      channels <= 0;
      sums <= 0;
      last <= 0;
      fallback <= 0;
      result_error <= 0;
      activation_base <= 0;
      weight_base <= 0;
      features <= 0;
      started <= 0;
      received <= 0;
    end else begin
      // Keep child reset on a single registered output across state transitions.
      child_rst_n <= 1;
      if ((state == Start || state == Collect) && fault_now) begin
        result_error <= 1;
        sums <= 0;
        state <= AbortDrain;
      end else
        case (state)
          Idle:
          if (in_valid) begin
            tag <= in_tag;
            count <= in_count;
            channels <= in_channels;
            sums <= 0;
            last <= in_last;
            fallback <= in_fallback;
            result_error <= 0;
            activation_base <= in_activation_base;
            weight_base <= in_weight_base;
            features <= in_features;
            started <= 0;
            received <= 0;
            if (in_count == 0) state <= Result;
            else if (invalid_shape) begin
              result_error <= 1;
              state <= Result;
            end else state <= Start;
          end
          Start: begin
            started <= started | child_in_ready;
            if (&(started | child_in_ready)) state <= Collect;
          end
          Collect: begin
            received <= received | child_out_valid;
            for (int cluster = 0; cluster < Clusters; cluster++) begin
              if (child_out_valid[cluster] && !received[cluster])
                sums[cluster*1024+:1024] <= child_out_data[cluster];
            end
            if (&(received | child_out_valid)) state <= Result;
          end
          AbortDrain: if (!offer && !busy) begin
            child_rst_n <= 0;
            state <= ResetChildren;
          end
          ResetChildren: state <= Result;
          Result: if (out_ready) state <= Idle;
          default: begin
            result_error <= 1;
            state <= AbortDrain;
          end
        endcase
    end
  end
endmodule
