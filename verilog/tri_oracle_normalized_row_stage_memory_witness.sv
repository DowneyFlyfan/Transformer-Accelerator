`timescale 1ns/1ps
module normalized_row_stage_ram_witness #(
  parameter int WORDS = 0,
  parameter int WIDTH = 0
);
  string instance_path;
  initial begin
    instance_path = $sformatf("%m");
    if (WORDS != 512 || WIDTH != 64) $fatal(1, "ROW_STAGE_VENDOR_GEOMETRY");
    case (instance_path)
      "tri_oracle_normalized_row_stage_green_tb.memory.lower_metadata.vendor_witness":
        $root.tri_oracle_normalized_row_stage_green_tb.vendor_cells_seen[0] = 1;
      "tri_oracle_normalized_row_stage_green_tb.memory.upper_metadata.vendor_witness":
        $root.tri_oracle_normalized_row_stage_green_tb.vendor_cells_seen[1] = 1;
      "tri_oracle_normalized_row_stage_green_tb.contract_controls.memory.lower_metadata.vendor_witness":
        $root.tri_oracle_normalized_row_stage_green_tb.vendor_cells_seen[2] = 1;
      "tri_oracle_normalized_row_stage_green_tb.contract_controls.memory.upper_metadata.vendor_witness":
        $root.tri_oracle_normalized_row_stage_green_tb.vendor_cells_seen[3] = 1;
      default: $fatal(1, "ROW_STAGE_UNEXPECTED_VENDOR_INSTANCE");
    endcase
    $root.tri_oracle_normalized_row_stage_green_tb.vendor_cell_count++;
    $display("ROW_STAGE_VENDOR_CELL words=%0d width=%0d path=%m", WORDS, WIDTH);
  end
endmodule
bind TS5N28HPCPSVTA512X64M4F normalized_row_stage_ram_witness #(
  .WORDS(numWord), .WIDTH(numBit)
) vendor_witness();
