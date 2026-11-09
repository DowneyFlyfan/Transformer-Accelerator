`timescale 1ns/1ps
// Pre-learned-scale root-mean-square normalization for prediction.
// Local format: signed16 raw codes, epsilon in raw-code-squared Q16,
// signed16 normalized Q8. Two framed passes avoid a duplicate vector memory.
module tri_oracle_rmsnorm (
    input logic clk,
    input logic rst_n,
    input logic cfg_valid,
    output logic cfg_ready,
    input logic [31:0] cfg_tag,
    input logic [9:0] cfg_strips,
    input logic [31:0] cfg_epsilon_q16,
    input logic stats_valid,
    output logic stats_ready,
    input logic stats_last,
    input logic [127:0] stats_data,
    input logic replay_valid,
    output logic replay_ready,
    input logic replay_last,
    input logic [127:0] replay_data,
    output logic out_valid,
    input logic out_ready,
    output logic out_last,
    output logic out_error,
    output logic [31:0] out_tag,
    output logic [9:0] out_index,
    output logic [3:0] out_count,
    output logic [127:0] out_norm_q8,
    output logic [7:0] out_outlier_mask
);
    localparam int Lanes = 8;
    localparam int SampleWidth = 16;
    localparam int EnergyWidth = 44;
    localparam int DenominatorWidth = 61;
    localparam int CompareWidth = 96;
    localparam int NormFractionBits = 8;
    localparam int EpsilonFractionBits = 16;
    localparam int SquareShift = 2 * NormFractionBits + 2 + EpsilonFractionBits;
    localparam logic [9:0] MaxStrips = 10'd512;
    localparam logic [15:0] MaxNormCode = 16'd16384;
    localparam logic [15:0] ThreeSigmaCode = 16'd768;
    localparam logic [3:0] FinalIteration = 4'd14;
    typedef enum logic [2:0] {
        Idle, Stats, Replay, Search, Output, DrainStats, DrainReplay, Error
    } state_t;
    state_t state;
    logic [31:0] tag, epsilon_q16;
    logic [9:0] strips, stats_seen, replay_seen, saved_index;
    logic [12:0] features;
    logic [EnergyWidth-1:0] stats_energy, replay_energy;
    logic [EnergyWidth-1:0] stats_total, replay_total;
    logic [DenominatorWidth-1:0] denominator, denominator_total;
    logic [CompareWidth-1:0] numerator [0:Lanes-1];
    logic [CompareWidth-1:0] comparison [0:Lanes-1];
    logic [15:0] lower [0:Lanes-1], upper [0:Lanes-1];
    logic [15:0] lower_next [0:Lanes-1], upper_next [0:Lanes-1];
    logic [16:0] midpoint_sum [0:Lanes-1];
    logic [15:0] midpoint [0:Lanes-1];
    logic [31:0] threshold [0:Lanes-1], threshold_square [0:Lanes-1];
    logic [Lanes-1:0] negative, norm_outliers;
    logic [Lanes*SampleWidth-1:0] norm_data;
    logic [3:0] iteration;
    logic saved_last;

    function automatic logic [31:0] square16(input logic signed [15:0] value);
        logic signed [31:0] widened;
        begin
            widened = {{16{value[15]}},value};
            square16 = $unsigned(widened * widened);
        end
    endfunction

    // For k>=1, round(256*abs(x)/RMS)>=k iff
    // x*x*N*2^34 >= (2*k-1)^2 * (sum(x*x)*2^16 + N*epsilon_q16).
    // Both sides are nonnegative and the denominator must be positive.
    // Valid normalized magnitudes are <=256*sqrt(N)<=16384 for N<=4096.
    always_comb begin
        stats_total = stats_energy;
        replay_total = replay_energy;
        for (int lane = 0; lane < Lanes; lane++) begin
            stats_total = stats_total
                + EnergyWidth'(square16($signed(stats_data[lane*SampleWidth+:SampleWidth])));
            replay_total = replay_total
                + EnergyWidth'(square16($signed(replay_data[lane*SampleWidth+:SampleWidth])));
        end
        denominator_total = (DenominatorWidth'(stats_total) << EpsilonFractionBits)
            + DenominatorWidth'(features) * DenominatorWidth'(epsilon_q16);
        for (int lane = 0; lane < Lanes; lane++) begin
            lower_next[lane] = lower[lane];
            upper_next[lane] = upper[lane];
            midpoint_sum[lane] = {1'b0, lower[lane]} + {1'b0, upper[lane]} + 17'd1;
            midpoint[lane] = 16'(midpoint_sum[lane] >> 1);
            threshold[lane] = (32'(midpoint[lane]) << 1) - 32'd1;
            threshold_square[lane] = threshold[lane] * threshold[lane];
            comparison[lane] = CompareWidth'(threshold_square[lane])
                * CompareWidth'(denominator);
            if (lower[lane] < upper[lane]) begin
                if (numerator[lane] >= comparison[lane])
                    lower_next[lane] = midpoint[lane];
                else
                    upper_next[lane] = midpoint[lane] - 16'd1;
            end
        end
        cfg_ready = state == Idle;
        stats_ready = state == Stats || state == DrainStats;
        replay_ready = state == Replay || state == DrainReplay;
        out_valid = state == Output || state == Error;
        out_last = state == Error || saved_last;
        out_error = state == Error;
        out_tag = tag;
        out_index = state == Error ? '0 : saved_index;
        out_count = state == Error ? '0 : 4'(Lanes);
        out_norm_q8 = state == Error ? '0 : norm_data;
        out_outlier_mask = state == Error ? '0 : norm_outliers;
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= Idle;
            tag <= '0;
            epsilon_q16 <= '0;
            strips <= '0;
            stats_seen <= '0;
            replay_seen <= '0;
            saved_index <= '0;
            features <= '0;
            stats_energy <= '0;
            replay_energy <= '0;
            denominator <= '0;
            negative <= '0;
            norm_outliers <= '0;
            norm_data <= '0;
            iteration <= '0;
            saved_last <= 1'b0;
            for (int lane = 0; lane < Lanes; lane++) begin
                numerator[lane] <= '0;
                lower[lane] <= '0;
                upper[lane] <= '0;
            end
        end else begin
            case (state)
                Idle: if (cfg_valid) begin
                    tag <= cfg_tag;
                    strips <= cfg_strips;
                    features <= 13'(cfg_strips) << $clog2(Lanes);
                    epsilon_q16 <= cfg_epsilon_q16;
                    stats_seen <= '0;
                    replay_seen <= '0;
                    stats_energy <= '0;
                    replay_energy <= '0;
                    norm_data <= '0;
                    norm_outliers <= '0;
                    saved_last <= 1'b0;
                    saved_index <= '0;
                    if (cfg_strips == 0 || cfg_strips > MaxStrips) state <= Error;
                    else state <= Stats;
                end
                Stats: if (stats_valid) begin
                    if (stats_last) begin
                        if (stats_seen + 10'd1 != strips || denominator_total == 0)
                            state <= Error;
                        else begin
                            stats_energy <= stats_total;
                            denominator <= denominator_total;
                            replay_energy <= '0;
                            replay_seen <= '0;
                            state <= Replay;
                        end
                    end else if (stats_seen + 10'd1 == strips) begin
                        state <= DrainStats;
                    end else begin
                        stats_seen <= stats_seen + 10'd1;
                        stats_energy <= stats_total;
                    end
                end
                DrainStats: if (stats_valid && stats_last) state <= Error;
                Replay: if (replay_valid) begin
                    if (replay_last && replay_seen + 10'd1 != strips) begin
                        state <= Error;
                    end else if (!replay_last && replay_seen + 10'd1 == strips) begin
                        state <= DrainReplay;
                    end else if (replay_last && replay_total != stats_energy) begin
                        state <= Error;
                    end else begin
                        replay_energy <= replay_total;
                        saved_index <= replay_seen;
                        replay_seen <= replay_seen + 10'd1;
                        saved_last <= replay_last;
                        iteration <= '0;
                        for (int lane = 0; lane < Lanes; lane++) begin
                            numerator[lane] <= (CompareWidth'(square16(
                                $signed(replay_data[lane*SampleWidth+:SampleWidth])))
                                * CompareWidth'(features)) << SquareShift;
                            negative[lane] <= replay_data[(lane+1)*SampleWidth-1];
                            lower[lane] <= '0;
                            upper[lane] <= MaxNormCode;
                        end
                        state <= Search;
                    end
                end
                DrainReplay: if (replay_valid && replay_last) state <= Error;
                Search: begin
                    for (int lane = 0; lane < Lanes; lane++) begin
                        lower[lane] <= lower_next[lane];
                        upper[lane] <= upper_next[lane];
                        if (iteration == FinalIteration) begin
                            norm_data[lane*SampleWidth+:SampleWidth] <= negative[lane]
                                ? 16'(-$signed({1'b0, lower_next[lane]})) : lower_next[lane];
                            norm_outliers[lane] <= lower_next[lane] > ThreeSigmaCode;
                        end
                    end
                    if (iteration == FinalIteration) state <= Output;
                    else iteration <= iteration + 4'd1;
                end
                Output: if (out_ready) begin
                    if (saved_last) state <= Idle;
                    else state <= Replay;
                end
                Error: if (out_ready) state <= Idle;
                default: state <= Error;
            endcase
        end
    end
endmodule
