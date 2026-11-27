`timescale 1ns / 1ps
// One POST row of three distinct eight-bit feature channels, low lane first.
// One1024-bit shift buffer; no frame, SRAM, C/core or physical-lease release.
module tri_oracle_post_feature_store_v1 (
    input logic clk,
    input logic rst_n,
    input logic abort_valid,
    input logic producer_idle,
    input logic next_context_owned,
    input logic cfg_valid,
    output logic cfg_ready,
    input logic [1:0] cfg_normalization_role,
    input logic [31:0] cfg_tag,
    input logic [4:0] cfg_layer,
    input logic [15:0] cfg_epoch,
    input logic [9:0] cfg_original_root,
    input logic [9:0] cfg_input_rank,
    input logic [9:0] cfg_kept_rank,
    input logic [63:0] cfg_feature_base,
    input logic [63:0] cfg_feature_bytes,
    input logic [63:0] cfg_code_base,
    input logic [63:0] cfg_code_bytes,
    input logic [63:0] cfg_immutable_input_base,
    input logic [63:0] cfg_immutable_input_bytes,
    input logic aux_valid,
    output logic aux_ready,
    input logic aux_last,
    input logic aux_error,
    input logic [31:0] aux_tag,
    input logic [4:0] aux_layer,
    input logic [15:0] aux_epoch,
    input logic [9:0] aux_original_root,
    input logic [9:0] aux_input_rank,
    input logic [9:0] aux_kept_rank,
    input logic [9:0] aux_index,
    input logic [3:0] aux_count,
    input logic signed [8:0] aux_exponent,
    input logic [7:0] aux_outlier_mask,
    input logic [7:0] aux_normalized_negative,
    input logic [7:0] aux_outlier_negative,
    output logic scalar_req_valid,
    input logic scalar_req_ready,
    output logic [63:0] scalar_req_address,
    output logic [4:0] scalar_req_length,
    output logic scalar_data_valid,
    input logic scalar_data_ready,
    output logic scalar_data_last,
    output logic [63:0] scalar_data,
    output logic [7:0] scalar_strobe,
    input logic scalar_rsp_valid,
    output logic scalar_rsp_ready,
    input logic scalar_rsp_error,
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
    output logic [3:0] acknowledged_lines,
    output logic epoch_fault,
    output logic active,
    output logic port_idle,
    output logic idle
);
  typedef enum logic [3:0] {
    Idle, Collect, OfferRequest, SendData, WaitResponse,
    WaitSourceQuiet, SuccessHeld, ErrorDrain, ErrorHeld, FaultLock
  } state_t;
  state_t state;
  logic job_active, fault_latched, have_exponent;
  logic burst_owned, response_quarantined;
  logic [1023:0] bit_buffer;
  logic [10:0] bit_count;
  logic [2:0] beat_index;
  logic [31:0] saved_tag;
  logic [4:0] saved_layer;
  logic [15:0] saved_epoch;
  logic [9:0] saved_root, saved_input_rank, saved_kept_rank;
  logic signed [8:0] saved_exponent;
  logic [63:0] saved_row_address;
  logic [64:0] feature_last, code_last, immutable_last;
  logic [64:0] feature_row_address, feature_row_last, code_row_address, code_row_last;
  logic configuration_bad, packet_good, cfg_fire, aux_fire;
  logic request_fire, data_fire, response_fire;
  logic unexpected_response, association_bad, fault_now;
  logic auxiliary_drain_window, transfers_quiet;
  logic [23:0] incoming_features;

  function automatic logic overlaps(
      input logic [63:0] first_base, second_base,
      input logic [64:0] first_last, second_last);
    return {1'b0, first_base} <= second_last && {1'b0, second_base} <= first_last;
  endfunction

  always_comb begin
    // Allocations may include padding. Validate their WHOLE extents, as well
    // as this dense kept-rank row, before any feature write can be exposed.
    feature_last = {1'b0, cfg_feature_base} + {1'b0, cfg_feature_bytes} - 65'd1;
    code_last = {1'b0, cfg_code_base} + {1'b0, cfg_code_bytes} - 65'd1;
    immutable_last = {1'b0, cfg_immutable_input_base} + {1'b0, cfg_immutable_input_bytes} - 65'd1;
    feature_row_address = {1'b0, cfg_feature_base} + 65'(cfg_kept_rank) * 65'd768;
    feature_row_last = feature_row_address + 65'd767;
    code_row_address = {1'b0, cfg_code_base} + 65'(cfg_kept_rank) * 65'd2048;
    code_row_last = code_row_address + 65'd2047;
    configuration_bad = cfg_normalization_role != 1 || cfg_layer >= 22 ||
      cfg_original_root >= 576 || cfg_input_rank >= 576 || cfg_kept_rank >= 576 ||
      cfg_input_rank != cfg_kept_rank ||
      cfg_feature_base[5:0] != 0 || cfg_feature_bytes == 0 || cfg_feature_bytes[5:0] != 0 ||
      cfg_code_base[5:0] != 0 || cfg_code_bytes == 0 || cfg_code_bytes[5:0] != 0 ||
      cfg_immutable_input_base[5:0] != 0 || cfg_immutable_input_bytes == 0 ||
      cfg_immutable_input_bytes[5:0] != 0 || feature_last[64] || code_last[64] || immutable_last[64] ||
      feature_row_address[64] || feature_row_last[64] || code_row_address[64] || code_row_last[64] ||
      feature_row_last > feature_last || code_row_last > code_last ||
      overlaps(cfg_feature_base, cfg_code_base, feature_last, code_last) ||
      overlaps(cfg_feature_base, cfg_immutable_input_base, feature_last, immutable_last) ||
      overlaps(cfg_code_base, cfg_immutable_input_base, code_last, immutable_last);

    cfg_ready = rst_n && state == Idle && !job_active && !fault_latched && !response_quarantined &&
      !abort_valid && next_context_owned && producer_idle && !aux_valid && !scalar_rsp_valid;
    cfg_fire = cfg_valid && cfg_ready;
    // Resolve this cone before the ready logic that consumes it. Neither
    // current request acceptance nor data acceptance can create an association.
    unexpected_response = rst_n && scalar_rsp_valid && (!burst_owned || state != WaitResponse);
    association_bad = response_quarantined || unexpected_response;
    packet_good = !aux_error && aux_tag == saved_tag && aux_layer == saved_layer &&
      aux_epoch == saved_epoch && aux_original_root == saved_root &&
      aux_input_rank == saved_input_rank && aux_kept_rank == saved_kept_rank &&
      accepted_strips < 256 && aux_index == {1'b0, accepted_strips} && aux_count == 8 &&
      aux_last == (accepted_strips == 255) && (!have_exponent || aux_exponent == saved_exponent);
    incoming_features = {aux_outlier_negative, aux_normalized_negative, aux_outlier_mask};

    // Ready during an ordinary row is independent of current tuple validity:
    // malformed metadata must be accepted once and fault, not silently stall.
    // Fault drain instead accepts only an actually offered retained C tuple.
    // It may first become aux-visible AFTER fault when the writer opens its
    // ErrorDrain route; Root's registered abort stops fresh C creation. This
    // ownership premise cannot be inferred from producer_idle alone.
    auxiliary_drain_window = state == Collect || state == OfferRequest || state == SendData ||
      state == WaitResponse || state == WaitSourceQuiet || state == ErrorDrain;
    aux_ready = rst_n && job_active && !association_bad &&
      ((!fault_latched && state == Collect && !abort_valid && next_context_owned &&
        accepted_strips < 256 && bit_count < 512) ||
       (fault_latched && auxiliary_drain_window && aux_valid && accepted_strips < 511));
    aux_fire = aux_valid && aux_ready;

    // The offered head is never modified until its actual response ACK.
    // A fault cannot retract a request or any of its eight scalar data beats.
    scalar_req_valid = rst_n && state == OfferRequest;
    scalar_req_address = saved_row_address + {54'b0, acknowledged_lines, 6'b0};
    scalar_req_length = 5'd8;
    scalar_data_valid = rst_n && state == SendData;
    scalar_data_last = beat_index == 7;
    scalar_data = bit_buffer[beat_index*64+:64];
    scalar_strobe = 8'hff;
    scalar_rsp_ready = rst_n && state == WaitResponse && burst_owned && !response_quarantined;
    request_fire = scalar_req_valid && scalar_req_ready;
    data_fire = scalar_data_valid && scalar_data_ready;
    response_fire = scalar_rsp_valid && scalar_rsp_ready;

    // Association uses PRE-edge ownership AND completed data. A response on
    // the request-acceptance edge or final-data edge is not retroactively owned.
    // Known offered request/data traffic may still finish after quarantine,
    // but no response association or new completion can be manufactured.
    fault_now = association_bad || (job_active && (abort_valid || !next_context_owned)) ||
      (cfg_fire && configuration_bad) ||
      (state == Collect && !fault_latched && aux_fire && !packet_good) ||
      (job_active && accepted_strips >= 256 && aux_valid) ||
      (response_fire && scalar_rsp_error);
    transfers_quiet = !burst_owned && !scalar_req_valid && !scalar_data_valid && !scalar_rsp_valid &&
      !association_bad && producer_idle && !aux_valid;

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
    port_idle = rst_n && !scalar_req_valid && !scalar_data_valid && !burst_owned &&
      !scalar_rsp_valid && !association_bad;
    idle = rst_n && state == Idle && !job_active && !fault_latched && !abort_valid &&
      !cfg_valid && !aux_valid && producer_idle && port_idle;
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state <= Idle;
      job_active <= 0;
      fault_latched <= 0;
      have_exponent <= 0;
      burst_owned <= 0;
      response_quarantined <= 0;
      bit_buffer <= '0;
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
      acknowledged_lines <= 0;
    end else begin
      if (fault_now) fault_latched <= 1;
      if (unexpected_response) response_quarantined <= 1;
      // Counts actual transfers, including a malformed or discarded retained
      // tuple. The fault-drain guard stops at511 instead of wrapping this count.
      if (aux_fire) accepted_strips <= accepted_strips + 9'd1;
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
            saved_exponent <= 0;
            saved_row_address <= feature_row_address[63:0];
            have_exponent <= 0;
            bit_buffer <= '0;
            bit_count <= 0;
            beat_index <= 0;
            burst_owned <= 0;
            accepted_strips <= 0;
            acknowledged_lines <= 0;
            if (configuration_bad) state <= ErrorDrain;
            else state <= Collect;
          end
        end
        Collect: begin
          if (association_bad) state <= FaultLock;
          else if (fault_latched || fault_now) state <= ErrorDrain;
          else if (aux_fire) begin
            bit_buffer[bit_count+:24] <= incoming_features;
            bit_count <= bit_count + 11'd24;
            if (!have_exponent) begin
              saved_exponent <= aux_exponent;
              have_exponent <= 1;
            end
            // Every legitimate append begins below512; the largest possible
            // head+tail is528bits. The only payload register is1024bits.
            if (bit_count + 11'd24 >= 512) state <= OfferRequest;
          end
        end
        OfferRequest: begin
          if (request_fire) begin
            burst_owned <= 1;
            beat_index <= 0;
            state <= SendData;
          end
        end
        SendData: begin
          if (data_fire) begin
            if (beat_index == 7) state <= WaitResponse;
            else beat_index <= beat_index + 3'd1;
          end
        end
        WaitResponse: begin
          if (association_bad) state <= FaultLock;
          else if (response_fire) begin
            burst_owned <= 0;
            beat_index <= 0;
            if (bit_count < 512 || acknowledged_lines >= 12) begin
              fault_latched <= 1;
              state <= ErrorDrain;
            end else begin
              bit_buffer <= bit_buffer >> 512;
              bit_count <= bit_count - 11'd512;
              acknowledged_lines <= acknowledged_lines + 4'd1;
              if (fault_latched || fault_now || scalar_rsp_error) state <= ErrorDrain;
              else if (acknowledged_lines == 11) state <= WaitSourceQuiet;
              else state <= Collect;
            end
          end
        end
        WaitSourceQuiet: begin
          if (association_bad) state <= FaultLock;
          else if (fault_latched || fault_now) state <= ErrorDrain;
          else if (transfers_quiet && accepted_strips == 256 && acknowledged_lines == 12 && bit_count == 0)
            state <= SuccessHeld;
        end
        ErrorDrain: begin
          if (association_bad) state <= FaultLock;
          else if (transfers_quiet) begin
            // No scalar offer or owned response remains. Only private bits
            // that were never offered as another line may now be discarded.
            bit_buffer <= '0;
            bit_count <= 0;
            state <= ErrorHeld;
          end
        end
        SuccessHeld: if (done_ready) begin
          // Late faults never rewrite the already offered success tuple.
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
