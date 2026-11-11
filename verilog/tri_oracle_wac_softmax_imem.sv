`timescale 1ns/1ps
// Pack two scores or weights into each 64-bit input-memory word. The core
// arbitrates these ports with its matrix unit before admitting a softmax row.
module tri_oracle_wac_softmax_imem (
    input  logic clk,
    input  logic [9:0] index,
    input  logic last_key,
    input  logic load_score,
    input  logic read_score,
    input  logic store_weight,
    input  logic read_weight,
    input  logic [25:0] score,
    input  logic [29:0] weight,
    output logic [29:0] read_data,
    output logic [1:0] mem_ce_n,
    output logic [1:0] mem_we_n,
    output logic [8:0] mem_address,
    output logic [1:0][63:0] mem_d,
    input  logic [1:0][63:0] mem_q
);
    logic [25:0] first_score;
    logic [29:0] first_weight;
    logic select_weight;
    logic end_of_word;

    assign end_of_word = index[0] || last_key;
    assign mem_address = index[9:1];
    assign mem_we_n[0] = !(load_score && end_of_word);
    assign mem_we_n[1] = !(store_weight && end_of_word);
    assign mem_ce_n[0] = mem_we_n[0] && !read_score;
    assign mem_ce_n[1] = mem_we_n[1] && !read_weight;
    assign mem_d[0] = index[0] ? {6'b0, score, 6'b0, first_score} : {38'b0, score};
    assign mem_d[1] = index[0] ? {2'b0, weight, 2'b0, first_weight} : {34'b0, weight};
    assign read_data = index[0] ? mem_q[select_weight][61:32] : mem_q[select_weight][29:0];

    always_ff @(posedge clk) begin
        if (load_score && !index[0]) first_score <= score;
        if (store_weight && !index[0]) first_weight <= weight;
        if (read_score || read_weight) select_weight <= read_weight;
    end
endmodule
