`timescale 1ns/1ps

// Read each token's 2,048 sign bits as four contiguous 512-bit beats.
// The merge descriptor supplies the initial 64-byte line address. The
// merger starts its comparison when sign_valid arrives, so fetch one vector
// ahead of ready. Each image has storage for 576 vectors. A later frame may
// consume fewer, with the unused buffered vector discarded at completion.
// A response fault drains its burst and retries the same address. Reset
// cancels both the merge and any transaction on the shared physical link.
module tri_oracle_token_sign_dma (
  input logic clk, rst_n, merge_start, merge_finish, config_valid,
  input logic [35:0] config_line,
  output logic sign_valid,
  input logic sign_ready,
  output logic [2047:0] sign_data,
  input logic native_req_valid,
  output logic native_req_ready,
  input logic [63:0] native_req_address,
  input logic [5:0] native_req_length,
  output logic native_rsp_valid,
  input logic native_rsp_ready,
  output logic native_rsp_last, native_rsp_error,
  output logic [511:0] native_rsp_data,
  output logic req_valid,
  input logic req_ready,
  output logic [63:0] req_address,
  output logic [5:0] req_length,
  input logic rsp_valid,
  output logic rsp_ready,
  input logic rsp_last, rsp_error,
  input logic [511:0] rsp_data
);
  typedef enum logic [2:0] {Idle, Request, Receive, Drain, Present} state_t;
  state_t state;
  logic merge_active, configured, native_busy, owns_lane, matching_tail;
  logic [36:0] line_address;
  logic [9:0] vectors_remaining;
  logic [1:0] beat_index;

  assign owns_lane = state != Idle;
  assign req_valid = rst_n && (owns_lane ? state == Request : native_req_valid);
  assign req_address = owns_lane ? {21'd0, line_address, 6'd0} : native_req_address;
  assign req_length = owns_lane ? 6'd4 : native_req_length;
  assign native_req_ready = rst_n && !owns_lane && req_ready;
  assign native_rsp_valid = rst_n && !owns_lane && rsp_valid;
  assign {native_rsp_last, native_rsp_error, native_rsp_data} = {rsp_last, rsp_error, rsp_data};
  assign rsp_ready = rst_n && (owns_lane ? (state == Receive || state == Drain) : native_rsp_ready);
  assign sign_valid = rst_n && state == Present && configured && !merge_finish;
  assign matching_tail = rsp_last == (&beat_index);

  for (genvar beat = 0; beat < 4; beat++) begin : vector_beat
    always_ff @(posedge clk)
      if (state == Receive && rsp_valid && !rsp_error && matching_tail && beat_index == 2'(beat))
        sign_data[beat * 512 +: 512] <= rsp_data;
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state <= Idle;
      merge_active <= 0;
      configured <= 0;
      native_busy <= 0;
      line_address <= 0;
      vectors_remaining <= 0;
      beat_index <= 0;
    end else begin
      if (native_rsp_valid && native_rsp_ready && rsp_last) native_busy <= 0;
      if (native_req_valid && native_req_ready) native_busy <= 1;
      if (merge_start || merge_finish) begin
        merge_active <= merge_start;
        configured <= 0;
      end else if (merge_active && config_valid) begin
        configured <= 1;
        line_address <= {1'b0, config_line};
        vectors_remaining <= 10'd576;
      end

      case (state)
        Idle: if (configured && vectors_remaining != 0 && !merge_finish && !native_busy && !native_req_valid)
          state <= Request;
        Request: if (req_ready) begin
          beat_index <= 0;
          state <= Receive;
        end
        Receive: if (rsp_valid) begin
          if (!matching_tail || rsp_error)
            state <= !rsp_last ? Drain : configured && !merge_finish ? Request : Idle;
          else if (rsp_last)
            state <= configured && !merge_finish ? Present : Idle;
          else beat_index <= beat_index + 1'b1;
        end
        Drain: if (rsp_valid && rsp_last)
          state <= configured && !merge_finish ? Request : Idle;
        Present: if (!configured || merge_finish || sign_ready) begin
          if (sign_valid && sign_ready) begin
            line_address <= line_address + 37'd4;
            vectors_remaining <= vectors_remaining - 1'b1;
          end
          state <= Idle;
        end
        default: state <= Idle;
      endcase
    end
  end
endmodule
