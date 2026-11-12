#!/usr/bin/env bash
# Run inside cadence-ddi from the project directory.
set -euo pipefail
mkdir -p .cache
build=$(mktemp -d "$PWD/.cache/tri_oracle_simulation.XXXXXX")
trap 'rm -rf -- "$build"' EXIT

simulate() {
    local top=$1
    shift
    /opt/cadence/bin/xrun -64bit -sv -clean -top "$top" -timescale 1ns/1ps \
        -xmlibdirname "$build/xcelium.d" -l "$build/xrun.log" \
        -history_file "$build/xrun.history" "$@"
}

for unit in token_merger head_predictor snzv_predictor strip_predictor channel_compactor \
    proportional_normalizer pe_array word_bank silu_gate chip_dispatch; do
    simulate "tri_oracle_${unit}_tb" \
        "verilog/tri_oracle_${unit}.sv" "verilog/tri_oracle_${unit}_tb.sv"
    verilator --lint-only -Wall --top-module "tri_oracle_${unit}" \
        "verilog/tri_oracle_${unit}.sv"
done
simulate tri_oracle_word_bank_tb -defparam tri_oracle_word_bank_tb.DATA_W=32 \
    -defparam tri_oracle_word_bank_tb.ADDR_W=4 \
    verilog/tri_oracle_word_bank.sv verilog/tri_oracle_word_bank_tb.sv
simulate tri_oracle_predictor_paper_tb \
    verilog/tri_oracle_strip_predictor.sv verilog/tri_oracle_snzv_predictor.sv \
    verilog/tri_oracle_predictor_paper_tb.sv
simulate tri_oracle_strip_predictor_width_tb \
    verilog/tri_oracle_strip_predictor.sv verilog/tri_oracle_snzv_predictor.sv verilog/tri_oracle_strip_predictor_width_tb.sv
verilator --lint-only -Wall --top-module tri_oracle_strip_predictor \
    -GACT_W=32 verilog/tri_oracle_strip_predictor.sv
simulate tri_oracle_pe_array_tb \
    -defparam tri_oracle_pe_array_tb.NO_STALL=1 \
    verilog/tri_oracle_pe_array.sv verilog/tri_oracle_pe_array_tb.sv
simulate tri_oracle_memory_compute_tb \
    verilog/tri_oracle_pe_array.sv verilog/tri_oracle_word_bank.sv verilog/tri_oracle_memory_compute.sv \
    verilog/tri_oracle_memory_compute_tb.sv
verilator --lint-only -Wall --top-module tri_oracle_memory_compute \
    verilog/tri_oracle_pe_array.sv verilog/tri_oracle_word_bank.sv verilog/tri_oracle_memory_compute.sv
simulate tri_oracle_partial_weight_tb \
    verilog/tri_oracle_pe_array.sv verilog/tri_oracle_word_bank.sv verilog/tri_oracle_memory_compute.sv \
    verilog/tri_oracle_partial_weight_tb.sv
dispatch_sources=(verilog/tri_oracle_strip_predictor.sv verilog/tri_oracle_channel_compactor.sv \
    verilog/tri_oracle_predicted_dispatch.sv)
simulate tri_oracle_predicted_dispatch_tb \
    "${dispatch_sources[@]}" verilog/tri_oracle_pe_array.sv \
    verilog/tri_oracle_word_bank.sv verilog/tri_oracle_memory_compute.sv verilog/tri_oracle_predicted_dispatch_tb.sv
verilator --lint-only -Wall --top-module tri_oracle_predicted_dispatch "${dispatch_sources[@]}"
simulate tri_oracle_sparse_weight_dma_tb \
    verilog/tri_oracle_pe_array.sv verilog/tri_oracle_word_bank.sv verilog/tri_oracle_memory_compute.sv \
    verilog/tri_oracle_sparse_weight_dma.sv verilog/tri_oracle_sparse_weight_dma_tb.sv
verilator --lint-only -Wall --top-module tri_oracle_sparse_weight_dma verilog/tri_oracle_sparse_weight_dma.sv
executor_sources=(verilog/tri_oracle_sparse_weight_dma.sv verilog/tri_oracle_tile_executor.sv)
simulate tri_oracle_tile_executor_tb \
    "${executor_sources[@]}" verilog/tri_oracle_pe_array.sv \
    verilog/tri_oracle_word_bank.sv verilog/tri_oracle_memory_compute.sv verilog/tri_oracle_tile_executor_tb.sv
verilator --lint-only -Wall --top-module tri_oracle_tile_executor "${executor_sources[@]}"
predicted_core_sources=(verilog/tri_oracle_silu_gate.sv verilog/tri_oracle_gated_executor.sv \
    verilog/tri_oracle_predicted_core.sv "${dispatch_sources[@]}" \
    "${executor_sources[@]}" verilog/tri_oracle_pe_array.sv verilog/tri_oracle_word_bank.sv \
    verilog/tri_oracle_memory_compute.sv)
simulate tri_oracle_predicted_core_tb \
    "${predicted_core_sources[@]}" verilog/tri_oracle_predicted_core_tb.sv
verilator --lint-only -Wall --top-module tri_oracle_predicted_core "${predicted_core_sources[@]}"
simulate tri_oracle_predicted_core_tb -defparam tri_oracle_predicted_core_tb.GATED=1 \
    "${predicted_core_sources[@]}" verilog/tri_oracle_predicted_core_tb.sv
verilator --lint-only -Wall --top-module tri_oracle_predicted_core -GGATED=1 "${predicted_core_sources[@]}"
simulate tri_oracle_gated_executor_tb \
    verilog/tri_oracle_gated_executor.sv verilog/tri_oracle_silu_gate.sv \
    "${executor_sources[@]}" verilog/tri_oracle_pe_array.sv verilog/tri_oracle_word_bank.sv \
    verilog/tri_oracle_memory_compute.sv verilog/tri_oracle_gated_executor_tb.sv
verilator --lint-only -Wall --top-module tri_oracle_gated_executor \
    verilog/tri_oracle_gated_executor.sv verilog/tri_oracle_silu_gate.sv "${executor_sources[@]}"
simulate tri_oracle_down_executor_tb \
    verilog/tri_oracle_down_executor.sv verilog/tri_oracle_down_executor_tb.sv \
    verilog/tri_oracle_pe_array.sv verilog/tri_oracle_word_bank.sv verilog/tri_oracle_memory_compute.sv
verilator --lint-only -Wall --top-module tri_oracle_down_executor verilog/tri_oracle_down_executor.sv
feedforward_sources=(verilog/tri_oracle_feedforward_core.sv verilog/tri_oracle_down_executor.sv \
    "${predicted_core_sources[@]}")
simulate tri_oracle_feedforward_core_tb \
    "${feedforward_sources[@]}" verilog/tri_oracle_feedforward_core_tb.sv
verilator --lint-only -Wall --top-module tri_oracle_feedforward_core "${feedforward_sources[@]}"
fabric_sources=(verilog/tri_oracle_pe_array.sv verilog/tri_oracle_word_bank.sv verilog/tri_oracle_memory_compute.sv \
    verilog/tri_oracle_compute_cluster.sv verilog/tri_oracle_compute_fabric.sv)
simulate tri_oracle_compute_fabric_tb \
    "${fabric_sources[@]}" verilog/tri_oracle_compute_fabric_tb.sv
simulate tri_oracle_token_merger_random_tb \
    verilog/tri_oracle_token_merger.sv verilog/tri_oracle_token_merger_random_tb.sv
verilator --lint-only -Wall --top-module tri_oracle_compute_fabric "${fabric_sources[@]}"
