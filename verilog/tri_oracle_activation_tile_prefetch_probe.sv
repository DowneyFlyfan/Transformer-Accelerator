`timescale 1ns/1ps
module tri_oracle_activation_tile_prefetch_probe (
  input logic clk, rst_n, prefetch_inflight, load_valid, activation_bank,
  input logic [1:0] load_kind,
  input logic [9:0] load_addr, backend_cmd_activation,
  input logic backend_cmd_valid, backend_cmd_ready,
  input logic projection_done
);
  bit previous_prefetch;
  int windows, writes, parallel_writes, retired_windows;
  always @(posedge clk) if (rst_n) begin
    if (prefetch_inflight && !previous_prefetch) windows++;
    if (prefetch_inflight && projection_done) retired_windows++;
    if (prefetch_inflight && load_valid) begin
      if (load_kind != 1 || load_addr[9] !== activation_bank)
        $fatal(1, "CHIP_PREFETCH_INVALID_LOAD");
      writes++;
      if (backend_cmd_valid && backend_cmd_ready) begin
        if (load_addr[9] === backend_cmd_activation[9])
          $fatal(1, "CHIP_PREFETCH_SAME_BANK");
        parallel_writes++;
      end
    end
    previous_prefetch = prefetch_inflight;
  end
  final $display("CHIP_ACTIVATION_PREFETCH windows=%0d writes=%0d parallel=%0d retired=%0d",
                 windows, writes, parallel_writes, retired_windows);
endmodule

bind tri_oracle_batched_tensor390 tri_oracle_activation_tile_prefetch_probe activation_prefetch_probe (
    .clk, .rst_n, .prefetch_inflight, .load_valid, .activation_bank, .load_kind, .load_addr,
    .backend_cmd_activation, .backend_cmd_valid, .backend_cmd_ready,
    .projection_done(sequence_done_valid && state==WAIT_PREFETCH)
);
