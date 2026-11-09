# Read-only inventory of the native protection attribute; preserve enum values
# verbatim rather than treating the attribute as an assumed Boolean.
source syn/tri_oracle_memory_physical_config.tcl
set tag postroute_probe_protection_states
if {$::env(TRI_ORACLE_PHYSICAL_STAGE) ne $tag} {error "Unexpected protection probe stage"}
set destination $out/${tag}.rpt
if {![catch {file lstat $destination ignored}]} {error "Refusing existing protection probe"}
set_multi_cpu_usage -local_cpu 20
read_db $out/postroute_endpoint_free_slots_02.db
tri_oracle_require_memory_design
set counts [dict create]
set samples [dict create]
set total 0
foreach inst [get_db insts] {
    set state [get_db $inst .dont_touch]
    dict incr counts $state
    if {![dict exists $samples $state] || [llength [dict get $samples $state]] < 5} {
        dict lappend samples $state [list [get_db $inst .name] [get_db $inst .base_cell.name]]
    }
    incr total
}
if {$total != 906419} {error "Protection probe instance coverage changed"}
set channel [open $destination w]
try {
    puts $channel "total_instances $total"
    foreach state [lsort [dict keys $counts]] {
        puts $channel [list state $state count [dict get $counts $state] samples [dict get $samples $state]]
    }
} finally {close $channel}
puts "TRI_ORACLE_MEMORY_PROTECTION_STATES_OBSERVED [dict size $counts] INSTANCES $total"
puts "TRI_ORACLE_MEMORY_PROTECTION_PROBE_FINISHED"
exit
