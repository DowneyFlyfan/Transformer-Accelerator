#!/usr/bin/env bash
# Run the twenty-core resident-operand simulation inside the Cadence container.
set -euo pipefail
mkdir -p .cache
build=$(mktemp -d "$PWD/.cache/tri_oracle_fabric_stream.XXXXXX")
trap 'rm -rf -- "$build"' EXIT
timeout --kill-after=5s 120 /opt/cadence/bin/xrun -64bit -sv -top tri_oracle_fabric_stream_tb \
    -xmlibdirname "$build/xcelium.d" -l "$build/xrun.log" -history_file "$build/xrun.history" \
    verilog/tri_oracle_fabric_stream_tb.sv verilog/tri_oracle_compute_fabric.sv \
    verilog/tri_oracle_compute_cluster.sv verilog/tri_oracle_memory_compute.sv \
    verilog/tri_oracle_word_bank.sv verilog/tri_oracle_pe_array.sv
