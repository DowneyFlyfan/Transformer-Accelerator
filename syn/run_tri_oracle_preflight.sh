#!/usr/bin/env bash
set -euo pipefail
: "${TRI_ORACLE_LIBS:?Set TRI_ORACLE_LIBS to a Tcl list of standard-cell Liberty files visible inside the Cadence container}"
cd /home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator
mkdir -p .cache/physical/preflight
for unit in token_merger head_predictor snzv_predictor proportional_normalizer pe_array memory_compute compute_cluster compute_fabric; do
  export TRI_ORACLE_TOP="tri_oracle_${unit}"
  mkdir -p ".cache/physical/preflight/$TRI_ORACLE_TOP"
  /usr/bin/time -v genus -no_gui -batch \
    -log ".cache/physical/preflight/$TRI_ORACLE_TOP/genus" \
    -files syn/tri_oracle_preflight.tcl \
    > ".cache/physical/preflight/$TRI_ORACLE_TOP/console.log" 2>&1
  grep -q "TRI_ORACLE_ELABORATION_PASS $TRI_ORACLE_TOP" \
    ".cache/physical/preflight/$TRI_ORACLE_TOP/console.log"
done
printf 'All eight Genus elaboration checks passed.\n'
