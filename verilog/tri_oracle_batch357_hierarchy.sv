`timescale 1ns/1ps
module tri_oracle_batch357_hierarchy;
  int cores=0,clusters=0,weights_masks=0,activations=0,results=0;
  initial begin
    #1;
    if(cores!=20 || clusters!=5 || weights_masks!=360 || activations!=40 || results!=200)
      $fatal(1,"BATCH357_WRONG_NATIVE_HIERARCHY");
    $display("BATCH357_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=600");
  end
endmodule
module tri_oracle_batch357_count #(parameter int KIND=0) ();
  initial case(KIND)
    0:$root.tri_oracle_batch357_hierarchy.cores++;
    1:$root.tri_oracle_batch357_hierarchy.clusters++;
    2:$root.tri_oracle_batch357_hierarchy.weights_masks++;
    3:$root.tri_oracle_batch357_hierarchy.activations++;
    4:$root.tri_oracle_batch357_hierarchy.results++;
  endcase
endmodule
bind tri_oracle_sram_memory_compute tri_oracle_batch357_count #(.KIND(0)) count_core357 ();
bind tri_oracle_sram_compute_cluster tri_oracle_batch357_count #(.KIND(1)) count_cluster357 ();
bind TS5N28HPCPSVTA32X128M2FW tri_oracle_batch357_count #(.KIND(2)) count_weight357 ();
bind TS5N28HPCPSVTA512X64M4F tri_oracle_batch357_count #(.KIND(3)) count_activation357 ();
bind TS6N28HPCPSVTA16X128M2F tri_oracle_batch357_count #(.KIND(4)) count_result357 ();
