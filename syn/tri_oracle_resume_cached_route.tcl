source syn/tri_oracle_cached_physical_config.tcl
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
source syn/tri_oracle_release_cached_core.tcl
tri_oracle_release_cached_core
source $root/syn/tri_oracle_finish_route.tcl
exit
