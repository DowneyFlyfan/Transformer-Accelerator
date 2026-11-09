#!/usr/bin/env bash
# Bounded banked full-capacity core mapping; not static-RAM macro mapping.
set -euo pipefail
cd /home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator
export TRI_ORACLE_TOP=tri_oracle_memory_compute
export TRI_ORACLE_REUSE_PE=1
export TRI_ORACLE_LIBS=.cache/physical/library/tcbn28hpcplusbwp12t40p140ssg0p9v125c.lib
export TRI_ORACLE_SYNTH_ENTRY=syn/tri_oracle_synthesize_banked_core.tcl
export TRI_ORACLE_GUARD_SECONDS=3600
export TRI_ORACLE_GUARD_ANON_GIB=12
export TRI_ORACLE_SAVE_SYNTH_CHECKPOINTS=1
exec bash syn/run_tri_oracle_guarded_synthesis.sh
