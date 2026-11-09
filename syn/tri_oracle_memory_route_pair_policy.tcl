# Preserve each reported conflict pair so ordinary-data routing can cover
# every violation without silently selecting its clock or supply counterpart.
proc tri_oracle_memory_route_drc_pairs {text} {
    set pairs {}
    set pending {}
    set total {}
    set clean false
    foreach raw [split $text \n] {
        set line [string trim $raw]
        if {$line eq {} || [string index $line 0] eq {#}} {continue}
        if {[regexp {^CUTSPACING: \( Cut EolSpacing \) Regular Wire of Net (\S+) & Regular Wire of Net (\S+)  \( (VIA[234]) \)$} \
            $line -> first second layer]} {
            if {$pending ne {} || $total ne {} || $clean} {error "Unexpected cut-spacing record order"}
            set pending [dict create first $first second $second layer $layer]
        } elseif {[regexp {^Bounds : \( ([-+0-9.]+), ([-+0-9.]+) \) \( ([-+0-9.]+), ([-+0-9.]+) \)$} \
            $line -> xlo ylo xhi yhi]} {
            if {$pending eq {} || $total ne {} || $clean} {error "Cut bounds have no violation"}
            foreach value [list $xlo $ylo $xhi $yhi] {
                if {![string is double -strict $value] ||
                    [catch {expr {abs($value) < 1000000}} finite] || !$finite} {
                    error "Invalid native cut-spacing bounds"
                }
            }
            if {$xlo >= $xhi || $ylo >= $yhi} {error "Inverted native cut-spacing bounds"}
            dict set pending bounds [list $xlo $ylo $xhi $yhi]
            lappend pairs $pending
            set pending {}
        } elseif {[regexp {^Total Violations : ([0-9]+) Viols\.$} $line -> count]} {
            if {$total ne {} || $pending ne {}} {error "Repeated or premature native cut total"}
            set total $count
        } elseif {[regexp {^No DRC violations were found\.?$} $line]} {
            if {$clean || $pending ne {} || [llength $pairs] != 0} {error "Conflicting clean geometry result"}
            set clean true
        } else {error "Unsupported native geometry report line: $line"}
    }
    if {$pending ne {} || [llength $pairs] >= 200} {error "Truncated or unbounded cut-spacing report"}
    if {$clean} {
        if {$total ne {} && $total != 0} {error "Clean report has a nonzero total"}
    } elseif {$total eq {} || $total != [llength $pairs]} {
        error "Missing or inconsistent final cut-spacing total"
    }
    return $pairs
}

proc tri_oracle_memory_route_data_targets {pairs classifications} {
    if {[llength $pairs] == 0 || [llength $pairs] >= 200} {error "Expected bounded nonempty conflicts"}
    set targets {}
    foreach pair $pairs {
        set covered false
        foreach net [list [dict get $pair first] [dict get $pair second]] {
            if {![dict exists $classifications $net]} {error "Missing native classification: $net"}
            set flags [dict get $classifications $net]
            foreach key {is_clock is_power is_ground} {
                if {![dict exists $flags $key] ||
                    ![string is boolean -strict [dict get $flags $key]]} {
                    error "Incomplete native data-net classification: $net"
                }
            }
            if {![dict get $flags is_clock] && ![dict get $flags is_power] &&
                ![dict get $flags is_ground]} {
                lappend targets $net
                set covered true
            }
        }
        if {!$covered} {error "Cut conflict has no ordinary data-net counterpart"}
    }
    return [lsort -unique $targets]
}
