`timescale 1ns/1ps
module tri_oracle_distributed_metadata_cell_witness #(parameter int WORDS=0,WIDTH=0);
  string instance_path;
  initial begin
    instance_path=$sformatf("%m");
    if(WORDS!=512 || WIDTH!=64)$fatal(1,"SHARED_METADATA_VENDOR_GEOMETRY");
    if(instance_path=="tri_oracle_distributed_metadata_tb.collector.storage.lower_metadata.vendor_witness")begin
      if($root.tri_oracle_distributed_metadata_tb.lower_cell_seen)$fatal(1,"SHARED_METADATA_DUPLICATE_LOWER_CELL");
      $root.tri_oracle_distributed_metadata_tb.lower_cell_seen=1;
    end else if(instance_path=="tri_oracle_distributed_metadata_tb.collector.storage.upper_metadata.vendor_witness")begin
      if($root.tri_oracle_distributed_metadata_tb.upper_cell_seen)$fatal(1,"SHARED_METADATA_DUPLICATE_UPPER_CELL");
      $root.tri_oracle_distributed_metadata_tb.upper_cell_seen=1;
    end else $fatal(1,"SHARED_METADATA_UNEXPECTED_VENDOR_CELL path=%s",instance_path);
    $root.tri_oracle_distributed_metadata_tb.vendor_cell_count++;
    $display("SHARED_METADATA_VENDOR_CELL words=%0d width=%0d path=%m",WORDS,WIDTH);
  end
endmodule
bind TS5N28HPCPSVTA512X64M4F tri_oracle_distributed_metadata_cell_witness #(.WORDS(numWord),.WIDTH(numBit)) vendor_witness();
