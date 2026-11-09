# Extract only the observed via cut end-of-line spacing repair class. An
# unexpected violation or truncated report requires inspection before routing.
proc tri_oracle_route_drc_targets {text} {
    set names {}
    set count 0
    set bounds 0
    foreach line [split $text \n] {
        if {[regexp {^CUTSPACING: \( Cut EolSpacing \) Regular Wire of Net (\S+) & Regular Wire of Net (\S+)  \( VIA[23] \)$} $line -> first second]} {
            lappend names $first $second
            incr count
        } elseif {[regexp {^[A-Z][A-Z0-9_]+:} $line]} {
            error "Unsupported physical violation: $line"
        } elseif {[regexp {^Bounds :} $line]} {
            incr bounds
        }
    }
    if {$count >= 200 || $count != $bounds} {error "Unbounded or incomplete cut-spacing report"}
    if {$count == 0 && [string first "No DRC violations were found" $text] < 0} {
        error "Missing physical violation result"
    }
    return [lsort -unique $names]
}
