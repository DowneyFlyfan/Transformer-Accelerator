`timescale 1ns/1ps
// Passive test-only observer. Count every compiled memory family in the closed
// source bundle using its actual elaborated word/bit parameters. This excludes
// ordinary logic registers and is not physical-candidate memory qualification.
module tri_oracle_complete_memory_inventory;
  int unsigned count[6]='{default:0};
  longint unsigned logical_bits[6]='{default:0};
  longint unsigned total_bits=0;
  int unsigned total_count=0;
  initial begin
    #2;
    for(int kind=0;kind<6;kind++)begin
      total_bits+=logical_bits[kind];total_count+=count[kind];
      $display("COMPLETE_MEMORY_TYPE kind=%0d macros=%0d logical_bits=%0d",kind,count[kind],logical_bits[kind]);
    end
    if(total_count<602 || total_bits%8!=0)$fatal(1,"COMPLETE_MEMORY_INVALID_INVENTORY");
    $display("COMPLETE_MEMORY_TOTAL types=6 macros=%0d logical_bits=%0d logical_bytes=%0d",total_count,total_bits,total_bits/8);
  end
endmodule

module tri_oracle_complete_memory_count #(
  parameter int KIND=0,WORDS=0,WIDTH=0
) ();
  initial begin
    if(KIND<0 || KIND>=6 || WORDS<=0 || WIDTH<=0)$fatal(1,"COMPLETE_MEMORY_INVALID_BINDING");
    $root.tri_oracle_complete_memory_inventory.count[KIND]++;
    $root.tri_oracle_complete_memory_inventory.logical_bits[KIND]+=64'(WORDS)*64'(WIDTH);
    $display("COMPLETE_MEMORY_INSTANCE kind=%0d words=%0d width=%0d path=%m",KIND,WORDS,WIDTH);
  end
endmodule

bind TS5N28HPCPSVTA16X80M2FW tri_oracle_complete_memory_count
  #(.KIND(0),.WORDS(numWord),.WIDTH(numBit)) count_complete_sram ();
bind TS5N28HPCPSVTA24X128M2FW tri_oracle_complete_memory_count
  #(.KIND(1),.WORDS(numWord),.WIDTH(numBit)) count_complete_sram ();
bind TS5N28HPCPSVTA32X128M2FW tri_oracle_complete_memory_count
  #(.KIND(2),.WORDS(numWord),.WIDTH(numBit)) count_complete_sram ();
bind TS5N28HPCPSVTA512X64M4F tri_oracle_complete_memory_count
  #(.KIND(3),.WORDS(numWord),.WIDTH(numBit)) count_complete_sram ();
bind TS5N28HPCPSVTA8X80M2FW tri_oracle_complete_memory_count
  #(.KIND(4),.WORDS(numWord),.WIDTH(numBit)) count_complete_sram ();
bind TS6N28HPCPSVTA16X128M2F tri_oracle_complete_memory_count
  #(.KIND(5),.WORDS(W),.WIDTH(N)) count_complete_sram ();
