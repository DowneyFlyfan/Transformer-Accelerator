#!/usr/bin/env bash
# Functional simulation of the mapped or routed controller; no delay annotation.
set -euo pipefail
netlist=${TRI_ORACLE_NETLIST:-.cache/physical/synthesis/tri_oracle_sparse_weight_dma/netlist.v}
models=.cache/physical/library/tcbn28hpcplusbwp12t40p140.v
test -s "$netlist"
test -s "$models"
binary=.cache/physical/synthesis/tri_oracle_sparse_weight_dma/gate_simulation.vvp
trap 'rm -f "$binary"' EXIT
iverilog -g2012 -s tri_oracle_sparse_weight_dma_tb -o "$binary" \
    "$models" "$netlist" verilog/tri_oracle_pe_array.sv \
    verilog/tri_oracle_word_bank.sv verilog/tri_oracle_memory_compute.sv verilog/tri_oracle_sparse_weight_dma_tb.sv
vvp "$binary"
