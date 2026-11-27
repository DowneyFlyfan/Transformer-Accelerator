`timescale 1ns / 1ps
// One POST row, one cache-line register, and a coupled auxiliary-strip route.
// No C/core/TMU/SRAM or physical-lease release is instantiated here.
module tri_oracle_post_normalized_row_writer_v1 (
    input logic clk, rst_n, abort_valid, producer_idle,
    input logic cfg_valid,
    output logic cfg_ready,
    input logic [1:0] cfg_normalization_role,
    input logic [31:0] cfg_tag,
    input logic [4:0] cfg_layer,
    input logic [15:0] cfg_epoch,
    input logic [9:0] cfg_original_root, cfg_input_rank, cfg_kept_rank,
    input logic [63:0] cfg_code_base, cfg_immutable_input_base, cfg_immutable_input_bytes,
    input logic next_context_owned,

    input logic in_valid, in_last, in_error,
    output logic in_ready,
    input logic [31:0] in_tag,
    input logic [9:0] in_index,
    input logic [3:0] in_count,
    input logic [63:0] in_activation,
    input logic signed [8:0] in_exponent,
    input logic [7:0] in_outlier_mask, in_normalized_negative, in_outlier_negative,

    // The future phase consumer owns the external feature serialization route.
    // These fields MUST transfer on exactly the same edge as the input strip:
    // no independent fork and no alias of input-space sign to full gamma sign.
    output logic aux_valid,
    input logic aux_ready,
    output logic aux_last, aux_error,
    output logic [31:0] aux_tag,
    output logic [4:0] aux_layer,
    output logic [15:0] aux_epoch,
    output logic [9:0] aux_original_root, aux_input_rank, aux_kept_rank, aux_index,
    output logic [3:0] aux_count,
    output logic signed [8:0] aux_exponent,
    output logic [7:0] aux_outlier_mask, aux_normalized_negative, aux_outlier_negative,

    // Existing 512-bit external-write-mux client; one actual ACK per line.
    output logic vector_req_valid,
    input logic vector_req_ready,
    output logic [63:0] vector_req_address,
    output logic [511:0] vector_req_data,
    input logic vector_rsp_valid, vector_rsp_error,
    output logic vector_rsp_ready,
    // Descriptor write through the existing physical NextOwner lease. No
    // acquire/release port exists: this primitive cannot release that lease.
    output logic next_req_valid, next_req_write,
    input logic next_req_ready,
    output logic [9:0] next_req_word,
    output logic [63:0] next_req_data,
    input logic next_rsp_valid, next_rsp_error,
    input logic [63:0] next_rsp_data,
    output logic next_rsp_ready,

    // Row success proves atomic aux acceptance, not the consumer's later DMA.
    // Whole POST completion must additionally join that consumer's owned drain.
    output logic done_valid, done_error, epoch_fault, active, idle,
    input logic done_ready,
    output logic [31:0] done_tag,
    output logic [4:0] done_layer,
    output logic [15:0] done_epoch,
    output logic [9:0] done_original_root, done_input_rank, done_kept_rank,
    output logic signed [8:0] done_exponent,
    output logic [8:0] accepted_strips,
    output logic [5:0] acknowledged_lines,
    output logic descriptor_acknowledged
);
  typedef enum logic [3:0] {
    Idle, Receive, OfferVector, WaitVector, WaitSourceQuiet,
    OfferDescriptor, WaitDescriptor, SuccessHeld, ErrorDrain, ErrorHeld, FaultLock
  } state_t;
  state_t state;
  logic job_active, fault_latched, have_exponent, input_terminal;
  logic vector_owned, descriptor_owned, vector_quarantined, descriptor_quarantined;
  logic [31:0] saved_tag;
  logic [4:0] saved_layer;
  logic [15:0] saved_epoch;
  logic [9:0] saved_root, saved_input_rank, saved_kept_rank;
  logic signed [8:0] saved_exponent;
  logic [63:0] saved_row_address;
  logic [511:0] line_data;
  logic [4:0] line_index;
  logic cfg_fire, input_fire, vector_request_fire, vector_response_fire;
  logic descriptor_request_fire, descriptor_response_fire;
  logic configuration_bad, beat_valid, fault_now, association_bad;
  logic unexpected_vector_response, unexpected_descriptor_response;
  logic [64:0] immutable_last, row_address, row_last;
  logic auxiliary_window, transfers_quiet;

  always_comb begin
    // The external code space and the NextOwner SRAM word space are distinct.
    // This primitive validates exactly the selected 2048-byte code row.
    immutable_last = {1'b0, cfg_immutable_input_base} + {1'b0, cfg_immutable_input_bytes} - 65'd1;
    row_address = {1'b0, cfg_code_base} + 65'(cfg_kept_rank) * 65'd2048;
    row_last = row_address + 65'd2047;
    configuration_bad = cfg_normalization_role != 1 || cfg_layer >= 22 ||
      cfg_original_root >= 576 || cfg_input_rank >= 576 || cfg_kept_rank >= 576 ||
      cfg_input_rank != cfg_kept_rank || cfg_code_base[5:0] != 0 ||
      cfg_immutable_input_base[5:0] != 0 || cfg_immutable_input_bytes == 0 ||
      cfg_immutable_input_bytes[5:0] != 0 || immutable_last[64] || row_address[64] || row_last[64] ||
      !((immutable_last < row_address) || (row_last < {1'b0, cfg_immutable_input_base}));
    cfg_ready = rst_n && state == Idle && !fault_latched && next_context_owned && !abort_valid &&
      producer_idle && !in_valid && !vector_rsp_valid && !next_rsp_valid;
    cfg_fire = cfg_valid && cfg_ready;

    beat_valid = !in_error && in_tag == saved_tag && accepted_strips < 256 &&
      in_index == {1'b0, accepted_strips} && in_count == 8 && in_last == (accepted_strips == 255) &&
      (!have_exponent || in_exponent == saved_exponent);

    // Receive and fault drainage have the SAME auxiliary acceptance relation.
    // A fault cannot retract an exposed feature tuple. The qualified source
    // holds all strip fields until this joint handshake; no independent fork
    // can accept metadata while the code slot is unavailable.
    auxiliary_window = state == Receive || state == ErrorDrain;
    aux_valid = rst_n && auxiliary_window && in_valid;
    in_ready = rst_n && auxiliary_window && aux_ready;
    input_fire = in_valid && in_ready;
    aux_tag = in_tag;
    aux_layer = saved_layer;
    aux_epoch = saved_epoch;
    aux_original_root = saved_root;
    aux_input_rank = saved_input_rank;
    aux_kept_rank = saved_kept_rank;
    aux_index = in_index;
    aux_count = in_count;
    aux_last = in_last;
    aux_error = in_error;
    aux_exponent = in_exponent;
    aux_outlier_mask = in_outlier_mask;
    aux_normalized_negative = in_normalized_negative;
    aux_outlier_negative = in_outlier_negative;

    vector_req_valid = rst_n && state == OfferVector;
    vector_req_address = saved_row_address + {53'b0, line_index, 6'b0};
    vector_req_data = line_data;
    vector_rsp_ready = rst_n && vector_owned && !vector_quarantined;
    vector_request_fire = vector_req_valid && vector_req_ready;
    vector_response_fire = vector_rsp_valid && vector_rsp_ready;
    next_req_valid = rst_n && state == OfferDescriptor;
    next_req_write = 1;
    next_req_word = 10'd256 + saved_kept_rank;
    next_req_data = {3'b010, saved_exponent, saved_kept_rank, saved_root, saved_tag};
    next_rsp_ready = rst_n && descriptor_owned && !descriptor_quarantined;
    descriptor_request_fire = next_req_valid && next_req_ready;
    descriptor_response_fire = next_rsp_valid && next_rsp_ready;

    // Association is evaluated against ownership BEFORE the current edge.
    // Later acceptance of an already offered write cannot legitimize a response
    // that arrived before ownership. Other known-owned work can still drain.
    unexpected_vector_response = vector_rsp_valid && !vector_owned && (job_active || cfg_fire);
    unexpected_descriptor_response = next_rsp_valid && !descriptor_owned && (job_active || cfg_fire);
    association_bad = vector_quarantined || descriptor_quarantined ||
      unexpected_vector_response || unexpected_descriptor_response;
    fault_now = (job_active && (abort_valid || !next_context_owned)) || association_bad ||
      (cfg_fire && configuration_bad) ||
      (state == Receive && input_fire && !beat_valid) ||
      (job_active && accepted_strips >= 256 && in_valid) ||
      (vector_response_fire && vector_rsp_error) || (descriptor_response_fire && next_rsp_error);
    transfers_quiet = !vector_owned && !descriptor_owned && !vector_rsp_valid && !next_rsp_valid &&
      !vector_req_valid && !next_req_valid && producer_idle && !in_valid && !aux_valid;

    done_valid = rst_n && (state == SuccessHeld || state == ErrorHeld);
    done_error = state == ErrorHeld;
    done_tag = saved_tag;
    done_layer = saved_layer;
    done_epoch = saved_epoch;
    done_original_root = saved_root;
    done_input_rank = saved_input_rank;
    done_kept_rank = saved_kept_rank;
    done_exponent = saved_exponent;
    epoch_fault = rst_n && fault_latched;
    active = rst_n && job_active;
    idle = rst_n && state == Idle && !job_active && !fault_latched && producer_idle &&
      !in_valid && !cfg_valid && !vector_rsp_valid && !next_rsp_valid;
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state <= Idle;
      job_active <= 0;
      fault_latched <= 0;
      have_exponent <= 0;
      input_terminal <= 0;
      vector_owned <= 0;
      descriptor_owned <= 0;
      vector_quarantined <= 0;
      descriptor_quarantined <= 0;
      saved_tag <= 0;
      saved_layer <= 0;
      saved_epoch <= 0;
      saved_root <= 0;
      saved_input_rank <= 0;
      saved_kept_rank <= 0;
      saved_exponent <= 0;
      saved_row_address <= 0;
      line_data <= 0;
      line_index <= 0;
      accepted_strips <= 0;
      acknowledged_lines <= 0;
      descriptor_acknowledged <= 0;
    end else begin
      if (fault_now) fault_latched <= 1;
      if (unexpected_vector_response) vector_quarantined <= 1;
      if (unexpected_descriptor_response) descriptor_quarantined <= 1;
      if (vector_request_fire) vector_owned <= 1;
      if (descriptor_request_fire) descriptor_owned <= 1;
      if (vector_response_fire) begin
        vector_owned <= 0;
        if (!vector_rsp_error && acknowledged_lines < 32) acknowledged_lines <= acknowledged_lines + 1'b1;
      end
      if (descriptor_response_fire) begin
        descriptor_owned <= 0;
        if (!next_rsp_error) descriptor_acknowledged <= 1;
      end
      if (input_fire) begin
        if (accepted_strips != 9'h1ff) accepted_strips <= accepted_strips + 1'b1;
        if (in_last) input_terminal <= 1;
      end

      case (state)
        Idle: if (cfg_fire) begin
          job_active <= 1;
          saved_tag <= cfg_tag;
          saved_layer <= cfg_layer;
          saved_epoch <= cfg_epoch;
          saved_root <= cfg_original_root;
          saved_input_rank <= cfg_input_rank;
          saved_kept_rank <= cfg_kept_rank;
          saved_row_address <= row_address[63:0];
          saved_exponent <= 0;
          have_exponent <= 0;
          input_terminal <= 0;
          accepted_strips <= 0;
          acknowledged_lines <= 0;
          descriptor_acknowledged <= 0;
          line_index <= 0;
          line_data <= 0;
          state <= state_t'((configuration_bad || fault_now) ? ErrorDrain : Receive);
        end
        Receive: begin
          if (fault_latched || fault_now) state <= ErrorDrain;
          else if (input_fire) begin
            line_data[accepted_strips[2:0]*64+:64] <= in_activation;
            if (!have_exponent) begin saved_exponent <= in_exponent; have_exponent <= 1; end
            if (accepted_strips[2:0] == 7) state <= OfferVector;
          end
        end
        // Already exposed offers survive abort/ownership faults. If their
        // association was poisoned, readiness on that response channel remains
        // blocked until coupled reset rather than consuming an unrelated ACK.
        OfferVector: if (vector_request_fire) state <= WaitVector;
        WaitVector: if (vector_response_fire) begin
          if (fault_latched || fault_now || vector_rsp_error) state <= ErrorDrain;
          else if (acknowledged_lines == 31) state <= WaitSourceQuiet;
          else begin line_index <= line_index + 1'b1; state <= Receive; end
        end
        WaitSourceQuiet: begin
          if (fault_latched || fault_now) state <= ErrorDrain;
          else if (transfers_quiet) begin
            if (accepted_strips == 256 && acknowledged_lines == 32 && input_terminal && have_exponent)
              state <= OfferDescriptor;
            else begin fault_latched <= 1; state <= ErrorDrain; end
          end
        end
        OfferDescriptor: if (descriptor_request_fire) state <= WaitDescriptor;
        WaitDescriptor: if (descriptor_response_fire) begin
          if (fault_latched || fault_now || next_rsp_error) state <= ErrorDrain;
          else state <= SuccessHeld;
        end
        SuccessHeld: if (done_ready) begin
          // The visible successful tuple is immutable through late faults;
          // its ACK cannot release/reuse a faulted context.
          if (fault_latched || fault_now) state <= FaultLock;
          else begin job_active <= 0; state <= Idle; end
        end
        ErrorDrain: if (transfers_quiet) begin
          // No NEW status packet can claim drainage when an unassociated
          // response was observed, even if that response subsequently disappears.
          state <= state_t'(association_bad ? FaultLock : ErrorHeld);
        end
        ErrorHeld: if (done_ready) state <= FaultLock;
        FaultLock: begin end
        default: begin fault_latched <= 1; state <= FaultLock; end
      endcase
    end
  end
endmodule
