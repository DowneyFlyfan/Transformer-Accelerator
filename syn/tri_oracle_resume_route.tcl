source syn/tri_oracle_physical_config.tcl
set_multi_cpu_usage -local_cpu 18
set checkpoint $out/routed_before_optimization.db
if {[info exists ::env(TRI_ORACLE_ROUTED_CHECKPOINT)]} {
    set checkpoint $::env(TRI_ORACLE_ROUTED_CHECKPOINT)
}
read_db $checkpoint
source $root/syn/tri_oracle_finish_route.tcl
exit
