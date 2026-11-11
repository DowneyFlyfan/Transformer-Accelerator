`timescale 1ns/1ps
// Four 30-bit scores or weights share one 128-bit aggregator memory word.
// The owner supplies the synchronous read outputs of four 16-by-128 macros.
module tri_oracle_softmax_iomem (
    input  logic clk,
    input  logic rst_n,
    input  logic begin_row,
    input  logic load,
    input  logic [7:0] slot,
    input  logic signed [15:0] in_score,
    input  logic [9:0] in_size,
    input  logic read_slot,
    input  logic write_weight,
    input  logic [29:0] weighted,
    input  logic flush,
    output logic write_valid,
    output logic read_valid,
    output logic [5:0] write_line,
    output logic [5:0] read_line,
    output logic [127:0] write_data,
    input  logic [3:0][127:0] memory_q,
    output logic [29:0] read_data
);
    logic partial;
    logic [5:0] partial_line;
    logic [7:0] read_pointer;
    logic [127:0] packed_scores, next_scores, selected_line;

    assign read_valid = rst_n && read_slot;
    assign read_line = slot[7:2];
    assign selected_line = memory_q[read_pointer[7:6]];
    assign read_data = selected_line[int'(read_pointer[1:0]) * 30 +: 30];

    always_comb begin
        next_scores = slot[1:0] == 0 ? '0 : packed_scores;
        // Masked scores can be unknown at the input and always produce zero weight.
        next_scores[int'(slot[1:0]) * 30 +: 30] = {4'b0, in_size, in_size == 0 ? 16'b0 : in_score};

        write_valid = rst_n && (write_weight || (load && slot[1:0] == 3) || (flush && partial));
        write_line = load ? slot[7:2] : partial_line;
        write_data = load ? next_scores : packed_scores;
        if (write_weight) begin
            write_line = read_pointer[7:2];
            write_data = selected_line;
            write_data[int'(read_pointer[1:0]) * 30 +: 30] = weighted;
        end
    end

    always_ff @(posedge clk) begin
        if (load) begin
            packed_scores <= next_scores;
            partial_line <= slot[7:2];
        end
        if (read_valid) read_pointer <= slot;
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) partial <= 0;
        else if (begin_row || flush) partial <= 0;
        else if (load) partial <= slot[1:0] != 3;
    end
endmodule
