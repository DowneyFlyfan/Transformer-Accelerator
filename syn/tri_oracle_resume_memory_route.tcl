source syn/tri_oracle_memory_physical_config.tcl
set_multi_cpu_usage -local_cpu 20
set checkpoint $out/routed_before_optimization.db
if {[info exists ::env(TRI_ORACLE_ROUTED_CHECKPOINT)]} {
    set checkpoint $::env(TRI_ORACLE_ROUTED_CHECKPOINT)
}
read_db $checkpoint
set loaded_top [get_db current_design .name]
if {$loaded_top ne $top} {
    error "Loaded checkpoint top '$loaded_top' differs from required '$top'"
}
# Restore all required views before repair, even for a pruned saved checkpoint.
# Resume starts the separately checkpointed hold pass; setup follows in its own process.
source syn/tri_oracle_memory_postroute_settings.tcl
source syn/tri_oracle_memory_hold_body.tcl
exit
