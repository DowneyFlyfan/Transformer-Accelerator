#!/usr/bin/env bash
set -euo pipefail
: "${TRI_ORACLE_TOP:?Specify the synthesis top}"
: "${TRI_ORACLE_LIBS:?Specify the Liberty library list}"
cd /home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator
output=".cache/physical/synthesis/$TRI_ORACLE_TOP"
mkdir -p "$output"
trap 'task_exit=$?; printf "%s\n" "$task_exit" > "$output/exit_status"' EXIT
# Preserve cancellation as failure even if the last foreground status was zero.
trap 'exit 143' TERM
trap 'exit 130' INT
date -Is > "$output/started_at"
/usr/bin/time -v genus -no_gui -batch -log "$output/genus" \
    -files syn/tri_oracle_synthesize.tcl > "$output/console.log" 2>&1
grep -q "TRI_ORACLE_SYNTHESIS_PASS $TRI_ORACLE_TOP" "$output/console.log"
date -Is > "$output/finished_at"
