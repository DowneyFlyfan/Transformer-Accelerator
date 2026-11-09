#!/usr/bin/env bash
# Icarus behavioral simulation, with all20 real memory/compute cores instantiated.
set -euo pipefail
binary=.cache/tri_oracle_fabric_stream.vvp
trap 'rm -f "$binary"' EXIT
iverilog -g2012 -s tri_oracle_fabric_stream_tb -o "$binary" \
    verilog/tri_oracle_fabric_stream_tb.sv verilog/tri_oracle_compute_fabric.sv \
    verilog/tri_oracle_compute_cluster.sv verilog/tri_oracle_memory_compute.sv \
    verilog/tri_oracle_word_bank.sv verilog/tri_oracle_pe_array.sv
timeout 120 vvp "$binary"
