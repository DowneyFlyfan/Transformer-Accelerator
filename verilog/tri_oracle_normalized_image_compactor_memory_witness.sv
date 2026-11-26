`timescale 1ns/1ps
// Exact genuine model instance census; no behavioral memory replacement.
module compactor_vendor_memory_witness #(parameter int WORDS=0, WIDTH=0);
  string instance_path;
  initial begin
    instance_path=$sformatf("%m");
    case(instance_path)
      "tri_oracle_normalized_image_compactor_tb.merge_fabric.aggregator[0].unit.similarity.shard.compiled.compact.slices[0].vendor_witness": begin
        if(WORDS!=24 || WIDTH!=128)$fatal(1,"COMPACTOR_VENDOR_GEOMETRY");
        $root.tri_oracle_normalized_image_compactor_tb.vendor_cells_seen[0]=1;
      end
      "tri_oracle_normalized_image_compactor_tb.merge_fabric.aggregator[0].unit.similarity.shard.compiled.compact.slices[1].vendor_witness": begin
        if(WORDS!=24 || WIDTH!=128)$fatal(1,"COMPACTOR_VENDOR_GEOMETRY");
        $root.tri_oracle_normalized_image_compactor_tb.vendor_cells_seen[1]=1;
      end
      "tri_oracle_normalized_image_compactor_tb.merge_fabric.aggregator[0].unit.similarity.shard.compiled.compact.slices[2].vendor_witness": begin
        if(WORDS!=24 || WIDTH!=128)$fatal(1,"COMPACTOR_VENDOR_GEOMETRY");
        $root.tri_oracle_normalized_image_compactor_tb.vendor_cells_seen[2]=1;
      end
      "tri_oracle_normalized_image_compactor_tb.merge_fabric.aggregator[0].unit.similarity.shard.compiled.compact.slices[3].vendor_witness": begin
        if(WORDS!=24 || WIDTH!=128)$fatal(1,"COMPACTOR_VENDOR_GEOMETRY");
        $root.tri_oracle_normalized_image_compactor_tb.vendor_cells_seen[3]=1;
      end
      "tri_oracle_normalized_image_compactor_tb.merge_fabric.aggregator[1].unit.similarity.shard.compiled.compact.slices[0].vendor_witness": begin
        if(WORDS!=24 || WIDTH!=128)$fatal(1,"COMPACTOR_VENDOR_GEOMETRY");
        $root.tri_oracle_normalized_image_compactor_tb.vendor_cells_seen[4]=1;
      end
      "tri_oracle_normalized_image_compactor_tb.merge_fabric.aggregator[1].unit.similarity.shard.compiled.compact.slices[1].vendor_witness": begin
        if(WORDS!=24 || WIDTH!=128)$fatal(1,"COMPACTOR_VENDOR_GEOMETRY");
        $root.tri_oracle_normalized_image_compactor_tb.vendor_cells_seen[5]=1;
      end
      "tri_oracle_normalized_image_compactor_tb.merge_fabric.aggregator[1].unit.similarity.shard.compiled.compact.slices[2].vendor_witness": begin
        if(WORDS!=24 || WIDTH!=128)$fatal(1,"COMPACTOR_VENDOR_GEOMETRY");
        $root.tri_oracle_normalized_image_compactor_tb.vendor_cells_seen[6]=1;
      end
      "tri_oracle_normalized_image_compactor_tb.merge_fabric.aggregator[2].unit.similarity.shard.compiled.compact.slices[0].vendor_witness": begin
        if(WORDS!=24 || WIDTH!=128)$fatal(1,"COMPACTOR_VENDOR_GEOMETRY");
        $root.tri_oracle_normalized_image_compactor_tb.vendor_cells_seen[7]=1;
      end
      "tri_oracle_normalized_image_compactor_tb.merge_fabric.aggregator[2].unit.similarity.shard.compiled.compact.slices[1].vendor_witness": begin
        if(WORDS!=24 || WIDTH!=128)$fatal(1,"COMPACTOR_VENDOR_GEOMETRY");
        $root.tri_oracle_normalized_image_compactor_tb.vendor_cells_seen[8]=1;
      end
      "tri_oracle_normalized_image_compactor_tb.merge_fabric.aggregator[2].unit.similarity.shard.compiled.compact.slices[2].vendor_witness": begin
        if(WORDS!=24 || WIDTH!=128)$fatal(1,"COMPACTOR_VENDOR_GEOMETRY");
        $root.tri_oracle_normalized_image_compactor_tb.vendor_cells_seen[9]=1;
      end
      "tri_oracle_normalized_image_compactor_tb.merge_fabric.aggregator[3].unit.similarity.shard.compiled.compact.slices[0].vendor_witness": begin
        if(WORDS!=24 || WIDTH!=128)$fatal(1,"COMPACTOR_VENDOR_GEOMETRY");
        $root.tri_oracle_normalized_image_compactor_tb.vendor_cells_seen[10]=1;
      end
      "tri_oracle_normalized_image_compactor_tb.merge_fabric.aggregator[3].unit.similarity.shard.compiled.compact.slices[1].vendor_witness": begin
        if(WORDS!=24 || WIDTH!=128)$fatal(1,"COMPACTOR_VENDOR_GEOMETRY");
        $root.tri_oracle_normalized_image_compactor_tb.vendor_cells_seen[11]=1;
      end
      "tri_oracle_normalized_image_compactor_tb.merge_fabric.aggregator[3].unit.similarity.shard.compiled.compact.slices[2].vendor_witness": begin
        if(WORDS!=24 || WIDTH!=128)$fatal(1,"COMPACTOR_VENDOR_GEOMETRY");
        $root.tri_oracle_normalized_image_compactor_tb.vendor_cells_seen[12]=1;
      end
      "tri_oracle_normalized_image_compactor_tb.merge_fabric.aggregator[4].unit.similarity.shard.compiled.compact.slices[0].vendor_witness": begin
        if(WORDS!=24 || WIDTH!=128)$fatal(1,"COMPACTOR_VENDOR_GEOMETRY");
        $root.tri_oracle_normalized_image_compactor_tb.vendor_cells_seen[13]=1;
      end
      "tri_oracle_normalized_image_compactor_tb.merge_fabric.aggregator[4].unit.similarity.shard.compiled.compact.slices[1].vendor_witness": begin
        if(WORDS!=24 || WIDTH!=128)$fatal(1,"COMPACTOR_VENDOR_GEOMETRY");
        $root.tri_oracle_normalized_image_compactor_tb.vendor_cells_seen[14]=1;
      end
      "tri_oracle_normalized_image_compactor_tb.merge_fabric.aggregator[4].unit.similarity.shard.compiled.compact.slices[2].vendor_witness": begin
        if(WORDS!=24 || WIDTH!=128)$fatal(1,"COMPACTOR_VENDOR_GEOMETRY");
        $root.tri_oracle_normalized_image_compactor_tb.vendor_cells_seen[15]=1;
      end
      "tri_oracle_normalized_image_compactor_tb.merge_fabric.aggregator[0].unit.sizes.local_sizes.table_bank.compiled.full.entries.vendor_witness": begin
        if(WORDS!=16 || WIDTH!=80)$fatal(1,"COMPACTOR_VENDOR_GEOMETRY");
        $root.tri_oracle_normalized_image_compactor_tb.vendor_cells_seen[16]=1;
      end
      "tri_oracle_normalized_image_compactor_tb.merge_fabric.aggregator[1].unit.sizes.local_sizes.table_bank.compiled.full.entries.vendor_witness": begin
        if(WORDS!=16 || WIDTH!=80)$fatal(1,"COMPACTOR_VENDOR_GEOMETRY");
        $root.tri_oracle_normalized_image_compactor_tb.vendor_cells_seen[17]=1;
      end
      "tri_oracle_normalized_image_compactor_tb.merge_fabric.aggregator[2].unit.sizes.local_sizes.table_bank.compiled.full.entries.vendor_witness": begin
        if(WORDS!=16 || WIDTH!=80)$fatal(1,"COMPACTOR_VENDOR_GEOMETRY");
        $root.tri_oracle_normalized_image_compactor_tb.vendor_cells_seen[18]=1;
      end
      "tri_oracle_normalized_image_compactor_tb.merge_fabric.aggregator[3].unit.sizes.local_sizes.table_bank.compiled.full.entries.vendor_witness": begin
        if(WORDS!=16 || WIDTH!=80)$fatal(1,"COMPACTOR_VENDOR_GEOMETRY");
        $root.tri_oracle_normalized_image_compactor_tb.vendor_cells_seen[19]=1;
      end
      "tri_oracle_normalized_image_compactor_tb.merge_fabric.aggregator[4].unit.sizes.local_sizes.table_bank.compiled.tail.entries.vendor_witness": begin
        if(WORDS!=8 || WIDTH!=80)$fatal(1,"COMPACTOR_VENDOR_GEOMETRY");
        $root.tri_oracle_normalized_image_compactor_tb.vendor_cells_seen[20]=1;
      end
      "tri_oracle_normalized_image_compactor_tb.memory.lower_metadata.vendor_witness": begin
        if(WORDS!=512 || WIDTH!=64)$fatal(1,"COMPACTOR_VENDOR_GEOMETRY");
        $root.tri_oracle_normalized_image_compactor_tb.vendor_cells_seen[21]=1;
      end
      "tri_oracle_normalized_image_compactor_tb.memory.upper_metadata.vendor_witness": begin
        if(WORDS!=512 || WIDTH!=64)$fatal(1,"COMPACTOR_VENDOR_GEOMETRY");
        $root.tri_oracle_normalized_image_compactor_tb.vendor_cells_seen[22]=1;
      end
      default:$fatal(1,"COMPACTOR_UNEXPECTED_VENDOR_INSTANCE path=%s",instance_path);
    endcase
    $root.tri_oracle_normalized_image_compactor_tb.vendor_cell_count++;
    $display("COMPACTOR_VENDOR_CELL words=%0d width=%0d path=%m",WORDS,WIDTH);
  end
endmodule
bind TS5N28HPCPSVTA24X128M2FW compactor_vendor_memory_witness #(.WORDS(numWord),.WIDTH(numBit)) vendor_witness();
bind TS5N28HPCPSVTA16X80M2FW compactor_vendor_memory_witness #(.WORDS(numWord),.WIDTH(numBit)) vendor_witness();
bind TS5N28HPCPSVTA8X80M2FW compactor_vendor_memory_witness #(.WORDS(numWord),.WIDTH(numBit)) vendor_witness();
bind TS5N28HPCPSVTA512X64M4F compactor_vendor_memory_witness #(.WORDS(numWord),.WIDTH(numBit)) vendor_witness();
