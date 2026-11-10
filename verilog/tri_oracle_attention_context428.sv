`timescale 1ns/1ps
// Four 512-by-64 memory macros hold 22 maps. Thirty-two 10-bit origins
// pack into five 64-bit words, so each 576-origin layer uses 90 words.
// The caller owns validity and issues only in-range layer IDs while idle.
module tri_oracle_attention_context428 (
    input logic clk, rst_n,
    output logic idle,
    input logic [4:0] layer,
    input logic save_start, save_cancel, save_valid,
    output logic save_ready,
    input logic [9:0] save_origin,
    input logic restore_start, restore_ready,
    output logic restore_valid, restore_last,
    output logic [9:0] restore_origin
);
    typedef enum logic [2:0] {Idle, Collect, WriteWords, ReadIssue, ReadCapture, Emit} state_t;
    state_t state;
    logic [10:0] address;
    logic [4:0] group_index, origin_lane;
    logic [2:0] word_lane;
    logic [319:0] packed_origins;
    logic [63:0] memory_data, memory_output[4];
    logic write_enable, read_enable;

    assign idle = state==Idle;
    assign save_ready = state==Collect && !save_cancel;
    assign restore_valid = state==Emit;
    assign restore_origin = packed_origins[int'(origin_lane)*10+:10];
    assign restore_last = restore_valid && group_index==17 && origin_lane==31;
    assign write_enable = state==WriteWords && !save_cancel;
    assign read_enable = state==ReadIssue;
    assign memory_data = packed_origins[int'(word_lane)*64+:64];

    for (genvar bank=0;bank<4;bank++) begin : banks
        wire select_bank = (write_enable || read_enable) && address[10:9]==2'(bank);
        TS5N28HPCPSVTA512X64M4F memory (
            .CLK(clk), .CEB(!select_bank), .WEB(!write_enable),
            .A(address[8:0]), .D(memory_data), .Q(memory_output[bank])
        );
    end

    always_ff @(posedge clk) begin
        if (save_ready && save_valid)
            packed_origins[int'(origin_lane)*10+:10] <= save_origin;
        if (state==ReadCapture)
            packed_origins[int'(word_lane)*64+:64] <= memory_output[address[10:9]];
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= Idle;
            address <= 0;
            group_index <= 0;
            origin_lane <= 0;
            word_lane <= 0;
        end else case (state)
            Idle: if (save_start || restore_start) begin
                address <= 11'(layer)*11'd90;
                group_index <= 0;
                origin_lane <= 0;
                word_lane <= 0;
                if (save_start) state <= Collect;
                else state <= ReadIssue;
            end
            Collect: begin
                if (save_cancel) state <= Idle;
                else if (save_valid) begin
                    origin_lane <= origin_lane+1'b1;
                    if (origin_lane==31) state <= WriteWords;
                end
            end
            WriteWords: begin
                if (save_cancel) state <= Idle;
                else begin
                    address <= address+1'b1;
                    if (word_lane==4) begin
                        word_lane <= 0;
                        group_index <= group_index+1'b1;
                        if (group_index==17) state <= Idle;
                        else state <= Collect;
                    end else word_lane <= word_lane+1'b1;
                end
            end
            ReadIssue: state <= ReadCapture;
            ReadCapture: begin
                address <= address+1'b1;
                if (word_lane==4) begin
                    word_lane <= 0;
                    state <= Emit;
                end else begin
                    word_lane <= word_lane+1'b1;
                    state <= ReadIssue;
                end
            end
            Emit: if (restore_ready) begin
                origin_lane <= origin_lane+1'b1;
                if (origin_lane==31) begin
                    group_index <= group_index+1'b1;
                    if (group_index==17) state <= Idle;
                    else state <= ReadIssue;
                end
            end
            default: state <= Idle;
        endcase
    end
endmodule
