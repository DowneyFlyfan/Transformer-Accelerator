# Read-only Innovus diagnostic for large data-net loads on the placed chip.
if {[catch {
    set_multi_cpu_usage -local_cpu 1
    read_db $::env(TRI_ORACLE_FANOUT_CHECKPOINT)
    if {[get_db current_design .name] ne "tri_oracle_chip_command_layer_parallel_chip"} {
        error "Unexpected placement design"
    }
    set view setup_slow
    set_analysis_view -setup [list $view] -hold [list $view]
    set view_object [get_db analysis_views $view]
    if {[llength $view_object] != 1} {error "Missing slow analysis view"}
    set threshold $::env(TRI_ORACLE_FANOUT_THRESHOLD)
    if {![string is integer -strict $threshold] || $threshold < 64} {error "Invalid fanout threshold"}
    set candidates [get_db nets -if [format {.num_loads >= %d && .is_clock == false && .is_power == false && .is_ground == false} $threshold]]
    puts "TRI_ORACLE_FANOUT_CANDIDATES [llength $candidates]"
    set stream [open placed_fanout.tsv {WRONLY CREAT EXCL}]
    puts $stream "net\tdriver\tloads\tpin_load_pf\tlimit_pf\tmissing_sink_caps"
    set eligible 0
    foreach net $candidates {
        set driver [get_db $net .driver_pins]
        if {[llength $driver] != 1 || [get_db $net .num_drivers] != 1} {continue}
        set limit [get_db $driver .max_capacitance -index $view_object]
        if {![string is double -strict $limit] || $limit <= 0} {continue}
        set sum 0.0
        set missing 0
        set sinks [get_db $net .load_pins]
        set caps [get_db $sinks .capacitance_max -index $view_object]
        if {[llength $caps] != [llength $sinks]} {error "Sink capacitance cardinality mismatch"}
        foreach cap $caps {
            if {[string is double -strict $cap] && $cap >= 0} {
                set sum [expr {$sum + $cap}]
            } else {
                incr missing
            }
        }
        puts $stream [join [list [get_db $net .name] [get_db $driver .name] [llength $sinks] \
                              [format %.9f $sum] [format %.9f $limit] $missing] \t]
        incr eligible
    }
    close $stream
    puts "TRI_ORACLE_PLACED_FANOUT_DONE $eligible"
} message options]} {
    puts stderr [dict get $options -errorinfo]
    exit 1
}
exit 0
