# Select the actual parent reset obligations after native design import.
# Called while complete core models are unflattened, so all20 real block ports
# and the prediction controller's asynchronous register controls remain visible.
proc tri_oracle_require_parent_registered_resets {sequential_masters report_path} {
    set blocks [get_db insts -if {.base_cell.name == tri_oracle_sram_memory_compute}]
    if {[llength $blocks] != 20} {error "PARENT_RESET34_WRONG_CORE_COUNT"}
    set endpoints {}
    foreach block $blocks {
        set pins {}
        foreach pin [get_db $block .pins] {
            if {[file tail [get_db $pin .base_pin.name]] eq "rst_n"} {lappend pins $pin}
        }
        if {[llength $pins] != 1} {error "PARENT_RESET34_MISSING_CORE_RESET: [get_db $block .name]"}
        lappend endpoints [lindex $pins 0]
    }
    set prediction_count 0
    foreach instance [get_db insts] {
        if {![string match {prediction/*} [get_db $instance .name]]} {continue}
        if {[lsearch -exact $sequential_masters [get_db $instance .base_cell.name]] < 0} {continue}
        foreach pin [get_db $instance .pins] {
            if {[file tail [get_db $pin .base_pin.name]] in {CDN SDN}} {
                lappend endpoints $pin
                incr prediction_count
            }
        }
    }
    if {$prediction_count == 0} {error "PARENT_RESET34_MISSING_PREDICTION_RESET_ENDPOINTS"}
    set summary [tri_oracle_registered_reset_tree $endpoints $sequential_masters $report_path]
    if {[dict get $summary minimum_registered_depth] < 1 || [dict get $summary maximum_registered_depth] < 2} {
        error "PARENT_RESET34_REGISTERED_RESET_LEVELS_MISSING"
    }
    set file [open ${report_path}.summary.rpt w]
    puts $file "core_reset_endpoints: 20"
    puts $file "prediction_async_reset_endpoints: $prediction_count"
    puts $file "all_reset_endpoints: [dict get $summary endpoint_count]"
    puts $file "minimum_registered_depth: [dict get $summary minimum_registered_depth]"
    puts $file "maximum_registered_depth: [dict get $summary maximum_registered_depth]"
    puts $file "registered_source_cells: [dict size [dict get $summary registered_sources]]"
    puts $file "traced_native_reset_nets: [dict get $summary traced_nets]"
    close $file
    return $summary
}
