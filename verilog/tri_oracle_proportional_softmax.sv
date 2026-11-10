`timescale 1ns/1ps
// Proportional softmax for one row of already scheduled attention keys.
// Scores are signed Q8. A zero causal size masks a key. Output approximates
// probability scaled by 65535 using a quantized exponential and reciprocal.
module tri_oracle_proportional_softmax (
    input  logic clk,
    input  logic rst_n,
    input  logic cfg_valid,
    output logic cfg_ready,
    input  logic [10:0] cfg_length,
    output logic cfg_error,
    input  logic in_valid,
    output logic in_ready,
    input  logic signed [15:0] in_score,
    input  logic [9:0] in_size,
    output logic out_valid,
    input  logic out_ready,
    output logic [15:0] out_probability,
    output logic out_last
);
    localparam int MAX_KEYS = 1024;
    typedef enum logic [2:0] {
        IDLE, LOAD, READ_SCORE, WRITE_WEIGHT, DIVIDE, READ_OUTPUT, HOLD_OUTPUT
    } row_state_t;
    row_state_t state;

    logic [9:0] index, last_index;
    logic signed [15:0] maximum;
    // Reuse the single port to replace each packed size/score with its weight.
    logic [29:0] scratch [MAX_KEYS];
    logic [29:0] read_data;
    logic [39:0] weight_sum, remainder;
    logic [28:0] reciprocal;
    logic [5:0] divide_bit;

    // round(2^20 * 2^(-index/64)), including both interpolation endpoints.
    function automatic logic [20:0] exp2_negative(input logic [6:0] address);
        case (address)
            7'd0: exp2_negative = 21'd1048576;
            7'd1: exp2_negative = 21'd1037281;
            7'd2: exp2_negative = 21'd1026107;
            7'd3: exp2_negative = 21'd1015054;
            7'd4: exp2_negative = 21'd1004120;
            7'd5: exp2_negative = 21'd993303;
            7'd6: exp2_negative = 21'd982604;
            7'd7: exp2_negative = 21'd972019;
            7'd8: exp2_negative = 21'd961548;
            7'd9: exp2_negative = 21'd951191;
            7'd10: exp2_negative = 21'd940944;
            7'd11: exp2_negative = 21'd930809;
            7'd12: exp2_negative = 21'd920782;
            7'd13: exp2_negative = 21'd910863;
            7'd14: exp2_negative = 21'd901051;
            7'd15: exp2_negative = 21'd891345;
            7'd16: exp2_negative = 21'd881744;
            7'd17: exp2_negative = 21'd872246;
            7'd18: exp2_negative = 21'd862850;
            7'd19: exp2_negative = 21'd853555;
            7'd20: exp2_negative = 21'd844361;
            7'd21: exp2_negative = 21'd835265;
            7'd22: exp2_negative = 21'd826268;
            7'd23: exp2_negative = 21'd817367;
            7'd24: exp2_negative = 21'd808563;
            7'd25: exp2_negative = 21'd799853;
            7'd26: exp2_negative = 21'd791237;
            7'd27: exp2_negative = 21'd782714;
            7'd28: exp2_negative = 21'd774282;
            7'd29: exp2_negative = 21'd765942;
            7'd30: exp2_negative = 21'd757691;
            7'd31: exp2_negative = 21'd749529;
            7'd32: exp2_negative = 21'd741455;
            7'd33: exp2_negative = 21'd733468;
            7'd34: exp2_negative = 21'd725567;
            7'd35: exp2_negative = 21'd717752;
            7'd36: exp2_negative = 21'd710020;
            7'd37: exp2_negative = 21'd702372;
            7'd38: exp2_negative = 21'd694806;
            7'd39: exp2_negative = 21'd687321;
            7'd40: exp2_negative = 21'd679917;
            7'd41: exp2_negative = 21'd672593;
            7'd42: exp2_negative = 21'd665348;
            7'd43: exp2_negative = 21'd658181;
            7'd44: exp2_negative = 21'd651091;
            7'd45: exp2_negative = 21'd644078;
            7'd46: exp2_negative = 21'd637140;
            7'd47: exp2_negative = 21'd630276;
            7'd48: exp2_negative = 21'd623487;
            7'd49: exp2_negative = 21'd616771;
            7'd50: exp2_negative = 21'd610127;
            7'd51: exp2_negative = 21'd603555;
            7'd52: exp2_negative = 21'd597053;
            7'd53: exp2_negative = 21'd590622;
            7'd54: exp2_negative = 21'd584260;
            7'd55: exp2_negative = 21'd577966;
            7'd56: exp2_negative = 21'd571740;
            7'd57: exp2_negative = 21'd565581;
            7'd58: exp2_negative = 21'd559489;
            7'd59: exp2_negative = 21'd553462;
            7'd60: exp2_negative = 21'd547500;
            7'd61: exp2_negative = 21'd541603;
            7'd62: exp2_negative = 21'd535768;
            7'd63: exp2_negative = 21'd529997;
            7'd64: exp2_negative = 21'd524288;
            default: exp2_negative = '0;
        endcase
    endfunction

    wire [16:0] delta = {maximum[15], maximum} - {read_data[15], read_data[15:0]};
    // Convert the nonnegative Q8 delta into a base-two Q8 exponent.
    wire [16:0] log_delta = 17'((29'(delta) * 29'd5909 + 29'd2048) >> 12);
    wire [6:0] exp_index = {1'b0, log_delta[7:2]};
    wire [20:0] upper = exp2_negative(exp_index);
    wire [20:0] lower = exp2_negative(exp_index + 1'b1);
    wire [20:0] interpolated =
        upper - 21'(((23'(upper) - 23'(lower)) * 23'(log_delta[1:0]) + 23'd2) >> 2);
    // Apply size before the right shift to retain small scores with large groups.
    wire [29:0] fractional_weight = interpolated * read_data[25:16];
    wire [29:0] weighted = read_data[25:16] == 0 ? 30'd0 : fractional_weight >> log_delta[16:8];
    wire [39:0] next_sum = weight_sum + 40'(weighted);

    // One restoring division per row. With a visible key the maximum
    // contributes at least 2^20, so floor(2^48 / sum) fits in 29 bits.
    wire [40:0] shifted_remainder = {remainder, divide_bit == 6'd48};
    wire [40:0] extended_sum = {1'b0, weight_sum};
    wire quotient_bit = shifted_remainder >= extended_sum;
    wire [58:0] normalized = read_data * reciprocal;
    wire [74:0] rounded =
        {normalized, 16'b0} - 75'(normalized) + (75'd1 << 47);

    assign cfg_ready = state == IDLE;
    assign in_ready = state == LOAD;
    assign out_valid = state == HOLD_OUTPUT;
    assign out_last = out_valid && index == last_index;
    assign out_probability = 16'(rounded >> 48);

    always_ff @(posedge clk) begin
        case (state)
            LOAD: if (in_valid) scratch[index] <= {4'b0, in_size, in_score};
            READ_SCORE, READ_OUTPUT: read_data <= scratch[index];
            WRITE_WEIGHT: scratch[index] <= weighted;
            default: ;
        endcase
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= IDLE;
            cfg_error <= 1'b0;
            index <= '0;
            last_index <= '0;
            maximum <= 16'sh8000;
            weight_sum <= '0;
            remainder <= '0;
            reciprocal <= '0;
            divide_bit <= '0;
        end else begin
            cfg_error <= 1'b0;
            case (state)
                IDLE: if (cfg_valid) begin
                    if (cfg_length == 0 || cfg_length > 11'(MAX_KEYS)) begin
                        cfg_error <= 1'b1;
                    end else begin
                        index <= '0;
                        last_index <= 10'(cfg_length - 1'b1);
                        maximum <= 16'sh8000;
                        weight_sum <= '0;
                        reciprocal <= '0;
                        state <= LOAD;
                    end
                end
                LOAD: if (in_valid) begin
                    if (in_size != 0 && in_score > maximum) maximum <= in_score;
                    index <= index + 1'b1;
                    if (index == last_index) begin
                        index <= '0;
                        state <= READ_SCORE;
                    end
                end
                READ_SCORE: state <= WRITE_WEIGHT;
                WRITE_WEIGHT: begin
                    weight_sum <= next_sum;
                    index <= index + 1'b1;
                    state <= READ_SCORE;
                    if (index == last_index) begin
                        index <= '0;
                        remainder <= '0;
                        divide_bit <= 6'd48;
                        // An entirely masked row emits zeros without division.
                        if (next_sum == 0) state <= READ_OUTPUT;
                        else state <= DIVIDE;
                    end
                end
                DIVIDE: begin
                    remainder <= 40'(quotient_bit ? shifted_remainder - extended_sum : shifted_remainder);
                    reciprocal <= {reciprocal[27:0], quotient_bit};
                    divide_bit <= divide_bit - 1'b1;
                    if (divide_bit == 0) state <= READ_OUTPUT;
                end
                READ_OUTPUT: state <= HOLD_OUTPUT;
                HOLD_OUTPUT: if (out_ready) begin
                    index <= index + 1'b1;
                    if (index == last_index) state <= IDLE;
                    else state <= READ_OUTPUT;
                end
                default: state <= IDLE;
            endcase
        end
    end
endmodule
