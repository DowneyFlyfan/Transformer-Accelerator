# Read-only isolation of the routed checkpoint's library-loading failure.
source syn/tri_oracle_memory_physical_config.tcl
if {![info exists ::env(TRI_ORACLE_RESTORE_CPUS)] ||
    $::env(TRI_ORACLE_RESTORE_CPUS) ni {1 20}} {
    error "Restore probe requires exactly1 or20 loader processors"
}
set loader_cpus $::env(TRI_ORACLE_RESTORE_CPUS)
puts "TRI_ORACLE_MEMORY_RESTORE_LOADER_CPUS $loader_cpus"
set_multi_cpu_usage -local_cpu $loader_cpus
read_db $out/routed_before_optimization.db
tri_oracle_require_memory_design
set_multi_cpu_usage -local_cpu 20
puts "TRI_ORACLE_MEMORY_RESTORE_PROBE_FINISHED"
exit
