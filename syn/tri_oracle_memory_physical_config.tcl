# Memory-driven top physical configuration; older qualified flows stay unchanged.
set root /home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator
set top tri_oracle_memory_feedforward_core
if {[info exists ::env(TRI_ORACLE_TOP)] && $::env(TRI_ORACLE_TOP) ne $top} {
    error "Memory-driven physical entry requires tri_oracle_memory_feedforward_core"
}
set out $root/.cache/physical/pnr/$top

proc tri_oracle_require_memory_design {} {
    set actual [get_db current_design .name]
    if {$actual ne "tri_oracle_memory_feedforward_core"} {
        error "Loaded physical top differs from required memory-driven design: $actual"
    }
}
