#!/usr/bin/env bash
# Run inside cadence-ddi from the project directory.
set -euo pipefail
mkdir -p .cache
binary=.cache/tri_oracle_simulation.vvp
trap 'rm -f "$binary"' EXIT
for unit in token_merger head_predictor snzv_predictor strip_predictor channel_compactor proportional_normalizer pe_array word_bank silu_gate; do
    iverilog -g2012 -s "tri_oracle_${unit}_tb" -o "$binary" \
        "verilog/tri_oracle_${unit}.sv" "verilog/tri_oracle_${unit}_tb.sv"
    vvp "$binary"
    verilator --lint-only -Wall --top-module "tri_oracle_${unit}" \
        "verilog/tri_oracle_${unit}.sv"
done
iverilog -g2012 -s tri_oracle_word_bank_tb -P tri_oracle_word_bank_tb.DATA_W=32 \
    -P tri_oracle_word_bank_tb.ADDR_W=4 -o "$binary" \
    verilog/tri_oracle_word_bank.sv verilog/tri_oracle_word_bank_tb.sv
vvp "$binary"
iverilog -g2012 -s tri_oracle_predictor_paper_tb -o "$binary" \
    verilog/tri_oracle_strip_predictor.sv verilog/tri_oracle_snzv_predictor.sv \
    verilog/tri_oracle_predictor_paper_tb.sv
vvp "$binary"
iverilog -g2012 -s tri_oracle_strip_predictor_width_tb -o "$binary" \
    verilog/tri_oracle_strip_predictor.sv verilog/tri_oracle_snzv_predictor.sv verilog/tri_oracle_strip_predictor_width_tb.sv
vvp "$binary"
verilator --lint-only -Wall --top-module tri_oracle_strip_predictor \
    -GACT_W=32 verilog/tri_oracle_strip_predictor.sv
iverilog -g2012 -s tri_oracle_pe_array_tb \
    -P tri_oracle_pe_array_tb.NO_STALL=1 -o "$binary" \
    verilog/tri_oracle_pe_array.sv verilog/tri_oracle_pe_array_tb.sv
vvp "$binary"
iverilog -g2012 -s tri_oracle_memory_compute_tb -o "$binary" \
    verilog/tri_oracle_pe_array.sv verilog/tri_oracle_word_bank.sv verilog/tri_oracle_memory_compute.sv \
    verilog/tri_oracle_memory_compute_tb.sv
vvp "$binary"
verilator --lint-only -Wall --top-module tri_oracle_memory_compute \
    verilog/tri_oracle_pe_array.sv verilog/tri_oracle_word_bank.sv verilog/tri_oracle_memory_compute.sv
iverilog -g2012 -s tri_oracle_partial_weight_tb -o "$binary" \
    verilog/tri_oracle_pe_array.sv verilog/tri_oracle_word_bank.sv verilog/tri_oracle_memory_compute.sv \
    verilog/tri_oracle_partial_weight_tb.sv
vvp "$binary"
dispatch_sources=(verilog/tri_oracle_strip_predictor.sv verilog/tri_oracle_channel_compactor.sv \
    verilog/tri_oracle_predicted_dispatch.sv)
iverilog -g2012 -s tri_oracle_predicted_dispatch_tb -o "$binary" \
    "${dispatch_sources[@]}" verilog/tri_oracle_pe_array.sv \
    verilog/tri_oracle_word_bank.sv verilog/tri_oracle_memory_compute.sv verilog/tri_oracle_predicted_dispatch_tb.sv
vvp "$binary"
verilator --lint-only -Wall --top-module tri_oracle_predicted_dispatch "${dispatch_sources[@]}"
iverilog -g2012 -s tri_oracle_sparse_weight_dma_tb -o "$binary" \
    verilog/tri_oracle_pe_array.sv verilog/tri_oracle_word_bank.sv verilog/tri_oracle_memory_compute.sv \
    verilog/tri_oracle_sparse_weight_dma.sv verilog/tri_oracle_sparse_weight_dma_tb.sv
vvp "$binary"
verilator --lint-only -Wall --top-module tri_oracle_sparse_weight_dma verilog/tri_oracle_sparse_weight_dma.sv
executor_sources=(verilog/tri_oracle_sparse_weight_dma.sv verilog/tri_oracle_tile_executor.sv)
iverilog -g2012 -s tri_oracle_tile_executor_tb -o "$binary" \
    "${executor_sources[@]}" verilog/tri_oracle_pe_array.sv \
    verilog/tri_oracle_word_bank.sv verilog/tri_oracle_memory_compute.sv verilog/tri_oracle_tile_executor_tb.sv
vvp "$binary"
verilator --lint-only -Wall --top-module tri_oracle_tile_executor "${executor_sources[@]}"
predicted_core_sources=(verilog/tri_oracle_silu_gate.sv verilog/tri_oracle_gated_executor.sv \
    verilog/tri_oracle_predicted_core.sv "${dispatch_sources[@]}" \
    "${executor_sources[@]}" verilog/tri_oracle_pe_array.sv verilog/tri_oracle_word_bank.sv \
    verilog/tri_oracle_memory_compute.sv)
iverilog -g2012 -s tri_oracle_predicted_core_tb -o "$binary" \
    "${predicted_core_sources[@]}" verilog/tri_oracle_predicted_core_tb.sv
vvp "$binary"
verilator --lint-only -Wall --top-module tri_oracle_predicted_core "${predicted_core_sources[@]}"
iverilog -g2012 -s tri_oracle_predicted_core_tb -P tri_oracle_predicted_core_tb.GATED=1 -o "$binary" \
    "${predicted_core_sources[@]}" verilog/tri_oracle_predicted_core_tb.sv
vvp "$binary"
verilator --lint-only -Wall --top-module tri_oracle_predicted_core -GGATED=1 "${predicted_core_sources[@]}"
iverilog -g2012 -s tri_oracle_gated_executor_tb -o "$binary" \
    verilog/tri_oracle_gated_executor.sv verilog/tri_oracle_silu_gate.sv \
    "${executor_sources[@]}" verilog/tri_oracle_pe_array.sv verilog/tri_oracle_word_bank.sv \
    verilog/tri_oracle_memory_compute.sv verilog/tri_oracle_gated_executor_tb.sv
vvp "$binary"
verilator --lint-only -Wall --top-module tri_oracle_gated_executor \
    verilog/tri_oracle_gated_executor.sv verilog/tri_oracle_silu_gate.sv "${executor_sources[@]}"
iverilog -g2012 -s tri_oracle_down_executor_tb -o "$binary" \
    verilog/tri_oracle_down_executor.sv verilog/tri_oracle_down_executor_tb.sv \
    verilog/tri_oracle_pe_array.sv verilog/tri_oracle_word_bank.sv verilog/tri_oracle_memory_compute.sv
vvp "$binary"
verilator --lint-only -Wall --top-module tri_oracle_down_executor verilog/tri_oracle_down_executor.sv
feedforward_sources=(verilog/tri_oracle_feedforward_core.sv verilog/tri_oracle_down_executor.sv \
    "${predicted_core_sources[@]}")
iverilog -g2012 -s tri_oracle_feedforward_core_tb -o "$binary" \
    "${feedforward_sources[@]}" verilog/tri_oracle_feedforward_core_tb.sv
vvp "$binary"
verilator --lint-only -Wall --top-module tri_oracle_feedforward_core "${feedforward_sources[@]}"
fabric_sources=(verilog/tri_oracle_pe_array.sv verilog/tri_oracle_word_bank.sv verilog/tri_oracle_memory_compute.sv \
    verilog/tri_oracle_compute_cluster.sv verilog/tri_oracle_compute_fabric.sv)
iverilog -g2012 -s tri_oracle_compute_fabric_tb -o "$binary" \
    "${fabric_sources[@]}" verilog/tri_oracle_compute_fabric_tb.sv
vvp "$binary"
verilator --lint-only -Wall --top-module tri_oracle_compute_fabric "${fabric_sources[@]}"
iverilog -g2012 -s tri_oracle_token_merger_random_tb -o "$binary" \
    verilog/tri_oracle_token_merger.sv verilog/tri_oracle_token_merger_random_tb.sv
vvp "$binary"
