#!/usr/bin/env bash
# Functional verification only. No extracted delays are annotated in this run.
set -euo pipefail
netlist=.cache/physical/pnr/tri_oracle_pe_array/routed_netlist.v
models=.cache/physical/library/tcbn28hpcplusbwp12t40p140.v
test -s "$netlist"
test -s "$models"
binary=.cache/physical/pnr/tri_oracle_pe_array/routed_gate_simulation.vvp
trap 'rm -f "$binary"' EXIT
for stream in 0 1; do
    iverilog -g2012 -s tri_oracle_pe_array_tb \
        -P "tri_oracle_pe_array_tb.NO_STALL=$stream" -o "$binary" \
        "$models" "$netlist" verilog/tri_oracle_pe_array_tb.sv
    vvp "$binary"
done
