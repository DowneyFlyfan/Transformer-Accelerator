`timescale 1ns/1ps
module tri_oracle_weight_tile_prefetch_probe (
  input logic clk, rst_n, prefetch_inflight, sequence_done_valid,
  input logic wide_req_valid, wide_req_ready, aux_req_valid, aux_req_ready,
  input logic [1:0] wide_load_valid,
  input logic backend_cmd_valid, backend_cmd_ready
);
  int request_overlaps, load_overlaps, concurrent_loads;
  always @(posedge clk) if (rst_n && prefetch_inflight && !sequence_done_valid) begin
    request_overlaps += int'(wide_req_valid && wide_req_ready) + int'(aux_req_valid && aux_req_ready);
    load_overlaps += $countones(wide_load_valid);
    if (backend_cmd_valid && backend_cmd_ready) concurrent_loads += $countones(wide_load_valid);
  end
  final $display("CHIP_WEIGHT_PREFETCH requests=%0d loads=%0d alongside_reads=%0d",
                 request_overlaps, load_overlaps, concurrent_loads);
endmodule

bind tri_oracle_batched_tensor390 tri_oracle_weight_tile_prefetch_probe weight_prefetch_probe (.*);
