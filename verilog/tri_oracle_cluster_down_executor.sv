`timescale 1ns/1ps
// Four control engines share one externally owned physical compute cluster.
// Each engine gathers up to eight selected inputs into its own core. One
// common command produces the four-core sum; completion/read adaptation
// returns that same sum to all engines and retires exactly one agreed result.
// The owner must connect cluster_rst_n to the real cluster and hand over only
// when both owners are idle. A fatal packet drains its accepted memory burst,
// resets the complete cluster and all context tags, then returns one error.
module tri_oracle_cluster_down_executor (
    input logic clk, rst_n, in_valid, in_last, in_accumulate, out_ready,
    input logic [31:0] in_tag,
    input logic [5:0] in_count, in_output_count, in_shift,
    input logic [511:0] in_channels,
    input logic [1023:0] in_data,
    input logic [63:0] in_weight_base,
    input logic [16:0] in_dense_features,
    input logic [15:0] in_output_start,
    input logic [3:0] in_slot,
    output logic in_ready, out_valid, out_last, out_error,
    output logic [31:0] out_tag,
    output logic [5:0] out_count,
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
  typedef enum logic [2:0] {IDLE, RUN, ABORT_DRAIN, FLUSH, RESULT} state_t;
  state_t state;
  logic [31:0] tag;
  logic [5:0] output_count;
  logic [15:0] output_start;
  logic [3:0] slot;
  logic last, result_error, flush_second_cycle;
  logic [1023:0] result_data, aggregate_data;
  logic [3:0] child_ready, child_out_valid, child_out_error, child_out_last;
  logic [3:0][31:0] child_out_tag;
  logic [3:0][5:0] child_out_count;
  logic [3:0][15:0] child_out_start;
  logic [3:0][3:0] child_out_slot;
  logic [3:0][1023:0] child_out_data, child_input_data;
  logic [3:0][511:0] child_channels;
  logic [3:0] child_req_valid, child_req_ready, child_rsp_valid, child_rsp_ready;
  logic [3:0][63:0] child_req_address;
  logic [3:0][4:0] child_req_length;
  logic [3:0] child_load_valid, child_load_ready;
  logic [3:0][1:0] child_load_kind;
  logic [3:0][9:0] child_load_address;
  logic [3:0][2047:0] child_load_data;
  logic [3:0][31:0] child_load_rows;
  logic [3:0] child_cmd_valid, child_cmd_ready, child_cmd_accumulate;
  logic [3:0][4:0] child_cmd_weight, child_cmd_mask;
  logic [3:0][9:0] child_cmd_activation;
  logic [3:0][3:0] child_cmd_output, child_read_output;
  logic [3:0] child_read_valid, read_seen;
  logic launch, child_retire, child_reset_n, backend_reset_n, abort_now;
  logic metadata_mismatch, command_mismatch, read_mismatch, unexpected_result;
  logic memory_busy, await_aggregate, aggregate_valid, done_pulse, result_pulse;
  logic [1:0] memory_owner, request_cursor, load_cursor, request_choice, load_choice;
  logic request_pending;
  logic [1:0] pending_owner;
  logic [63:0] pending_address;
  logic [4:0] pending_length;
  logic [63:0] child_weight_base;
  logic request_found, load_found, response_retired;

  // Static ready/reset outputs do not depend on in_valid. Keep this cone
  // separate from command generation for composable ready/valid interfaces.
  always_comb begin
    in_ready = state == IDLE && backend_reset_n && (&child_ready);
    child_reset_n = backend_reset_n;
    cluster_rst_n = backend_reset_n;
  end

  always_comb begin
    child_channels = '0;
    child_input_data = '0;
    for (int core = 0; core < 4; core++)
      for (int lane = 0; lane < 8; lane++)
        if (core*8+lane < int'(in_count)) begin
          child_channels[core][lane*16+:16] = in_channels[(core*8+lane)*16+:16];
          child_input_data[core][lane*32+:32] = in_data[(core*8+lane)*32+:32];
        end
    launch = in_ready && in_valid && in_count <= 32 && in_weight_base[2:0] == 0;
    // Empty packets use a real zero-add/read command but must never inspect
    // a weight address. Keep dummy zero lanes in a safe address range while
    // the wrapper independently retains the original alignment validation.
    child_weight_base = in_count == 0 ? 64'b0 : in_weight_base;
    out_valid = state == RESULT;
    out_tag = tag;
    out_count = result_error ? 6'd0 : output_count;
    out_start = output_start;
    out_slot = slot;
    out_last = last;
    out_error = result_error;
    out_data = result_data;
    // The reset root is a flop output, never a binary-state decoder: RUN001
    // to ABORT010 must not transiently decode FLUSH011 in physical gates.

    metadata_mismatch = 0;
    if (&child_out_valid)
      for (int core = 0; core < 4; core++)
        if (child_out_tag[core] != tag || child_out_slot[core] != slot ||
            child_out_start[core] != output_start || child_out_last[core] != last ||
            child_out_count[core] != output_count || child_out_data[core] != child_out_data[0])
          metadata_mismatch = 1;
    command_mismatch = 0;
    if (&child_cmd_valid)
      for (int core = 1; core < 4; core++)
        if ({child_cmd_weight[core], child_cmd_mask[core], child_cmd_activation[core],
             child_cmd_output[core], child_cmd_accumulate[core]} !=
            {child_cmd_weight[0], child_cmd_mask[0], child_cmd_activation[0],
             child_cmd_output[0], child_cmd_accumulate[0]}) command_mismatch = 1;
    read_mismatch = 0;
    for (int core = 0; core < 4; core++)
      if (child_read_valid[core] && child_read_output[core] != slot) read_mismatch = 1;
    unexpected_result = cluster_out_valid && (!await_aggregate || cluster_out_output != slot);
    abort_now = state == RUN && ((|(child_out_valid & child_out_error)) ||
        cluster_load_error || metadata_mismatch || command_mismatch ||
        read_mismatch || unexpected_result);
    child_retire = state == RUN && (&child_out_valid) && !abort_now;

    request_found = 0;
    request_choice = request_cursor;
    load_found = 0;
    load_choice = load_cursor;
    for (int offset = 0; offset < 4; offset++) begin
      if (!request_found && child_req_valid[(int'(request_cursor)+offset)%4]) begin
        request_found = 1;
        request_choice = 2'(int'(request_cursor)+offset);
      end
      if (!load_found && child_load_valid[(int'(load_cursor)+offset)%4]) begin
        load_found = 1;
        load_choice = 2'(int'(load_cursor)+offset);
      end
    end
    // An advertised request owns the bus even before it is accepted. Retain
    // its identity under backpressure and finish it before an abort reset.
    if (request_pending) request_choice = pending_owner;
    req_valid = request_pending || (state == RUN && !abort_now && !memory_busy && request_found);
    req_address = request_pending ? pending_address : child_req_address[request_choice];
    req_length = request_pending ? pending_length : child_req_length[request_choice];
    child_req_ready = 0;
    if (req_valid && state == RUN && !abort_now) child_req_ready[request_choice] = req_ready;
    child_rsp_valid = 0;
    if (state == RUN && !abort_now && memory_busy) child_rsp_valid[memory_owner] = rsp_valid;
    rsp_ready = memory_busy && ((state == RUN && !abort_now) ? child_rsp_ready[memory_owner] : 1'b1);
    response_retired = rsp_valid && rsp_ready && rsp_last;

    cluster_load_valid = state == RUN && !abort_now && load_found;
    cluster_load_core = load_choice;
    cluster_load_kind = child_load_kind[load_choice];
    cluster_load_address = child_load_address[load_choice];
    cluster_load_data = child_load_data[load_choice];
    cluster_load_rows = child_load_rows[load_choice];
    child_load_ready = 0;
    if (cluster_load_valid) child_load_ready[load_choice] = 1;

    cluster_cmd_valid = state == RUN && !abort_now && (&child_cmd_valid) && !await_aggregate && !aggregate_valid;
    cluster_cmd_weight = child_cmd_weight[0];
    cluster_cmd_mask = child_cmd_mask[0];
    cluster_cmd_activation = child_cmd_activation[0];
    cluster_cmd_output = child_cmd_output[0];
    cluster_cmd_accumulate = child_cmd_accumulate[0];
    child_cmd_ready = {4{cluster_cmd_valid && cluster_cmd_ready}};
    cluster_out_ready = state == RUN && !abort_now && await_aggregate && !aggregate_valid;
  end

  tri_oracle_down_executor engines[3:0] (
      .clk(clk), .rst_n(child_reset_n), .in_valid(launch), .in_ready(child_ready),
      .in_last(in_last), .in_accumulate(in_accumulate), .in_tag(in_tag),
      .in_count(6'd8), .in_output_count(in_output_count), .in_shift(in_shift),
      .in_channels(child_channels), .in_data(child_input_data),
      .in_weight_base(child_weight_base), .in_dense_features(in_dense_features),
      .in_output_start(in_output_start), .in_slot(in_slot), .out_ready(child_retire),
      .out_valid(child_out_valid), .out_last(child_out_last), .out_error(child_out_error),
      .out_tag(child_out_tag), .out_count(child_out_count), .out_start(child_out_start),
      .out_slot(child_out_slot), .out_data(child_out_data),
      .req_valid(child_req_valid), .req_ready(child_req_ready),
      .req_address(child_req_address), .req_length(child_req_length),
      .rsp_valid(child_rsp_valid), .rsp_last(rsp_last), .rsp_error(rsp_error),
      .rsp_ready(child_rsp_ready), .rsp_data(rsp_data),
      .core_load_valid(child_load_valid), .core_load_ready(child_load_ready),
      .core_load_error(cluster_load_error), .core_load_kind(child_load_kind),
      .core_load_address(child_load_address), .core_load_data(child_load_data),
      .core_load_rows(child_load_rows), .core_cmd_valid(child_cmd_valid),
      .core_cmd_ready(child_cmd_ready), .core_cmd_weight(child_cmd_weight),
      .core_cmd_mask(child_cmd_mask), .core_cmd_activation(child_cmd_activation),
      .core_cmd_output(child_cmd_output), .core_cmd_accumulate(child_cmd_accumulate),
      .core_done_valid(done_pulse), .core_done_output(slot),
      .core_read_valid(child_read_valid), .core_read_output(child_read_output),
      .core_result_valid(result_pulse), .core_result_data(aggregate_data)
  );

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state <= IDLE;
      backend_reset_n <= 0;
      tag <= 0; output_count <= 0; output_start <= 0; slot <= 0;
      last <= 0; result_error <= 0; flush_second_cycle <= 0;
      result_data <= 0; aggregate_data <= 0;
      memory_busy <= 0; memory_owner <= 0; request_cursor <= 0; load_cursor <= 0;
      request_pending <= 0; pending_owner <= 0; pending_address <= 0; pending_length <= 0;
      await_aggregate <= 0; aggregate_valid <= 0;
      read_seen <= 0; done_pulse <= 0; result_pulse <= 0;
    end else begin
      backend_reset_n <= 1;
      done_pulse <= 0;
      result_pulse <= 0;
      if (req_valid && req_ready) begin
        memory_busy <= 1;
        memory_owner <= request_choice;
        request_cursor <= request_choice + 2'd1;
        request_pending <= 0;
      end else if (req_valid && !request_pending) begin
        request_pending <= 1;
        pending_owner <= request_choice;
        pending_address <= req_address;
        pending_length <= req_length;
      end
      if (response_retired) memory_busy <= 0;
      if (cluster_load_valid) load_cursor <= load_choice + 2'd1;
      if (cluster_cmd_valid && cluster_cmd_ready) begin
        await_aggregate <= 1;
        read_seen <= 0;
      end
      if (cluster_out_valid && cluster_out_ready) begin
        aggregate_data <= cluster_out_data;
        aggregate_valid <= 1;
        await_aggregate <= 0;
        done_pulse <= 1;
      end
      if (state == RUN && aggregate_valid && !abort_now) begin
        read_seen <= read_seen | child_read_valid;
        if (&(read_seen | child_read_valid)) begin
          result_pulse <= 1;
          aggregate_valid <= 0;
          read_seen <= 0;
        end
      end
      case (state)
        IDLE: if (in_valid && in_ready) begin
          tag <= in_tag; output_count <= in_output_count;
          output_start <= in_output_start; slot <= in_slot; last <= in_last;
          result_error <= 0; result_data <= 0;
          await_aggregate <= 0; aggregate_valid <= 0; read_seen <= 0;
          if (in_count > 32 || in_weight_base[2:0] != 0) begin
            result_error <= 1;
            flush_second_cycle <= 0;
            backend_reset_n <= 0;
            state <= FLUSH;
          end else state <= RUN;
        end
        RUN: begin
          if (abort_now) begin
            result_error <= 1;
            result_data <= 0;
            flush_second_cycle <= 0;
            state <= ((memory_busy && !response_retired) || req_valid) ? ABORT_DRAIN : FLUSH;
            if (!((memory_busy && !response_retired) || req_valid)) backend_reset_n <= 0;
          end else if (&child_out_valid) begin
            result_data <= child_out_data[0];
            state <= RESULT;
          end
        end
        ABORT_DRAIN: if ((!memory_busy && !request_pending && !req_valid) || response_retired) begin
          state <= FLUSH;
          backend_reset_n <= 0;
        end
        FLUSH: begin
          await_aggregate <= 0;
          aggregate_valid <= 0;
          read_seen <= 0;
          done_pulse <= 0;
          result_pulse <= 0;
          memory_busy <= 0;
          request_pending <= 0;
          if (flush_second_cycle) state <= RESULT;
          else begin
            backend_reset_n <= 0;
            flush_second_cycle <= 1;
          end
        end
        RESULT: if (out_ready) state <= IDLE;
        default: begin
          result_error <= 1;
          result_data <= 0;
          flush_second_cycle <= 0;
          state <= (memory_busy || request_pending || req_valid) ? ABORT_DRAIN : FLUSH;
          if (!(memory_busy || request_pending || req_valid)) backend_reset_n <= 0;
        end
      endcase
    end
  end
endmodule
