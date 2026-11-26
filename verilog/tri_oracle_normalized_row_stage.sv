`timescale 1ns/1ps
// One normalized row in the existing metadata-memory lease. Row acceptance
// consumes its signs only; the later compact reader explicitly releases it.
module tri_oracle_normalized_row_stage (
  input  logic clk,
  input  logic rst_n,
  input  logic start_valid,
  output logic start_ready,
  input  logic [31:0] start_tag,
  input  logic abort_valid,
  input  logic producer_idle,
  input  logic epoch_clear_valid,
  output logic epoch_clear_ready,
  output logic epoch_invalid,

  input  logic in_valid,
  output logic in_ready,
  input  logic [31:0] in_tag,
  input  logic [9:0] in_index,
  input  logic [3:0] in_count,
  input  logic in_last,
  input  logic in_error,
  input  logic [63:0] in_activation,
  input  logic signed [8:0] in_exponent,
  input  logic [7:0] in_negative,

  output logic memory_acquire_valid,
  input  logic memory_acquire_ready,
  input  logic memory_context_owned,
  output logic memory_release_valid,
  input  logic memory_release_ready,
  output logic memory_req_valid,
  input  logic memory_req_ready,
  output logic memory_req_write,
  output logic [9:0] memory_req_word,
  output logic [63:0] memory_req_data,
  input  logic memory_rsp_valid,
  input  logic memory_rsp_error,
  output logic memory_rsp_ready,

  output logic row_valid,
  input  logic row_ready,
  output logic [31:0] row_tag,
  output logic signed [8:0] row_exponent,
  output logic [2047:0] row_negative,
  output logic row_consumed,
  input  logic release_valid,
  output logic release_ready,
  input  logic consumer_idle,
  output logic lease_held,
  output logic [8:0] accepted_words,
  output logic [8:0] acknowledged_words
);
  typedef enum logic [1:0] {Idle, Receive, Held, Drain} state_t;
  state_t state;
  logic [31:0] saved_tag;
  logic signed [8:0] saved_exponent;
  logic [2047:0] saved_negative;
  logic have_exponent, input_terminal, response_pending;
  logic beat_valid, request_fire, response_fire, release_allowed;

  always_comb begin
    beat_valid = !in_error && in_tag == saved_tag &&
                 in_index == {1'b0, accepted_words} && in_count == 4'd8 &&
                 in_last == (accepted_words == 9'd255) &&
                 (!have_exponent || in_exponent == saved_exponent);

    start_ready = rst_n && state == Idle && !epoch_invalid &&
                  !abort_valid && !epoch_clear_valid && producer_idle &&
                  !in_valid && memory_acquire_ready;
    memory_acquire_valid = rst_n && state == Idle && !epoch_invalid &&
                           !abort_valid && !epoch_clear_valid && producer_idle &&
                           !in_valid && start_valid;
    epoch_clear_ready = rst_n && state == Idle && !memory_context_owned &&
                        !memory_rsp_valid && producer_idle && !in_valid &&
                        consumer_idle && !abort_valid;
    lease_held = rst_n && state != Idle && memory_context_owned;

    memory_req_valid = 1'b0;
    memory_req_write = 1'b1;
    memory_req_word = {1'b0, accepted_words};
    memory_req_data = in_activation;
    in_ready = 1'b0;
    if (rst_n && state == Receive && memory_context_owned && !input_terminal) begin
      if (abort_valid || epoch_invalid) begin
        in_ready = 1'b1;
      end else if (!response_pending) begin
        if (!beat_valid) begin
          in_ready = 1'b1;
        end else begin
          memory_req_valid = in_valid;
          in_ready = memory_req_ready;
        end
      end
    end
    if (rst_n && state == Drain) in_ready = 1'b1;

    memory_rsp_ready = rst_n && memory_context_owned &&
                       ((state == Receive && response_pending) || state == Drain);
    request_fire = memory_req_valid && memory_req_ready;
    response_fire = memory_rsp_valid && memory_rsp_ready;

    row_valid = rst_n && state == Held && memory_context_owned && !row_consumed &&
                !epoch_invalid && !abort_valid;
    row_tag = saved_tag;
    row_exponent = saved_exponent;
    row_negative = epoch_invalid ? 2048'b0 : saved_negative;

    release_allowed = rst_n && !abort_valid && memory_context_owned && consumer_idle &&
                      !response_pending && !memory_rsp_valid &&
                      ((state == Held && row_consumed && !abort_valid) ||
                       (state == Drain && input_terminal && producer_idle && !in_valid));
    memory_release_valid = release_allowed && release_valid;
    release_ready = release_allowed && memory_release_ready;
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state <= Idle;
      saved_tag <= '0;
      saved_exponent <= '0;
      saved_negative <= '0;
      have_exponent <= 1'b0;
      input_terminal <= 1'b0;
      response_pending <= 1'b0;
      row_consumed <= 1'b0;
      accepted_words <= '0;
      acknowledged_words <= '0;
      epoch_invalid <= 1'b0;
    end else begin
      if (epoch_clear_valid && epoch_clear_ready) epoch_invalid <= 1'b0;

      if (start_valid && start_ready) begin
        state <= Receive;
        saved_tag <= start_tag;
        saved_exponent <= '0;
        saved_negative <= '0;
        have_exponent <= 1'b0;
        input_terminal <= 1'b0;
        response_pending <= 1'b0;
        row_consumed <= 1'b0;
        accepted_words <= '0;
        acknowledged_words <= '0;
      end

      if (request_fire) begin
        response_pending <= 1'b1;
        accepted_words <= accepted_words + 9'd1;
        saved_negative[accepted_words[7:0]*8 +: 8] <= in_negative;
        if (!have_exponent) begin
          saved_exponent <= in_exponent;
          have_exponent <= 1'b1;
        end
      end
      if (in_valid && in_ready && in_last) input_terminal <= 1'b1;
      if (state == Drain && producer_idle && !in_valid) input_terminal <= 1'b1;

      if (response_fire) begin
        response_pending <= 1'b0;
        if (response_pending && !memory_rsp_error) begin
          acknowledged_words <= acknowledged_words + 9'd1;
          if (state == Receive && !epoch_invalid && !abort_valid &&
              accepted_words == 9'd256 && input_terminal &&
              acknowledged_words == 9'd255) state <= Held;
        end
      end
      if (row_valid && row_ready) row_consumed <= 1'b1;

      // A malformed accepted beat never becomes a memory request. Existing
      // requests and the rest of the normalizer output are drained, not retried.
      if ((state == Receive && in_valid && in_ready && !beat_valid) ||
          (state == Receive && response_fire && memory_rsp_error) ||
          (state == Receive && memory_rsp_valid && !response_pending) ||
          ((state == Receive || state == Held) && !memory_context_owned) ||
          abort_valid) begin
        epoch_invalid <= 1'b1;
        if (state != Idle) state <= Drain;
      end

      // A consumer must explicitly relinquish the retained row only after its
      // own reader/mux has drained. Sign acceptance alone cannot free this lease.
      if (release_valid && release_ready) begin
        state <= Idle;
        saved_tag <= '0;
        saved_exponent <= '0;
        saved_negative <= '0;
        have_exponent <= 1'b0;
        input_terminal <= 1'b0;
        response_pending <= 1'b0;
        row_consumed <= 1'b0;
        accepted_words <= '0;
        acknowledged_words <= '0;
      end

      // Lost ownership is an epoch fault, never a successful completion. Once
      // every known response and input beat is drained, only epoch_clear permits
      // the parent to begin its separately controlled whole-epoch restart.
      if (state == Drain && !memory_context_owned && !response_pending &&
          !memory_rsp_valid && input_terminal && producer_idle &&
          !in_valid && consumer_idle) state <= Idle;
    end
  end
endmodule
