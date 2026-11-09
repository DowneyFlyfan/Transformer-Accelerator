# Admit only the two complete native rule forms observed in the current flow.
# Keep duplicate/directed markers: their count must equal the native total.
proc tri_oracle_memory_current_geometry_pairs {text} {
    set pairs {}
    set pending {}
    set total {}
    set clean false
    foreach raw [split $text \n] {
        set line [string trim $raw]
        if {$line eq {} || [string index $line 0] eq {#}} {continue}
        if {[regexp {^CUTSPACING: \( Cut EolSpacing \) Regular Wire of Net (\S+) & Regular Wire of Net (\S+)  \( (VIA[1234]) \)$} \
            $line -> first second layer]} {
            if {$pending ne {} || $total ne {} || $clean} {error "Unexpected geometry record order"}
            set pending [dict create first $first second $second layer $layer kind CUTSPACING]
        } elseif {[regexp {^EndOfLine: \( EndOfLine Spacing \) Regular Wire of Net (\S+) & Regular Wire of Net (\S+)  \( (M2) \)$} \
            $line -> first second layer]} {
            if {$pending ne {} || $total ne {} || $clean} {error "Unexpected geometry record order"}
            set pending [dict create first $first second $second layer $layer kind EndOfLine]
        } elseif {[regexp {^Bounds : \( ([-+0-9.]+), ([-+0-9.]+) \) \( ([-+0-9.]+), ([-+0-9.]+) \)$} \
            $line -> xlo ylo xhi yhi]} {
            if {$pending eq {} || $total ne {} || $clean} {error "Geometry bounds have no violation"}
            foreach value [list $xlo $ylo $xhi $yhi] {
                if {![string is double -strict $value] ||
                    [catch {expr {abs($value) < 1000000}} finite] || !$finite} {error "Invalid geometry bounds"}
            }
            if {$xlo >= $xhi || $ylo >= $yhi} {error "Inverted geometry bounds"}
            dict set pending bounds [list $xlo $ylo $xhi $yhi]
            lappend pairs $pending
            set pending {}
        } elseif {[regexp {^Total Violations : ([0-9]+) Viols\.$} $line -> count]} {
            if {$total ne {} || $pending ne {}} {error "Repeated or premature geometry total"}
            set total $count
        } elseif {[regexp {^No DRC violations were found\.?$} $line]} {
            if {$clean || $pending ne {} || [llength $pairs]} {error "Conflicting clean geometry report"}
            set clean true
        } else {error "Unsupported native geometry line: $line"}
    }
    if {$pending ne {} || [llength $pairs] >= 200} {error "Truncated or unbounded geometry report"}
    if {$clean} {
        if {$total ne {} && $total != 0} {error "Clean report has nonzero geometry total"}
    } elseif {$total eq {} || $total != [llength $pairs]} {error "Missing or inconsistent geometry total"}
    return $pairs
}
