`timescale 1ns / 1ps
// Updated to modern SystemVerilog
// Fetch all raw statistics, then raw/learned-coefficient replay pairs.
// Each read owns two64-bit beats through actual LAST, including fault drain.
// Delivered strips remain provisional until this reader and preparation succeed.
// Raw/coefficient memory stays stable for the token. Reset also resets the peer.
module tri_oracle_activation_loader (
    input logic clk,
    rst_n,
    cfg_valid,
    output logic cfg_ready,
    input logic [31:0] cfg_tag,
    input logic [9:0] cfg_strips,
    input logic [63:0] cfg_raw_base,
    cfg_gamma_base,
    output logic stats_valid,
    input logic stats_ready,
    output logic stats_last,
    output logic [127:0] stats_data,
    output logic replay_valid,
    input logic replay_ready,
    output logic replay_last,
    output logic [127:0] replay_data,
    replay_gamma,
    output logic done_valid,
    input logic done_ready,
    output logic done_error,
    output logic [31:0] done_tag,
    output logic req_valid,
    input logic req_ready,
    output logic [63:0] req_address,
    output logic [4:0] req_length,
    input logic rsp_valid,
    output logic rsp_ready,
    input logic rsp_last,
    rsp_error,
    input logic [63:0] rsp_data
);
  localparam int WordWidth = 64;
  localparam int StripBytesLog2 = 4;
  localparam int MaxStrips = 512;
  localparam int StripIndexWidth = $clog2(MaxStrips);
  localparam logic [4:0] ReadBeats = 5'd2;
  localparam logic [64:0] LastAddress = 65'h0_ffff_ffff_ffff_ffff;
  typedef enum logic [2:0] {
    Idle,
    Request,
    Response,
    StatisticsOutput,
    ReplayOutput,
    Drain,
    Done
  } state_t;
  typedef enum logic [1:0] {
    StatisticsRaw,
    ReplayRaw,
    ReplayGamma
  } phase_t;
  state_t state;
  phase_t phase;
  logic [63:0] raw_base, gamma_base;
  logic [9:0] strips;
  logic [StripIndexWidth-1:0] strip_index;
  logic second_beat;
  logic [2*WordWidth-1:0] raw_word, gamma_word;
  logic [64:0] allocation_bytes, raw_end, gamma_end;
  logic invalid_config, final_strip;

  always_comb begin
    allocation_bytes = 65'(cfg_strips) << StripBytesLog2;
    raw_end = {1'b0, cfg_raw_base} + allocation_bytes - 65'd1;
    gamma_end = {1'b0, cfg_gamma_base} + allocation_bytes - 65'd1;
    invalid_config = cfg_strips == 0 || cfg_strips > 10'(MaxStrips) ||
            cfg_raw_base[2:0] != 0 || cfg_gamma_base[2:0] != 0 ||
            raw_end > LastAddress || gamma_end > LastAddress;
    final_strip = 10'(strip_index) + 10'd1 == strips;
    cfg_ready = state == Idle;
    stats_valid = state == StatisticsOutput;
    stats_last = final_strip;
    stats_data = raw_word;
    replay_valid = state == ReplayOutput;
    replay_last = final_strip;
    replay_data = raw_word;
    replay_gamma = gamma_word;
    done_valid = state == Done;
    req_valid = state == Request;
    req_address = (phase == ReplayGamma ? gamma_base : raw_base)
            + (WordWidth'(strip_index) << StripBytesLog2);
    req_length = ReadBeats;
    rsp_ready = state == Response || state == Drain;
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state <= Idle;
      phase <= StatisticsRaw;
      raw_base <= '0;
      gamma_base <= '0;
      strips <= '0;
      strip_index <= '0;
      second_beat <= 1'b0;
      raw_word <= '0;
      gamma_word <= '0;
      done_error <= 1'b0;
      done_tag <= '0;
    end else begin
      case (state)
        Idle:
        if (cfg_valid) begin
          raw_base <= cfg_raw_base;
          gamma_base <= cfg_gamma_base;
          strips <= cfg_strips;
          strip_index <= '0;
          phase <= StatisticsRaw;
          done_tag <= cfg_tag;
          done_error <= invalid_config;
          if (invalid_config) state <= Done;
          else state <= Request;
        end
        Request:
        if (req_ready) begin
          second_beat <= 1'b0;
          state <= Response;
        end
        Response:
        if (rsp_valid) begin
          if (rsp_error || rsp_last != second_beat) begin
            done_error <= 1'b1;
            if (rsp_last) state <= Done;
            else state <= Drain;
          end else begin
            if (phase == ReplayGamma) begin
              if (second_beat) gamma_word[WordWidth+:WordWidth] <= rsp_data;
              else gamma_word[0+:WordWidth] <= rsp_data;
            end else begin
              if (second_beat) raw_word[WordWidth+:WordWidth] <= rsp_data;
              else raw_word[0+:WordWidth] <= rsp_data;
            end
            if (!second_beat) second_beat <= 1'b1;
            else if (phase == StatisticsRaw) state <= StatisticsOutput;
            else if (phase == ReplayRaw) begin
              phase <= ReplayGamma;
              state <= Request;
            end else state <= ReplayOutput;
          end
        end
        StatisticsOutput:
        if (stats_ready) begin
          if (final_strip) begin
            strip_index <= '0;
            phase <= ReplayRaw;
          end else strip_index <= strip_index + StripIndexWidth'(1);
          state <= Request;
        end
        ReplayOutput:
        if (replay_ready) begin
          if (final_strip) state <= Done;
          else begin
            strip_index <= strip_index + StripIndexWidth'(1);
            phase <= ReplayRaw;
            state <= Request;
          end
        end
        Drain: if (rsp_valid && rsp_last) state <= Done;
        Done:  if (done_ready) state <= Idle;
        default: begin
          done_error <= 1'b1;
          state <= Done;
        end
      endcase
    end
  end
endmodule
