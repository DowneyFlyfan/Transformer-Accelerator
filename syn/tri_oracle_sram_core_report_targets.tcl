# Read a complete, explicitly counted native core electrical report. The earlier
# leaf reader retains its 200-net admission limit; this reader does not modify it.
proc tri_oracle_sram_core_drv_targets {text kind expected_rows} {
    if {$kind ni {max_tran max_cap} || ![string is integer -strict $expected_rows] ||
        $expected_rows < 0 || $expected_rows > 10000} {
        error "Invalid core report contract"
    }
    set names {}
    set current {}
    set current_rows 0
    set rows 0
    set totals {}
    foreach line [split $text \n] {
        if {[string trim $line] eq {} || [regexp {^#} $line]} {continue}
        set summary [format {^\*info: there (?:is|are) ([0-9]+) %s violations? in the design\.$} $kind]
        if {[regexp $summary $line -> total]} {
            lappend totals $total
        } elseif {[regexp {^\*info: [0-9]+ violations? (?:is|are) real \(remark R\)\.$} $line]} {
            continue
        } elseif {[regexp {^[^#\s*]\S*$} $line]} {
            if {$current ne {} && $current_rows == 0} {error "Core net group has no violation rows"}
            set current $line
            set current_rows 0
            lappend names $current
        } elseif {[regexp {^\s+\S+\s+\S+\s+\S+\s+\S+\s+\S+\s+[A-Z]\s*$} $line]} {
            if {$current eq {}} {error "Core violation has no parent net"}
            incr rows
            incr current_rows
        } else {
            error "Unsupported core electrical row: $line"
        }
    }
    if {$current ne {} && $current_rows == 0} {error "Core net group has no violation rows"}
    if {[llength $totals] != 1 || $rows != [lindex $totals 0] || $rows != $expected_rows} {
        error "Missing, truncated or unexpected core electrical inventory"
    }
    set names [lsort -unique $names]
    if {[llength $names] > $rows || ([llength $names] == 0) != ($rows == 0)} {
        error "Invalid core electrical target inventory"
    }
    return $names
}
