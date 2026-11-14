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
    logic [31:0] replay_square [0:Lanes-1];
    logic [CompareWidth-1:0] trial_delta;
    logic [CompareWidth-1:0] remainder [0:Lanes-1], root_term [0:Lanes-1];
    logic [CompareWidth-1:0] trial [0:Lanes-1];
    logic [CompareWidth:0] trial_remainder [0:Lanes-1];
    logic [14:0] root_code [0:Lanes-1], root_next [0:Lanes-1];
    logic [15:0] rounded_code [0:Lanes-1];
    logic [Lanes-1:0] accept_bit;
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

    // Find floor(sqrt(x*x*N*2^34/denominator)) one bit at a time,
    // then add one and divide by two to round the normalized magnitude.
    // Testing bit b adds d*2^(2*b) + 2*d*r*2^b to the squared root,
    // where d is the denominator and r contains the bits already chosen.
    // The next step halves the second term and quarters the first.
    // A root of 32768 rounds to the same code as the 15-bit cap of 32767.
    always_comb begin
        stats_total = stats_energy;
        replay_total = replay_energy;
        for (int lane = 0; lane < Lanes; lane++) begin
            stats_total = stats_total
                + EnergyWidth'(square16($signed(stats_data[lane*SampleWidth+:SampleWidth])));
            replay_square[lane] = square16($signed(replay_data[lane*SampleWidth+:SampleWidth]));
            replay_total = replay_total + EnergyWidth'(replay_square[lane]);
        end
        denominator_total = (DenominatorWidth'(stats_total) << EpsilonFractionBits)
            + DenominatorWidth'(features) * DenominatorWidth'(epsilon_q16);
        for (int lane = 0; lane < Lanes; lane++) begin
            trial[lane] = root_term[lane] + trial_delta;
            trial_remainder[lane] = {1'b0, remainder[lane]} - {1'b0, trial[lane]};
            accept_bit[lane] = !trial_remainder[lane][CompareWidth];
            root_next[lane] = {root_code[lane][13:0], accept_bit[lane]};
            rounded_code[lane] = ({1'b0, root_next[lane]} + 16'd1) >> 1;
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
            trial_delta <= '0;
            negative <= '0;
            norm_outliers <= '0;
            norm_data <= '0;
            iteration <= '0;
            saved_last <= 1'b0;
            for (int lane = 0; lane < Lanes; lane++) begin
                remainder[lane] <= '0;
                root_term[lane] <= '0;
                root_code[lane] <= '0;
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
                        trial_delta <= CompareWidth'(denominator) << (2 * FinalIteration);
                        for (int lane = 0; lane < Lanes; lane++) begin
                            remainder[lane] <= (CompareWidth'(replay_square[lane])
                                * CompareWidth'(features)) << SquareShift;
                            negative[lane] <= replay_data[(lane+1)*SampleWidth-1];
                            root_term[lane] <= '0;
                            root_code[lane] <= '0;
                        end
                        state <= Search;
                    end
                end
                DrainReplay: if (replay_valid && replay_last) state <= Error;
                Search: begin
                    trial_delta <= trial_delta >> 2;
                    for (int lane = 0; lane < Lanes; lane++) begin
                        root_code[lane] <= root_next[lane];
                        root_term[lane] <= (root_term[lane] >> 1)
                            + (accept_bit[lane] ? trial_delta : '0);
                        if (accept_bit[lane]) remainder[lane] <= trial_remainder[lane][CompareWidth-1:0];
                        if (iteration == FinalIteration) begin
                            norm_data[lane*SampleWidth+:SampleWidth] <= negative[lane]
                                ? 16'(-$signed({1'b0, rounded_code[lane]})) : rounded_code[lane];
                            norm_outliers[lane] <= rounded_code[lane] > ThreeSigmaCode;
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
