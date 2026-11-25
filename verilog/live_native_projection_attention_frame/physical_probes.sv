// Passive observers: no data, reset, clock or handshake feedback.
module tri_oracle_head_array_probe (
    input logic clk,rst_n,in_valid,in_ready,out_valid,out_ready,
    input logic [2047:0] operand_a,operand_b,
    input logic [255:0] lane_enable,
    input logic [607:0] out_sums
);
    initial $display("HEAD_ARRAY path=%m");
    always @(posedge clk) if(rst_n && !tri_oracle_trained_head_prediction_tb.projection_phase)begin
        if(in_valid && in_ready)
            $display("HEAD_ARRAY_INPUT path=%m tick=%0t a=%0512h b=%0512h mask=%064h",$time,operand_a,operand_b,lane_enable);
        if(out_valid && out_ready)
            $display("HEAD_ARRAY_OUTPUT path=%m tick=%0t sums=%0152h",$time,out_sums);
    end
endmodule
bind tri_oracle_pe_array tri_oracle_head_array_probe head_array_witness(.*);

module tri_oracle_head_core_probe (
    input logic clk,rst_n,cmd_valid,cmd_ready,cmd_accumulate,done_valid
);
    always @(posedge clk) if(rst_n && !tri_oracle_trained_head_prediction_tb.projection_phase)begin
        if(cmd_valid && cmd_ready)
            $display("HEAD_PHYSICAL_ISSUE path=%m tick=%0t accumulate=%0d",$time,cmd_accumulate);
        if(done_valid)$display("HEAD_PHYSICAL_DONE path=%m tick=%0t",$time);
    end
endmodule
bind tri_oracle_sram_strip_core448 tri_oracle_head_core_probe head_physical_witness(.*);
