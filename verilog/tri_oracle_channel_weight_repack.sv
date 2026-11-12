`timescale 1ns/1ps

// Convert eight channel-aligned memory responses into eight existing
// eight-row by eight-feature compute beats. The memory owner supplies
// lane_index in order, skipping masked channels. Byte zero is bits [7:0].
module tri_oracle_channel_weight_repack (
  input  logic clk,
  input  logic rst_n,
  input  logic cfg_valid,
  output logic cfg_ready,
  input  logic cfg_down,
  input  logic [7:0] cfg_keep,
  input  logic lane_valid,
  output logic lane_ready,
  output logic [2:0] lane_index,
  input  logic [511:0] lane_data,
  output logic beat_valid,
  input  logic beat_ready,
  output logic beat_last,
  output logic [2:0] beat_index,
  output logic [511:0] beat_data
);
  typedef enum logic [1:0] {Idle, Gather, Emit} state_t;
  state_t state;
  logic down;
  logic [7:0] keep, pending, remaining;
  logic [511:0] strips [0:7];

  assign cfg_ready = rst_n && state == Idle;
  assign lane_ready = rst_n && state == Gather;
  assign beat_valid = rst_n && state == Emit;
  assign beat_last = beat_valid && beat_index == 3'd7;
  assign remaining = pending & ~(8'b1 << lane_index);

  always_comb begin
    lane_index = 0;
    for (int lane = 7; lane >= 0; lane--)
      if (pending[lane]) lane_index = 3'(lane);
  end

  always_comb begin
    beat_data = '0;
    for (int lane = 0; lane < 8; lane++) begin
      logic [63:0] word;
      word = strips[lane][{beat_index, 6'b0} +: 64];
      if (keep[lane]) begin
        if (down) begin
          // The input channel is a feature column of the down matrix.
          for (int row = 0; row < 8; row++)
            beat_data[(row * 8 + lane) * 8 +: 8] = word[row * 8 +: 8];
        end else begin
          beat_data[lane * 64 +: 64] = word;
        end
      end
    end
  end

  // The buffered contents are observed only after every kept lane arrives.
  always_ff @(posedge clk)
    if (lane_ready && lane_valid) strips[lane_index] <= lane_data;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state <= Idle;
      down <= 0;
      keep <= 0;
      pending <= 0;
      beat_index <= 0;
    end else begin
      case (state)
        Idle: if (cfg_valid) begin
          down <= cfg_down;
          keep <= cfg_keep;
          pending <= cfg_keep;
          beat_index <= 0;
          state <= cfg_keep == 0 ? Emit : Gather;
        end
        Gather: if (lane_valid) begin
          pending <= remaining;
          if (remaining == 0) state <= Emit;
        end
        Emit: if (beat_ready) begin
          if (beat_last) state <= Idle;
          else beat_index <= beat_index + 3'd1;
        end
        default: state <= Idle;
      endcase
    end
  end
endmodule
