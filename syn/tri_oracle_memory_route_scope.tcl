# Row fields: model, integer database-unit point, orientation, placement status,
# clock-tree status, effective placement status, and don't-touch protection.
proc tri_oracle_memory_route_valid_row {row} {
    if {[llength $row] != 7 || ![regexp {^\S+$} [lindex $row 0]] ||
        [llength [lindex $row 1]] != 2} {error "Malformed physical preservation row"}
    foreach coordinate [lindex $row 1] {
        if {![string is integer -strict $coordinate]} {error "Noninteger physical preservation point"}
    }
    # The complete producer inventory reports enum "none" (899851 cells) or
    # "true" (6568 delays), rather than Boolean false/true. Keep it verbatim.
    if {[lindex $row 6] ni {none true}} {error "Invalid don't-touch state"}
}

proc tri_oracle_memory_route_original_row {name before after} {
    tri_oracle_memory_route_valid_row $before
    tri_oracle_memory_route_valid_row $after
    if {$before ne $after} {error "Routing changed original model/placement/status/protection: $name"}
    return 1
}

proc tri_oracle_memory_route_added_row {name row} {
    tri_oracle_memory_route_valid_row $row
    if {[lindex $row 0] ne {ANTENNABWP12T40P140} ||
        [lindex $row 2] ni {r0 mx my r180} ||
        [lindex $row 3] ni {placed fixed soft_fixed} ||
        [lindex $row 4] ne {unset} ||
        [lindex $row 5] ni {placed fixed soft_fixed}} {
        error "Routing added unexpected logic, clock or unplaced cell: $name"
    }
    return 1
}

proc tri_oracle_memory_route_scope_counts {seen expected added} {
    foreach count [list $seen $expected $added] {
        if {![string is integer -strict $count]} {error "Noninteger route-scope count"}
    }
    if {$expected < 1 || $expected > 1000000 || $seen != $expected || $added < 0 || $added > 8} {
        error "Missing originals or unbounded antenna additions"
    }
}

proc tri_oracle_memory_selected_route_evidence {text} {
    if {$text eq {} || [string length $text] > 67108864 ||
        [regexp -nocase {NRIG-87|NRCM-25|NRDB-187|NRDB-121|SI driven not effective|No slack were found|\*\*ERROR|\*\*FATAL} $text]} {
        error "Selected-route native diagnostics require investigation"
    }
    if {[regexp -all -line {^TRI_ORACLE_MEMORY_SELECTED_ROUTE_MODE true true true$} $text] != 1} {
        error "Timing/signal-integrity/selected-only routing mode was not verified"
    }
    set result [dict create physical_closure_passed false]
    foreach {label key} {{DRC violations} geometry_violations \
        {process antenna violations} antenna_violations \
        {net violated process antenna rule} antenna_nets} {
        set totals [regexp -all -line -inline [format {^#Total number of %s = ([0-9]+)$} $label] $text]
        if {[llength $totals] == 0} {error "Missing selected-route diagnostic count: $label"}
        dict set result $key [lindex $totals end]
    }
    # Native route_detail emits lowercase "statistics" in the selected path;
    # the geometric ECO path uses the capitalized spelling.
    set fails [regexp -all -line -inline {^#Total number of fails = ([0-9]+)$} $text]
    if {[llength $fails] != 2 || [lindex $fails 1] != 0 ||
        [regexp -all -line {^#Complete route_detail on .+$} $text] != 1} {
        error "Missing native route completion or nonzero failures"
    }
    if {![regexp -line {^#route_detail [Ss]tatistics:$} $text] ||
        ![regexp -line {^# +Entire Command +\|[ 0-9:]+\|[ 0-9:]+\|[ 0-9.]+\|$} $text]} {
        error "Incomplete selected-route command statistics"
    }
    return $result
}
