`timescale 1ns/1ps
// The coordinator streams a row in order and handles the two row reductions.
// Five local datapaths hold the scores, evaluate the weights and round the outputs.
module tri_oracle_aggregator_softmax (
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
    localparam int BANKS = 5;
    localparam int MAX_KEYS = 1024;

    typedef enum logic [3:0] {
        IDLE, LOAD, REDUCE_MAX, READ_SCORE, WRITE_WEIGHT,
        REDUCE_SUM, DIVIDE, READ_OUTPUT, HOLD_OUTPUT
    } row_state_t;
    row_state_t state;

    logic [9:0] index, last_index;
    logic [2:0] bank_index, last_bank;
    logic [7:0] slot_index, last_slot;
    logic signed [15:0] maximum, row_maximum;
    logic [39:0] row_sum, weight_sum, remainder;
    logic [28:0] reciprocal;
    logic [5:0] divide_bit;

    logic [BANKS-1:0] bank_load, bank_weight_write, bank_output_read;
    logic signed [15:0] bank_maximum [BANKS];
    logic [37:0] bank_sum [BANKS];
    logic [15:0] bank_probability [BANKS];

    wire valid_length = cfg_length != 0 && cfg_length <= 11'(MAX_KEYS);
    wire begin_row = state == IDLE && cfg_valid && valid_length;
    wire [40:0] shifted_remainder = {remainder, divide_bit == 6'd48};
    wire [40:0] extended_sum = {1'b0, weight_sum};
    wire quotient_bit = shifted_remainder >= extended_sum;

    assign cfg_ready = state == IDLE;
    assign in_ready = state == LOAD;
    assign out_valid = state == HOLD_OUTPUT;
    assign out_last = out_valid && index == last_index;
    assign out_probability = bank_probability[bank_index];

    always_comb begin
        row_maximum = 16'sh8000;
        row_sum = '0;
        for (int bank = 0; bank < BANKS; bank++) begin
            if (bank_maximum[bank] > row_maximum) row_maximum = bank_maximum[bank];
            row_sum = row_sum + 40'(bank_sum[bank]);
        end
    end

    for (genvar bank = 0; bank < BANKS; bank++) begin : aggregator
        localparam int ENTRIES = (MAX_KEYS + BANKS - 1 - bank) / BANKS;
        wire active_slot;
        if (bank == 0) assign active_slot = slot_index <= last_slot;
        else assign active_slot = slot_index < last_slot || (slot_index == last_slot && 3'(bank) <= last_bank);
        assign bank_load[bank] = state == LOAD && in_valid && bank_index == 3'(bank);
        assign bank_weight_write[bank] = state == WRITE_WEIGHT && active_slot;
        assign bank_output_read[bank] = state == READ_OUTPUT && bank_index == 3'(bank);
        tri_oracle_softmax_bank #(.ENTRIES(ENTRIES)) datapath (
            .clk, .rst_n, .begin_row, .load(bank_load[bank]), .slot(slot_index), .in_score, .in_size,
            .read_slot((state == READ_SCORE && active_slot) || bank_output_read[bank]),
            .write_weight(bank_weight_write[bank]), .maximum, .reciprocal,
            .local_maximum(bank_maximum[bank]), .local_sum(bank_sum[bank]),
            .probability(bank_probability[bank])
        );
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= IDLE;
            cfg_error <= 0;
            index <= '0;
            last_index <= '0;
            bank_index <= '0;
            last_bank <= '0;
            slot_index <= '0;
            last_slot <= '0;
            maximum <= 16'sh8000;
            weight_sum <= '0;
            remainder <= '0;
            reciprocal <= '0;
            divide_bit <= '0;
        end else begin
            cfg_error <= 0;
            if ((state == LOAD && in_valid) || (out_valid && out_ready)) begin
                index <= index + 1'b1;
                if (bank_index == 3'(BANKS-1)) begin
                    bank_index <= '0;
                    slot_index <= slot_index + 1'b1;
                end else bank_index <= bank_index + 1'b1;
            end
            case (state)
                IDLE: if (cfg_valid) begin
                    if (!valid_length) cfg_error <= 1;
                    else begin
                        index <= '0;
                        last_index <= 10'(cfg_length - 1'b1);
                        bank_index <= '0;
                        slot_index <= '0;
                        reciprocal <= '0;
                        state <= LOAD;
                    end
                end
                LOAD: if (in_valid && index == last_index) begin
                    last_bank <= bank_index;
                    last_slot <= slot_index;
                    index <= '0;
                    bank_index <= '0;
                    slot_index <= '0;
                    state <= REDUCE_MAX;
                end
                REDUCE_MAX: begin
                    maximum <= row_maximum;
                    state <= READ_SCORE;
                end
                READ_SCORE: state <= WRITE_WEIGHT;
                WRITE_WEIGHT: begin
                    if (slot_index == last_slot) begin
                        slot_index <= '0;
                        state <= REDUCE_SUM;
                    end else begin
                        slot_index <= slot_index + 1'b1;
                        state <= READ_SCORE;
                    end
                end
                REDUCE_SUM: begin
                    weight_sum <= row_sum;
                    remainder <= '0;
                    divide_bit <= 6'd48;
                    state <= row_sum == 0 ? READ_OUTPUT : DIVIDE;
                end
                DIVIDE: begin
                    remainder <= 40'(quotient_bit ? shifted_remainder - extended_sum : shifted_remainder);
                    reciprocal <= {reciprocal[27:0], quotient_bit};
                    divide_bit <= divide_bit - 1'b1;
                    if (divide_bit == 0) state <= READ_OUTPUT;
                end
                READ_OUTPUT: state <= HOLD_OUTPUT;
                HOLD_OUTPUT: if (out_ready) state <= out_last ? IDLE : READ_OUTPUT;
                default: state <= IDLE;
            endcase
        end
    end
endmodule
