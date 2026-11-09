# Shared block selection. The default preserves the verified array flow.
set root /home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator
set top tri_oracle_pe_array
if {[info exists ::env(TRI_ORACLE_TOP)]} {set top $::env(TRI_ORACLE_TOP)}
if {$top ni {tri_oracle_pe_array tri_oracle_memory_compute tri_oracle_sparse_weight_dma tri_oracle_tile_executor tri_oracle_feedforward_core}} {
    error "Unsupported physical block: $top"
}
set out $root/.cache/physical/pnr/$top
