`timescale 1ns/1ps
// Selected as an additional simulation top only for the elaboration census.
// The complete frame uses the identical bundle without selecting this top.
module tri_oracle_full_memory_census_stop;
 initial begin
  #4;
  if($root.tri_oracle_shared_attention_projection_tb.clk!==1'b0 ||
     $root.tri_oracle_shared_attention_projection_tb.rst_n!==1'b0)
   $fatal(1,"FULL_MEMORY_CENSUS_CLOCK_OR_RESET_CHANGED");
  $display("FULL_MEMORY_CENSUS_ELABORATION_PASS clocks=0");
  $finish;
 end
endmodule
