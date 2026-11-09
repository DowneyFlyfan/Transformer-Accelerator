`timescale 1ns/1ps
// Small inferred flip-flop bank, not a foundry static-RAM macro.
// Asynchronous reads let the parent register the old word on a write edge.
// No reset on stored bits: preserve core memory retention semantics.
module tri_oracle_word_bank #(
    parameter integer DATA_W=64,
    parameter integer ADDR_W=5
)(
    input wire clk,rst_n,write_enable,
    input wire [ADDR_W-1:0] write_addr,read_addr,second_addr,
    input wire [DATA_W-1:0] write_data,
    output wire [DATA_W-1:0] read_data,second_data
);
    reg [DATA_W-1:0] words [0:(1<<ADDR_W)-1];
    assign read_data=words[read_addr];
    assign second_data=words[second_addr];
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin end // Retain memory; inhibit writes throughout reset.
        else if(write_enable) words[write_addr]<=write_data;
    end
endmodule
