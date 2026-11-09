#!/usr/bin/env bash
# Run in the Cadence image with Icarus Verilog installed (cadence-ddi).
set -euo pipefail
netlist=.cache/physical/synthesis/tri_oracle_pe_array/netlist.v
models=.cache/physical/library/tcbn28hpcplusbwp12t40p140.v
test -s "$netlist"
test -s "$models"
binary=.cache/physical/synthesis/tri_oracle_pe_array/gate_simulation.vvp
trap 'rm -f "$binary"' EXIT
iverilog -g2012 -s tri_oracle_pe_array_tb -o "$binary" \
    "$models" "$netlist" verilog/tri_oracle_pe_array_tb.sv
vvp "$binary"
iverilog -g2012 -s tri_oracle_pe_array_tb -P tri_oracle_pe_array_tb.NO_STALL=1 \
    -o "$binary" "$models" "$netlist" verilog/tri_oracle_pe_array_tb.sv
vvp "$binary"
