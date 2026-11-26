`timescale 1ns/1ps
// One immutable row, both passes, one owned read burst. No raw-row memory.
// Memory responses start strictly after request acceptance. Reset is coupled
// to the memory peer; private clear is only the wrapper's fault-reset exception.
module tri_oracle_raw32_gamma24_reader_v1 (
  input logic clk,
  input logic rst_n,
  input logic cfg_valid,
  output logic cfg_ready,
  input logic [31:0] cfg_tag,
  input logic [9:0] cfg_strips,
  input logic [63:0] cfg_raw_base,
  input logic [63:0] cfg_gamma_base,
  input logic abort_valid,
  output logic stats_valid,
  input logic stats_ready,
  output logic stats_last,
  output logic [255:0] stats_data,
  output logic [191:0] stats_gamma,
  output logic replay_valid,
  input logic replay_ready,
  output logic replay_last,
  output logic [255:0] replay_data,
  output logic [191:0] replay_gamma,
  output logic req_valid,
  input logic req_ready,
  output logic [63:0] req_address,
  output logic [4:0] req_length,
  input logic rsp_valid,
  output logic rsp_ready,
  input logic rsp_last,
  input logic rsp_error,
  input logic [63:0] rsp_data,
  output logic port_idle,
  output logic idle,
  output logic row_fault,
  output logic done_valid,
  input logic done_ready,
  output logic done_error,
  output logic [31:0] done_tag,
  input logic clear_valid,
  output logic clear_ready
);
  localparam int RAW_STRIP_BYTES = 32;
  localparam int GAMMA_STRIP_BYTES = 24;
  localparam logic [4:0] RAW_BEATS = 5'd4;
  localparam logic [4:0] GAMMA_BEATS = 5'd3;
  typedef enum logic [3:0] {
    Idle, Request, Response, OfferStats, OfferReplay, Drain, FaultWait,
    Done, ProtocolQuarantine
  } state_t;
  state_t state;
  logic [31:0] tag;
  logic [9:0] strips;
  logic [8:0] strip_index;
  logic [63:0] raw_base, gamma_base;
  logic [255:0] raw_word;
  logic [191:0] gamma_word;
  logic [1:0] beat_index;
  logic replay_pass, gamma_asset;
  logic request_offered, owned_burst, pair_valid, done_pending;
  logic sticky_fault, quarantine;
  logic active, unsolicited, response_bad, fault_now, fault_active;
  logic cfg_fire, request_fire, response_fire, pair_fire, done_fire, clear_fire;
  logic final_strip;
  logic [64:0] raw_last, gamma_last, next_address;
  logic invalid_config;

  assign raw_last = {1'b0,cfg_raw_base} + 65'(cfg_strips)*65'(RAW_STRIP_BYTES) - 65'd1;
  assign gamma_last = {1'b0,cfg_gamma_base} + 65'(cfg_strips)*65'(GAMMA_STRIP_BYTES) - 65'd1;
  assign invalid_config = cfg_strips == 0 || cfg_strips > 512 ||
    cfg_raw_base[2:0] != 0 || cfg_gamma_base[2:0] != 0 || raw_last[64] || gamma_last[64];
  assign next_address = gamma_asset ?
    {1'b0,gamma_base} + 65'(strip_index)*65'(GAMMA_STRIP_BYTES) :
    {1'b0,raw_base} + 65'(strip_index)*65'(RAW_STRIP_BYTES);
  assign active = state != Idle || request_offered || owned_burst || pair_valid || done_pending;
  assign unsolicited = rsp_valid && !owned_burst;
  assign response_bad = rsp_error || (rsp_last != (5'(beat_index)+5'd1 == req_length));
  assign fault_now = (abort_valid && active) || unsolicited ||
    (owned_burst && rsp_valid && response_bad);
  assign fault_active = sticky_fault || fault_now || quarantine;
  assign row_fault = sticky_fault || fault_now || quarantine;
  assign port_idle = rst_n && !request_offered && !owned_burst && !rsp_valid && !quarantine;
  assign cfg_ready = rst_n && state == Idle && !abort_valid && port_idle;
  assign idle = cfg_ready && !cfg_valid && !pair_valid && !done_pending;
  assign req_valid = rst_n && request_offered;
  assign rsp_ready = rst_n && owned_burst;
  assign stats_valid = rst_n && pair_valid && !replay_pass;
  assign replay_valid = rst_n && pair_valid && replay_pass;
  assign final_strip = 10'(strip_index)+10'd1 == strips;
  assign stats_last = final_strip;
  assign replay_last = final_strip;
  assign stats_data = raw_word;
  assign replay_data = raw_word;
  assign stats_gamma = gamma_word;
  assign replay_gamma = gamma_word;
  assign done_valid = rst_n && done_pending;
  assign done_tag = tag;
  assign clear_ready = rst_n && sticky_fault && port_idle && !done_pending && state != Idle;
  assign cfg_fire = cfg_valid && cfg_ready;
  assign request_fire = req_valid && req_ready;
  assign response_fire = rsp_valid && rsp_ready;
  assign pair_fire = pair_valid && (replay_pass ? replay_ready : stats_ready);
  assign done_fire = done_valid && done_ready;
  assign clear_fire = clear_valid && clear_ready;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state <= Idle; tag <= 0; strips <= 0; strip_index <= 0;
      raw_base <= 0; gamma_base <= 0; raw_word <= 0; gamma_word <= 0;
      beat_index <= 0; replay_pass <= 0; gamma_asset <= 0;
      request_offered <= 0; owned_burst <= 0; pair_valid <= 0;
      done_pending <= 0; done_error <= 0; sticky_fault <= 0; quarantine <= 0;
      req_address <= 0; req_length <= 0;
    end else if (cfg_fire) begin
      tag <= cfg_tag; strips <= cfg_strips; raw_base <= cfg_raw_base; gamma_base <= cfg_gamma_base;
      strip_index <= 0; replay_pass <= 0; gamma_asset <= 0; beat_index <= 0;
      raw_word <= 0; gamma_word <= 0; pair_valid <= 0;
      sticky_fault <= invalid_config; done_error <= invalid_config;
      done_pending <= invalid_config;
      state <= invalid_config ? Done : Request;
    end else begin
      // Offers are independent flags: a fault/state transition cannot retract
      // a request, pair, or already offered Done tuple.
      if (done_fire) begin
        done_pending <= 0;
        if (!quarantine && !unsolicited) state <= Idle;
      end
      if (request_fire) begin
        request_offered <= 0; owned_burst <= 1; beat_index <= 0;
        if (!quarantine && !unsolicited) state <= fault_active ? Drain : Response;
      end
      if (response_fire) begin
        if (rsp_last) owned_burst <= 0;
        if (!quarantine) begin
          if (fault_active) begin
            state <= rsp_last ? FaultWait : Drain;
          end else begin
            if (gamma_asset) gamma_word[64*beat_index+:64] <= rsp_data;
            else raw_word[64*beat_index+:64] <= rsp_data;
            if (rsp_last) begin
              if (gamma_asset) begin
                pair_valid <= 1;
                state <= replay_pass ? OfferReplay : OfferStats;
              end else begin
                gamma_asset <= 1; state <= Request;
              end
            end else beat_index <= beat_index + 2'd1;
          end
        end
      end
      if (pair_fire) begin
        pair_valid <= 0;
        if (fault_active) state <= FaultWait;
        else if (final_strip && replay_pass) begin
          done_pending <= 1; done_error <= 0; state <= Done;
        end else begin
          if (final_strip) begin replay_pass <= 1; strip_index <= 0; end
          else strip_index <= strip_index + 9'd1;
          gamma_asset <= 0; state <= Request;
        end
      end
      if (state == Request && !request_offered && !owned_burst && !fault_active) begin
        req_address <= next_address[63:0];
        req_length <= gamma_asset ? GAMMA_BEATS : RAW_BEATS;
        request_offered <= 1;
      end
      if (fault_now) sticky_fault <= 1;
      if (fault_active && active && !done_pending && !quarantine && !unsolicited)
        state <= owned_burst ? Drain : FaultWait;
      if (state == FaultWait && port_idle && !pair_valid && !done_pending) begin
        done_pending <= 1; done_error <= 1; state <= Done;
      end
      if (clear_fire) begin
        pair_valid <= 0; done_pending <= 1; done_error <= 1; state <= Done;
      end
      // A late unsolicited response preserves both request and Done flags.
      // Unknown association is never repaired by observing an arbitrary LAST.
      if (unsolicited || quarantine) begin
        quarantine <= 1; state <= ProtocolQuarantine;
      end
    end
  end
endmodule
