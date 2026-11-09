#!/usr/bin/env bash
set -euo pipefail
for corner in tt1v25c ssg0p9v125c ffg1p05vm40c; do
    output=".cache/physical/corner_checks/$corner"
    mkdir -p "$output"
    export TRI_ORACLE_CORNER="$corner"
    export TRI_ORACLE_LIBS=".cache/physical/library/tcbn28hpcplusbwp12t40p140${corner}.lib"
    /usr/bin/time -v genus -no_gui -batch -log "$output/genus" \
        -files syn/tri_oracle_report_mapped_timing.tcl > "$output/console.log" 2>&1
    grep -q "TRI_ORACLE_CORNER_CHECK_PASS $corner" "$output/console.log"
done
printf 'All three mapped-netlist corner checks completed.\n'
