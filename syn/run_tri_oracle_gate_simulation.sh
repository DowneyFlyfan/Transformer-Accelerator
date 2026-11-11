#!/usr/bin/env bash
# Run the mapped array's functional regression inside the Cadence image.
set -euo pipefail
netlist=.cache/physical/synthesis/tri_oracle_pe_array/netlist.v
models=.cache/physical/library/tcbn28hpcplusbwp12t40p140.v
test -s "$netlist"
test -s "$models"
build=$(mktemp -d "$PWD/.cache/tri_oracle_pe_gate.XXXXXX")
trap 'rm -rf -- "$build"' EXIT
for no_stall in 0 1; do
    /opt/cadence/bin/xrun -64bit -sv -nospecify -notimingchecks -clean \
        -top tri_oracle_pe_array_tb -defparam "tri_oracle_pe_array_tb.NO_STALL=$no_stall" \
        -xmlibdirname "$build/xcelium.d" -l "$build/xrun.log" -history_file "$build/xrun.history" \
        "$models" "$netlist" verilog/tri_oracle_pe_array_tb.sv
    grep -Fxq "PASS: 300 full 32x8 signed compute transactions, masks, stalls, reset; NO_STALL=$no_stall" \
        "$build/xrun.log"
done
