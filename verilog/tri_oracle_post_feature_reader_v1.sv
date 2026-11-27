`timescale 1ns / 1ps
// One committed POST feature row, no SRAM/fabric/normalizer or lease release.
// Each strip is {input-space outlier sign, full normalized sign, mask}, with
// the mask byte lowest. The archive has no identity/exponent header: the held
// caller context must join the real descriptor and completed feature writes.
module tri_oracle_post_feature_reader_v1 (
  input logic clk,
  input logic rst_n,
  input logic abort_valid,
  input logic next_context_owned,
  input logic cfg_valid,
  output logic cfg_ready,
  input logic cfg_archive_committed,
  input logic [1:0] cfg_normalization_role,
  input logic [31:0] cfg_tag,
  input logic [4:0] cfg_layer,
  input logic [15:0] cfg_epoch,
  input logic [9:0] cfg_original_root,
  input logic [9:0] cfg_input_rank,
  input logic [9:0] cfg_kept_rank,
  input logic signed [8:0] cfg_exponent,
  input logic [63:0] cfg_feature_base,
  input logic [63:0] cfg_feature_bytes,
  output logic req_valid,
  input logic req_ready,
  output logic [63:0] req_address,
  output logic [4:0] req_length,
  input logic rsp_valid,
  output logic rsp_ready,
  input logic rsp_last,
  input logic rsp_error,
  input logic [63:0] rsp_data,
  output logic out_valid,
  input logic out_ready,
  output logic out_last,
  output logic out_error,
  output logic [31:0] out_tag,
  output logic [4:0] out_layer,
  output logic [15:0] out_epoch,
  output logic [9:0] out_original_root,
  output logic [9:0] out_input_rank,
  output logic [9:0] out_kept_rank,
  output logic [9:0] out_index,
  output logic [3:0] out_count,
  output logic signed [8:0] out_exponent,
  output logic [7:0] out_outlier_mask,
  output logic [7:0] out_normalized_negative,
  output logic [7:0] out_outlier_negative,
  output logic done_valid,
  input logic done_ready,
  output logic done_error,
  output logic [31:0] done_tag,
  output logic [4:0] done_layer,
  output logic [15:0] done_epoch,
  output logic [9:0] done_original_root,
  output logic [9:0] done_input_rank,
  output logic [9:0] done_kept_rank,
  output logic signed [8:0] done_exponent,
  output logic [8:0] accepted_strips,
  output logic [3:0] completed_lines,
  output logic [6:0] received_beats,
  output logic epoch_fault,
  output logic active,
  output logic port_idle,
  output logic idle
);
  typedef enum logic [3:0] {
    Idle, OfferRequest, ReceiveLine, DrainRead, EmitStrip, WaitQuiet,
    ErrorDrain, SuccessHeld, ErrorHeld, FaultLock
  } state_t;
  state_t state;
  logic job_active, fault_latched, response_quarantined, burst_owned;
  // The low0/8/16 carry bits survive between lines. A complete next line
  // occupies at most16+512=528 bits. No response is appended while emitting.
  logic [527:0] reservoir;
  logic [9:0] bit_count;
  logic [2:0] beat_index;
  logic [31:0] saved_tag;
  logic [4:0] saved_layer;
  logic [15:0] saved_epoch;
  logic [9:0] saved_root, saved_input_rank, saved_kept_rank;
  logic signed [8:0] saved_exponent;
  logic [63:0] saved_row_address;
  logic [64:0] feature_last, row_address, row_last;
  logic configuration_bad, cfg_fire, request_fire, response_fire, output_fire;
  logic unexpected_response, association_bad, response_bad, internal_bad, fault_now;
  logic transfers_quiet;
  integer unsigned append_offset;

  always_comb begin
    feature_last = {1'b0, cfg_feature_base} + {1'b0, cfg_feature_bytes} - 65'd1;
    row_address = {1'b0, cfg_feature_base} + 65'(cfg_kept_rank) * 65'd768;
    row_last = row_address + 65'd767;
    configuration_bad = cfg_normalization_role != 1 || cfg_layer >= 22 ||
      cfg_original_root >= 576 || cfg_input_rank >= 576 || cfg_kept_rank >= 576 ||
      cfg_input_rank != cfg_kept_rank || cfg_feature_base[5:0] != 0 ||
      cfg_feature_bytes == 0 || cfg_feature_bytes[5:0] != 0 ||
      feature_last[64] || row_address[64] || row_last[64] || row_last > feature_last;

    cfg_ready = rst_n && state == Idle && !job_active && !fault_latched &&
      !response_quarantined && !abort_valid && next_context_owned &&
      cfg_archive_committed && !rsp_valid;
    cfg_fire = cfg_valid && cfg_ready;

    // Neither current request acceptance nor response appearance can create
    // an association. Ready depends only on PRE-edge owned-burst state.
    req_valid = rst_n && state == OfferRequest;
    req_address = saved_row_address + {54'b0, completed_lines, 6'b0};
    req_length = 5'd8;
    rsp_ready = rst_n && burst_owned && !response_quarantined &&
      (state == ReceiveLine || state == DrainRead);
    request_fire = req_valid && req_ready;
    response_fire = rsp_valid && rsp_ready;
    unexpected_response = rst_n && rsp_valid && (!burst_owned ||
      (state != ReceiveLine && state != DrainRead));
    association_bad = response_quarantined || unexpected_response;
    response_bad = rsp_error || rsp_last != (beat_index == 7);
    internal_bad = (state == ReceiveLine &&
      (bit_count > 16 || bit_count[2:0] != 0 || completed_lines >= 12)) ||
      (state == EmitStrip && (bit_count < 24 || bit_count > 528 || accepted_strips >= 256));
    fault_now = association_bad || (job_active && (abort_valid || !next_context_owned)) ||
      (cfg_fire && configuration_bad) ||
      (response_fire && state == ReceiveLine && response_bad) || internal_bad;
    append_offset = int'(bit_count) + int'(beat_index) * 64;

    // This state is entered ONLY after the actual eighth error-free beat.
    // Once exposed, a strip is irrevocable even on abort/lost owner/unknown
    // response. It retires once; fault then prevents another strip offer.
    out_valid = rst_n && state == EmitStrip && bit_count >= 24 && accepted_strips < 256;
    out_last = accepted_strips == 255;
    out_error = 0;
    out_tag = saved_tag;
    out_layer = saved_layer;
    out_epoch = saved_epoch;
    out_original_root = saved_root;
    out_input_rank = saved_input_rank;
    out_kept_rank = saved_kept_rank;
    out_index = {1'b0, accepted_strips};
    out_count = 4'd8;
    out_exponent = saved_exponent;
    out_outlier_mask = reservoir[7:0];
    out_normalized_negative = reservoir[15:8];
    out_outlier_negative = reservoir[23:16];
    output_fire = out_valid && out_ready;

    done_valid = rst_n && (state == SuccessHeld || state == ErrorHeld);
    done_error = state == ErrorHeld;
    done_tag = saved_tag;
    done_layer = saved_layer;
    done_epoch = saved_epoch;
    done_original_root = saved_root;
    done_input_rank = saved_input_rank;
    done_kept_rank = saved_kept_rank;
    done_exponent = saved_exponent;
    epoch_fault = rst_n && (fault_latched || fault_now);
    active = rst_n && job_active;
    port_idle = rst_n && !req_valid && !burst_owned && !rsp_valid && !association_bad;
    transfers_quiet = port_idle && !out_valid;
    idle = rst_n && state == Idle && !job_active && !fault_latched &&
      !response_quarantined && !abort_valid && !cfg_valid && port_idle;
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state <= Idle;
      job_active <= 0;
      fault_latched <= 0;
      response_quarantined <= 0;
      burst_owned <= 0;
      reservoir <= '0;
      bit_count <= 0;
      beat_index <= 0;
      saved_tag <= 0;
      saved_layer <= 0;
      saved_epoch <= 0;
      saved_root <= 0;
      saved_input_rank <= 0;
      saved_kept_rank <= 0;
      saved_exponent <= 0;
      saved_row_address <= 0;
      accepted_strips <= 0;
      completed_lines <= 0;
      received_beats <= 0;
    end else begin
      if (fault_now) fault_latched <= 1;
      if (unexpected_response) response_quarantined <= 1;
      // Actual owned response transfers, including discarded fault drainage.
      // Malformed peers may run past96; saturate rather than wrap at127.
      if (response_fire && received_beats != 127) received_beats <= received_beats + 7'd1;
      if (output_fire) accepted_strips <= accepted_strips + 9'd1;

      case (state)
        Idle: begin
          if (association_bad) state <= FaultLock;
          else if (cfg_fire) begin
            job_active <= 1;
            saved_tag <= cfg_tag;
            saved_layer <= cfg_layer;
            saved_epoch <= cfg_epoch;
            saved_root <= cfg_original_root;
            saved_input_rank <= cfg_input_rank;
            saved_kept_rank <= cfg_kept_rank;
            saved_exponent <= cfg_exponent;
            saved_row_address <= row_address[63:0];
            reservoir <= '0;
            bit_count <= 0;
            beat_index <= 0;
            burst_owned <= 0;
            accepted_strips <= 0;
            completed_lines <= 0;
            received_beats <= 0;
            if (configuration_bad) state <= ErrorDrain;
            else state <= OfferRequest;
          end
        end
        OfferRequest: begin
          // Even a fault/unknown response cannot withdraw this existing
          // command. A later acceptance never legitimizes an earlier response.
          if (request_fire) begin
            burst_owned <= 1;
            beat_index <= 0;
            state <= ReceiveLine;
          end
        end
        ReceiveLine: begin
          if (association_bad) state <= FaultLock;
          else if (response_fire) begin
            if (response_bad || internal_bad || fault_latched || fault_now) begin
              if (rsp_last) begin burst_owned <= 0; state <= ErrorDrain; end
              else state <= DrainRead;
            end else begin
              // Maximum index is16+7*64+63=527. DrainRead never appends an
              // extra malformed ninth beat, so dynamic selection stays bounded.
              reservoir[append_offset+:64] <= rsp_data;
              if (beat_index == 7) begin
                burst_owned <= 0;
                completed_lines <= completed_lines + 4'd1;
                bit_count <= bit_count + 10'd512;
                beat_index <= 0;
                state <= EmitStrip;
              end else beat_index <= beat_index + 3'd1;
            end
          end
        end
        DrainRead: begin
          if (association_bad) state <= FaultLock;
          else if (response_fire && rsp_last) begin
            burst_owned <= 0;
            state <= ErrorDrain;
          end
        end
        EmitStrip: begin
          if (internal_bad) state <= association_bad ? FaultLock : ErrorDrain;
          else if (output_fire) begin
            reservoir <= reservoir >> 24;
            bit_count <= bit_count - 10'd24;
            if (association_bad) state <= FaultLock;
            else if (fault_latched || fault_now) state <= ErrorDrain;
            else if (accepted_strips == 255) state <= WaitQuiet;
            else if (bit_count < 48) state <= OfferRequest;
          end
          // With no handshake the exposed strip AND state remain held. This
          // includes quarantine; the consumer can still retire that old offer.
        end
        WaitQuiet: begin
          if (association_bad) state <= FaultLock;
          else if (fault_latched || fault_now) state <= ErrorDrain;
          else if (transfers_quiet && accepted_strips == 256 && completed_lines == 12 &&
                   received_beats == 96 && bit_count == 0) state <= SuccessHeld;
        end
        ErrorDrain: begin
          if (association_bad) state <= FaultLock;
          else if (transfers_quiet) begin
            // Only unexposed private bits remain. No public tuple is cancelled.
            reservoir <= '0;
            bit_count <= 0;
            state <= ErrorHeld;
          end
        end
        SuccessHeld: if (done_ready) begin
          // Late faults never rewrite an earlier offered success or release
          // its protected context; only the earlier status itself can ACK.
          if (fault_latched || fault_now || association_bad) state <= FaultLock;
          else begin job_active <= 0; state <= Idle; end
        end
        ErrorHeld: if (done_ready) state <= FaultLock;
        FaultLock: begin end
        default: begin fault_latched <= 1; state <= FaultLock; end
      endcase
    end
  end
endmodule
