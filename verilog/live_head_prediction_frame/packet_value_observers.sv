`timescale 1ns/1ps
// Observe the complete accepted score payload with its actual clock edge.
// Unused score rows may contain unknown data; descriptors must be known.
module tri_oracle_head_packet_value_probe (
    input logic clk, rst_n,
    input logic tensor_out_valid, tensor_out_ready, tensor_out_last,
    input logic [31:0] tensor_out_tag,
    input logic [3:0] tensor_out_token,
    input logic [7:0] tensor_out_count,
    input logic [3071:0] tensor_out_data
);
    always @(posedge clk) begin
        if (rst_n === 1'b1 && tensor_out_valid === 1'b1 && tensor_out_ready === 1'b1 &&
            !$isunknown({tensor_out_tag,tensor_out_token,tensor_out_last,tensor_out_count}))
            $display("TRACE_HEAD_PACKET_VALUE tick=%0d tag=%08h token=%0d last=%0b count=%0d data=%0768h",
                     $time,tensor_out_tag,tensor_out_token,tensor_out_last,tensor_out_count,tensor_out_data);
    end
endmodule
bind tri_oracle_trained_head_prediction_tb tri_oracle_head_packet_value_probe packet_value_observation(.*);
