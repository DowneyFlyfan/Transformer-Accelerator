`timescale 1ns/1ps
// Full pre-rounding product signs; original normalization channels are direct.
module tri_oracle_fused_input_sign_normalizer (
  input logic clk, rst_n, cfg_valid,
  output logic cfg_ready,
  input logic [31:0] cfg_tag,
  input logic [9:0] cfg_strips,
  input logic [63:0] cfg_epsilon_q16,
  input logic signed [7:0] cfg_gamma_exponent,
  input logic stats_valid,
  output logic stats_ready,
  input logic stats_last,
  input logic [255:0] stats_data,
  input logic [127:0] stats_gamma,
  input logic replay_valid,
  output logic replay_ready,
  input logic replay_last,
  input logic [255:0] replay_data,
  input logic [127:0] replay_gamma,
  output logic out_valid,
  input logic out_ready,
  output logic out_last, out_error,
  output logic [31:0] out_tag,
  output logic [9:0] out_index,
  output logic [3:0] out_count,
  output logic [63:0] out_activation,
  output logic signed [8:0] out_exponent,
  output logic [7:0] out_outlier_mask, out_outlier_negative,
  output logic [7:0] out_normalized_negative
);
  logic [7:0] accepted_negative;
  tri_oracle_fused_input_normalizer base (.*);
  assign out_normalized_negative = out_error ? 8'b0 : accepted_negative;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) accepted_negative <= 8'b0;
    else if (replay_valid && replay_ready) begin
      for (int lane = 0; lane < 8; lane++) begin
        accepted_negative[lane] <=
            (replay_data[lane*32+:32] != 32'b0) &&
            (replay_gamma[lane*16+:16] != 16'b0) &&
            (replay_data[lane*32+31] ^ replay_gamma[lane*16+15]);
      end
    end
  end
endmodule
