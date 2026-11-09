# Exact native forms observed after the sixteen proved cell replacements.
# A cell counterpart is never interpreted as a routable net.
proc tri_oracle_memory_resized_cell_geometry_pairs {text} {
    set headers [regexp -all -line -inline {^#[ \t]*Design:[ \t]*(\S+)[ \t]*$} $text]
    if {[string length $text] > 2097152 || [llength $headers] != 2 ||
        [lindex $headers 1] ne {tri_oracle_memory_feedforward_core}} {
        error "Missing or conflicting resized-cell design header"
    }
    set forms [dict create \
        SPACING [list {ParallelRunLength Spacing} {M1 M2}] \
        SHORT [list {Metal Short} {M1 M2}] \
        EndOfLine [list {EndOfLine Spacing} {M1}] \
        CUTSPACING [list {Different Layer Cut Spacing} {VIA1}]]
    set pairs {}
    set pending {}
    set total {}
    set clean false
    foreach raw [split $text \n] {
        set line [string trim $raw]
        if {$line eq {} || [string index $line 0] eq {#}} {continue}
        if {[regexp {^([A-Za-z_]+): \( ([^()]+) \) Regular Wire of Net (\S+) & (Blockage of Cell|Pin of Cell) (\S+)  \( (M[0-9]+|VIA[0-9]+) \)$} \
            $line -> kind reason first second_type second layer]} {
            if {$pending ne {} || $total ne {} || $clean || ![dict exists $forms $kind]} {
                error "Unexpected resized-cell geometry record"
            }
            lassign [dict get $forms $kind] expected_reason layers
            if {$reason ne $expected_reason || $layer ni $layers ||
                [regexp {[*?]} $first] || [regexp {[*?]} $second]} {
                error "Unsupported resized-cell rule or counterpart"
            }
            set pending [dict create first $first second $second second_object_type $second_type \
                kind $kind reason $reason layer $layer]
        } elseif {[regexp {^Bounds : \( ([-+0-9.]+), ([-+0-9.]+) \) \( ([-+0-9.]+), ([-+0-9.]+) \)$} \
            $line -> xlo ylo xhi yhi]} {
            if {$pending eq {} || $total ne {} || $clean} {error "Geometry bounds have no current rule"}
            foreach value [list $xlo $ylo $xhi $yhi] {
                if {![string is double -strict $value] ||
                    [catch {expr {abs($value) < 1000000}} finite] || !$finite} {
                    error "Nonfinite resized-cell geometry bounds"
                }
            }
            if {$xlo >= $xhi || $ylo >= $yhi} {error "Inverted resized-cell geometry bounds"}
            dict set pending bounds [list $xlo $ylo $xhi $yhi]
            lappend pairs $pending
            set pending {}
        } elseif {[regexp {^Total Violations : ([0-9]+) Viols\.$} $line -> count]} {
            if {$total ne {} || $pending ne {}} {error "Repeated or premature geometry total"}
            set total $count
        } elseif {[regexp {^No DRC violations were found\.?$} $line]} {
            if {$clean || $pending ne {} || [llength $pairs]} {error "Conflicting clean geometry report"}
            set clean true
        } else {error "Unsupported resized-cell geometry line: $line"}
    }
    if {$pending ne {} || [llength $pairs] >= 200} {error "Incomplete or unbounded resized-cell geometry"}
    if {$clean} {
        if {$total ne {} && $total != 0} {error "Conflicting clean geometry total"}
    } elseif {$total eq {} || $total != [llength $pairs]} {error "Missing or inconsistent geometry total"}
    return $pairs
}
proc tri_oracle_memory_resized_cell_data_targets {pairs classes allowed_cells} {
    set result {}
    foreach pair $pairs {
        set name [dict get $pair first]
        if {[dict get $pair second_object_type] ni {{Blockage of Cell} {Pin of Cell}} ||
            [dict get $pair second] ni $allowed_cells || ![dict exists $classes $name]} {
            error "Geometry counterpart lacks exact native admission"
        }
        foreach flag {is_clock is_power is_ground} {
            set value [dict get $classes $name $flag]
            if {![string is boolean -strict $value] || $value} {
                error "Resized-cell repair requires an ordinary data net"
            }
        }
        lappend result $name
    }
    return [lsort -unique $result]
}
