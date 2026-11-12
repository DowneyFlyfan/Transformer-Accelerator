`timescale 1ns/1ps

// Fixed capacity for sixteen tokens with 52 words each. The upper 320
// words use the two 64-bit halves of each 128-bit compiled row.
module tri_oracle_compact_outlier_words (
    input logic clk, read_enable, write_enable,
    input logic [9:0] address,
    input logic [63:0] write_word,
    output logic [63:0] read_word
);
    logic enabled, read_tail, read_half;
    logic [2:0] read_bank;
    logic [127:0] tail_words[5], write_mask, selected_word;
    logic [63:0] lower_word;
    assign enabled = (read_enable || write_enable) && address < 10'd832;
    assign write_mask = {{64{!address[0]}}, {64{address[0]}}};

    TS5N28HPCPSVTA512X64M4F lower_words (
        .CLK(clk), .CEB(!enabled || address[9]), .WEB(!write_enable),
        .A(address[8:0]), .D(write_word), .Q(lower_word)
    );
    for (genvar bank = 0; bank < 5; bank++) begin : upper_words
        logic selected;
        assign selected = enabled && address[9] && address[8:6] == 3'(bank);
        TS5N28HPCPSVTA32X128M2FW memory (
            .CLK(clk), .CEB(!selected), .WEB(!write_enable), .A(address[5:1]),
            .D({write_word, write_word}), .BWEB(write_mask), .Q(tail_words[bank])
        );
    end

    always_ff @(posedge clk) begin
        if (enabled && read_enable && !write_enable) begin
            read_tail <= address[9];
            read_bank <= address[8:6];
            read_half <= address[0];
        end
    end
    assign selected_word = tail_words[read_bank];
    assign read_word = read_tail ? (read_half ? selected_word[127:64] : selected_word[63:0]) : lower_word;
endmodule
