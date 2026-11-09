# Physical wire removal must not delete logical nets, ports or pin connections.
proc tri_oracle_memory_wire_inventory {connections pins ports} {
    if {![string is integer -strict $connections] || $connections < 2 ||
        $connections > 1000000 ||
        [llength $pins] != [llength [lsort -unique $pins]] ||
        [llength $ports] != [llength [lsort -unique $ports]] ||
        $connections != [llength $pins] + [llength $ports]} {
        error "Incomplete or inconsistent logical net inventory"
    }
    foreach name [concat $pins $ports] {
        if {![regexp {^\S+$} $name]} {error "Invalid logical connection identity"}
    }
    return [list $connections [lsort $pins] [lsort $ports]]
}

proc tri_oracle_memory_wire_deletion {name before after before_wires after_wires} {
    if {[llength $before] != 3 || [llength $after] != 3} {error "Malformed wire-edit inventory"}
    set before [tri_oracle_memory_wire_inventory {*}$before]
    set after [tri_oracle_memory_wire_inventory {*}$after]
    if {$before ne $after} {error "Physical wire removal changed logical connections: $name"}
    foreach count [list $before_wires $after_wires] {
        if {![string is integer -strict $count]} {error "Noninteger native wire count"}
    }
    if {$before_wires < 1 || $after_wires != 0} {error "Selected signal wire removal was incomplete or a no-op: $name"}
    return $before_wires
}

proc tri_oracle_memory_wire_scope_counts {seen expected wires} {
    foreach count [list $seen $expected $wires] {
        if {![string is integer -strict $count]} {error "Noninteger physical edit coverage"}
    }
    if {$expected < 1 || $expected > 600 || $seen != $expected || $wires < $expected} {
        error "Missing, unbounded or no-op selected wire removal"
    }
}

# Routing may add a characterized antenna diode load, but must retain every
# original pin and exactly the same ports. No other logical change is allowed.
proc tri_oracle_memory_wire_routed {name before after diode_pins wires} {
    if {[llength $before] != 3 || [llength $after] != 3} {error "Malformed routed logical inventory"}
    set before [tri_oracle_memory_wire_inventory {*}$before]
    set after [tri_oracle_memory_wire_inventory {*}$after]
    if {![string is integer -strict $wires] || $wires < 1} {error "Selected net remains unrouted: $name"}
    if {[lindex $before 2] ne [lindex $after 2]} {error "Routing changed original ports: $name"}
    foreach pin [lindex $before 1] {
        if {$pin ni [lindex $after 1]} {error "Routing lost original logical pin: $name"}
    }
    foreach pin [lindex $after 1] {
        if {$pin ni [lindex $before 1] && $pin ni $diode_pins} {
            error "Routing added an unqualified logical connection: $name"
        }
    }
    return 1
}

proc tri_oracle_memory_clock_wires {name before after} {
    foreach status [concat $before $after] {
        if {$status ni {unknown routed fixed cover noshield}} {error "Unknown native clock-wire status: $name"}
    }
    if {[lsort $before] ne [lsort $after]} {error "Clock-wire statuses/count changed: $name"}
    return [llength $before]
}

proc tri_oracle_memory_wire_data_use {usage clock power ground} {
    foreach flag [list $clock $power $ground] {
        if {![string is boolean -strict $flag]} {error "Unknown native net classification"}
    }
    if {$usage ni {signal scan} || $clock || $power || $ground} {
        error "Physical edits require native signal/scan data use and no clock/supply flag"
    }
    return 1
}
