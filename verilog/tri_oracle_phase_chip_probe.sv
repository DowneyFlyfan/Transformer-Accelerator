`timescale 1ns/1ps
module tri_oracle_phase_chip_probe (
  input logic clk, memory_clk, rst_n, error,
  input logic scalar_valid,
  input logic [1:0] load_valid, load_ready, pending, retired,
  input logic [1:0][4:0] staged_core,
  input logic [4:0][63:0] phase_ce_n,
  input logic [4:0] phase_we_n
);
  int scalar_beats = 0, packed_beats = 0, committed_beats = 0;
  int reads = 0, writes = 0, simultaneous_writes = 0;
  bit [4:0] read_clusters, write_clusters;
  always @(posedge clk) if (rst_n) begin
    if (error || pending !== retired || (|(load_valid & ~load_ready)))
      $fatal(1, "PHASE_CHIP_INGRESS_SEQUENCE ready=%b pending=%b retired=%b", load_ready, pending, retired);
    if (scalar_valid)
      scalar_beats += $countones(load_valid);
    else
      packed_beats += $countones(load_valid);
    committed_beats += $countones(retired);
  end

  always @(posedge memory_clk) if (rst_n) begin
    int slot_writes;
    slot_writes = 0;
    for (int cluster = 0; cluster < 5; cluster++) begin
      if (phase_ce_n[cluster] != '1) begin
        if (phase_we_n[cluster]) begin
          if (!clk) $fatal(1, "PHASE_CHIP_WRONG_READ_PHASE cluster=%0d", cluster);
          reads++;
          read_clusters[cluster] = 1;
        end else begin
          if (clk || !(pending[0] && staged_core[0][4:2]==3'(cluster)
                       || pending[1] && staged_core[1][4:2]==3'(cluster)))
            $fatal(1, "PHASE_CHIP_WRONG_WRITE_PHASE cluster=%0d", cluster);
          writes++;
          slot_writes++;
          write_clusters[cluster] = 1;
        end
      end
    end
    if (slot_writes == 2) simultaneous_writes++;
  end

  final $display("PHASE_CHIP_PASS scalar=%0d packed=%0d commits=%0d writes=%0d reads=%0d double=%0d read_clusters=%0d write_clusters=%0d",
      scalar_beats, packed_beats, committed_beats, writes, reads, simultaneous_writes,
      $countones(read_clusters), $countones(write_clusters));
endmodule

bind tri_oracle_phase_weight_ingress tri_oracle_phase_chip_probe phase_probe (.*);
