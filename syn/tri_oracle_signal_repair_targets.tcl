# Native report readers for bounded selected-net repairs. These functions only
# choose targets; fresh full physical qualification determines whether a repair
# succeeded. Unsupported or incomplete formats stop before any routing change.
proc tri_oracle_route_drv_targets {text kind} {
    if {$kind ni {max_tran max_cap}} {error "Unsupported electrical violation kind"}
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
            if {$current ne {} && $current_rows == 0} {error "Electrical net group has no violation rows"}
            set current $line
            set current_rows 0
            lappend names $current
        } elseif {[regexp {^\s+\S+\s+\S+\s+\S+\s+\S+\s+\S+\s+[A-Z]\s*$} $line]} {
            if {$current eq {}} {error "Slew violation has no parent net"}
            incr rows
            incr current_rows
        } else {
            error "Unsupported slew report row: $line"
        }
    }
    if {$current ne {} && $current_rows == 0} {error "Electrical net group has no violation rows"}
    if {[llength $totals] != 1 || $rows != [lindex $totals 0] || $rows > 1000} {
        error "Missing, truncated or unbounded slew report"
    }
    set names [lsort -unique $names]
    if {[llength $names] > 200 || ([llength $names] == 0) != ($rows == 0)} {
        error "Invalid slew target inventory"
    }
    return $names
}

proc tri_oracle_route_slew_targets {text} {
    return [tri_oracle_route_drv_targets $text max_tran]
}

proc tri_oracle_route_capacitance_targets {text} {
    return [tri_oracle_route_drv_targets $text max_cap]
}

proc tri_oracle_route_require_data_net {name clock power ground} {
    if {$clock || $power || $ground} {error "Selected repair only covers ordinary data nets: $name"}
}

proc tri_oracle_route_glitch_targets {text} {
    set names {}
    set totals {}
    foreach line [split $text \n] {
        set line [string trim $line]
        if {$line eq {} || [regexp {^(#|NetName\s)} $line]} {continue}
        if {[regexp {^Total number of glitch violations: ([0-9]+)$} $line -> total]} {
            lappend totals $total
        } elseif {[regexp {^(\S+)\s+(\S+)\s+\S+\s+(\S+)\s+\S+$} $line -> name low high]} {
            foreach peak [list $low $high] {
                if {![string is double -strict $peak] ||
                    [catch {expr {abs($peak) < 10}} finite] || !$finite} {
                    error "Invalid reported glitch peak"
                }
            }
            lappend names $name
        } else {
            error "Unsupported glitch report row: $line"
        }
    }
    if {[llength $totals] != 1 || [llength $names] != [lindex $totals 0] || [llength $names] > 200} {
        error "Missing, truncated or unbounded glitch report"
    }
    return [lsort -unique $names]
}

proc tri_oracle_route_antenna_targets {text} {
    set names {}
    set rows 0
    set counts {}
    foreach line [split $text \n] {
        if {[regexp {^Net (\S+)$} $line -> name]} {lappend names $name}
        if {[regexp {^\s*VIO:} $line]} {incr rows}
        if {[regexp {Total number of process antenna violations:\s*([0-9]+) Viols\s+Number of nets violated:\s*([0-9]+)\.} $line -> total nets]} {
            lappend counts [list $total $nets]
        }
    }
    set names [lsort -unique $names]
    if {[llength $counts] == 0 && $rows == 0 && [llength $names] == 0 &&
        [string first "No Ant violations were found" $text] >= 0} {return {}}
    if {[llength $counts] != 1 || $rows != [lindex $counts 0 0] ||
        [llength $names] != [lindex $counts 0 1] || [llength $names] > 100} {
        error "Missing, truncated or unbounded antenna report"
    }
    return $names
}
