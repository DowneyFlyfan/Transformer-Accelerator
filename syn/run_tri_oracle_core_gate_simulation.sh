#!/usr/bin/env bash
# Functional gate simulation only; run in cadence-ddi, which has Icarus.
set -euo pipefail
netlist=${TRI_ORACLE_CORE_NETLIST:-.cache/physical/synthesis/tri_oracle_memory_compute/netlist.v}
bench=${TRI_ORACLE_CORE_BENCH:-tri_oracle_memory_compute_tb}
case "$bench" in
    tri_oracle_memory_compute_tb|tri_oracle_partial_weight_tb|tri_oracle_feedforward_core_tb|tri_oracle_memory_feedforward_core_tb) ;;
    *) echo "Unsupported core testbench: $bench" >&2; exit 2 ;;
esac
models=.cache/physical/library/tcbn28hpcplusbwp12t40p140.v
test -s "$netlist"
test -s "$models"
binary=.cache/${bench}_gate_simulation.vvp
trap 'rm -f "$binary"' EXIT
compile_flags=(-g2012 -gno-specify)
case "${TRI_ORACLE_FUNCTIONAL_LIBRARY_MODE:-0}" in
    0) ;;
    1) compile_flags+=(-DTETRAMAX) ;;
    *) echo "Unsupported functional-library mode" >&2; exit 2 ;;
esac
iverilog "${compile_flags[@]}" -s "$bench" -o "$binary" \
    "$models" "$netlist" "verilog/${bench}.sv"
vvp "$binary"
