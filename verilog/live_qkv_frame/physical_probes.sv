module tri_oracle_score_batch_core_probe (
    input logic clk,rst_n,cmd_valid,cmd_ready,cmd_accumulate,done_valid
);
    always @(posedge clk)if(rst_n && !$root.tri_oracle_shared_attention_projection_tb.ff_phase)begin
        if(cmd_valid && cmd_ready)$display("%s path=%m tick=%0t accumulate=%0d",($root.tri_oracle_shared_attention_projection_tb.qkv_phase ? string'("QKV_PHYSICAL_ISSUE") : string'("SCORE_BATCH_PHYSICAL_ISSUE")),$time,cmd_accumulate);
        if(done_valid)$display("%s path=%m tick=%0t",($root.tri_oracle_shared_attention_projection_tb.qkv_phase ? string'("QKV_PHYSICAL_DONE") : string'("SCORE_BATCH_PHYSICAL_DONE")),$time);
    end
endmodule
bind tri_oracle_sram_strip_core448 tri_oracle_score_batch_core_probe physical_witness(.*);

module tri_oracle_score_batch_array_probe (
    input logic clk,rst_n,in_valid,in_ready,out_valid,out_ready,
    input logic [2047:0] operand_a,operand_b,
    input logic [255:0] lane_enable,
    input logic [607:0] out_sums
);
    initial $display("SCORE_BATCH_ARRAY path=%m");
    always @(posedge clk)if(rst_n && !$root.tri_oracle_shared_attention_projection_tb.ff_phase)begin
        if(in_valid && in_ready)$display("%s path=%m tick=%0t a=%0512h b=%0512h mask=%064h",($root.tri_oracle_shared_attention_projection_tb.qkv_phase ? string'("QKV_ARRAY_INPUT") : string'("SCORE_BATCH_ARRAY_INPUT")),$time,operand_a,operand_b,lane_enable);
        if(out_valid && out_ready)$display("%s path=%m tick=%0t sums=%0152h",($root.tri_oracle_shared_attention_projection_tb.qkv_phase ? string'("QKV_ARRAY_OUTPUT") : string'("SCORE_BATCH_ARRAY_OUTPUT")),$time,out_sums);
    end
endmodule
bind tri_oracle_pe_array tri_oracle_score_batch_array_probe array_witness(.*);
module tri_oracle_score_batch_memory_probe;
    initial $display("SCORE_BATCH_MEMORY path=%m");
endmodule
bind TS5N28HPCPSVTA32X128M2FW tri_oracle_score_batch_memory_probe batch_memory_witness();
bind TS5N28HPCPSVTA512X64M4F tri_oracle_score_batch_memory_probe batch_memory_witness();
bind TS6N28HPCPSVTA16X128M2F tri_oracle_score_batch_memory_probe batch_memory_witness();

module tri_oracle_broker_slot_probe(input logic clk,rst_n,input logic[15:0] mask,
 input logic write,release_valid,input logic[9:0] address,input logic[1023:0] data);
 logic[15:0] previous=0;
 always @(negedge clk)if(!$root.tri_oracle_shared_attention_projection_tb.ff_phase)begin
  if(!rst_n)begin previous=0;$display("BROKER_LEASE_RESET path=%m tick=%0t",$time);end
  else if(mask!==previous)begin
   if($isunknown(mask))$fatal(1,"BROKER_UNKNOWN_LEASE");
   $display("%s path=%m tick=%0t mask=%04h",($root.tri_oracle_shared_attention_projection_tb.qkv_phase ? string'("QKV_BROKER_LEASE") : string'("BROKER_LEASE")),$time,mask);previous=mask;
  end
 end
 always @(posedge clk)if(rst_n && !$root.tri_oracle_shared_attention_projection_tb.ff_phase && (write || release_valid))
  $display("%s path=%m tick=%0t address=%0d write=%0d release=%0d data=%0256h",($root.tri_oracle_shared_attention_projection_tb.qkv_phase ? string'("QKV_BROKER_SLOT_ACCESS") : string'("BROKER_SLOT_ACCESS")),$time,address,write,release_valid,data);
endmodule
bind tri_oracle_sram_memory_compute tri_oracle_broker_slot_probe broker_slot_witness(
 .clk,.rst_n,.mask(context_owned),.write(context_write),.release_valid(context_release),
 .address(load_addr),.data(output_write_data));
