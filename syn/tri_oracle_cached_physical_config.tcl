# Cached-top physical configuration; older qualified flows stay unchanged.
set root /home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator
set top tri_oracle_cached_feedforward_core
if {[info exists ::env(TRI_ORACLE_TOP)] && $::env(TRI_ORACLE_TOP) ne $top} {
    error "Cached physical entry requires tri_oracle_cached_feedforward_core"
}
set out $root/.cache/physical/pnr/$top
