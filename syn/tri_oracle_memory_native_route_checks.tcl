# Native adapters use the already qualified pure preservation policies.
proc tri_oracle_memory_native_names {objects} {
    if {[llength $objects] == 0} {return {}}
    return [get_db $objects .name]
}

proc tri_oracle_memory_native_data_net {name} {
    if {[regexp {[*?]} $name]} {error "Ambiguous native data-net pattern: $name"}
    set net [get_db nets $name]
    if {[llength $net] != 1 || [get_db $net .name] ne $name} {error "Missing exact data net: $name"}
    tri_oracle_memory_wire_data_use [get_db $net .use] [get_db $net .is_clock] \
        [get_db $net .is_power] [get_db $net .is_ground]
    return $net
}

proc tri_oracle_memory_native_logical {net} {
    set ports [lsort -unique [concat [get_db $net .driver_ports] [get_db $net .load_ports]]]
    return [tri_oracle_memory_wire_inventory [get_db $net .num_connections] \
        [tri_oracle_memory_native_names [get_db $net .pins]] [tri_oracle_memory_native_names $ports]]
}

proc tri_oracle_memory_native_cell_row {inst} {
    return [list [get_db $inst .base_cell.name] \
        [tri_oracle_memory_point_dbu [get_db $inst .location]] \
        [get_db $inst .orient] [get_db $inst .place_status] \
        [get_db $inst .place_status_cts] [get_db $inst .place_status_effective] \
        [get_db $inst .dont_touch]]
}

proc tri_oracle_memory_native_cells_snapshot {expected} {
    set result [dict create]
    foreach inst [get_db insts] {
        set row [tri_oracle_memory_native_cell_row $inst]
        tri_oracle_memory_route_valid_row $row
        dict set result [get_db $inst .name] $row
    }
    if {[dict size $result] != $expected} {error "Original native cell inventory differs from producer"}
    return $result
}

proc tri_oracle_memory_native_cells_preserved {before} {
    set preserved 0
    set additions {}
    set diode_pins {}
    foreach inst [get_db insts] {
        set name [get_db $inst .name]
        set row [tri_oracle_memory_native_cell_row $inst]
        if {[dict exists $before $name]} {
            tri_oracle_memory_route_original_row $name [dict get $before $name] $row
            incr preserved
        } else {
            tri_oracle_memory_route_added_row $name $row
            lappend additions [list $name $row]
            set diode_pins [concat $diode_pins [tri_oracle_memory_native_names [get_db $inst .pins]]]
        }
    }
    tri_oracle_memory_route_scope_counts $preserved [dict size $before] [llength $additions]
    return [dict create original_cells $preserved added_antenna_diodes $additions allowed_diode_pins $diode_pins]
}

proc tri_oracle_memory_native_require_delays {expected} {
    set delays [get_db insts *TRI_MEMORY_ENDPOINT_HOLD_*]
    if {[llength $delays] != $expected} {error "Protected delay count changed"}
    foreach inst $delays {
        if {[get_db $inst .base_cell.name] ne {DEL100D1BWP12T40P140} ||
            [get_db $inst .dont_touch] ne {true}} {error "Protected delay identity/state changed"}
    }
}

proc tri_oracle_memory_native_clock_status {net} {
    set wires [get_db $net .wires]
    set statuses {}
    if {[llength $wires]} {set statuses [get_db $wires .status]}
    if {[llength $statuses] != [llength $wires]} {error "Incomplete native clock-wire status collection"}
    return $statuses
}

proc tri_oracle_memory_native_clocks_snapshot {} {
    set result [dict create]
    foreach net [get_db nets -if {.is_clock == true}] {
        set statuses [tri_oracle_memory_native_clock_status $net]
        tri_oracle_memory_clock_wires [get_db $net .name] $statuses $statuses
        dict set result [get_db $net .name] $statuses
    }
    if {[dict size $result] < 2 || [dict size $result] > 20000} {error "Unexpected native clock-net inventory"}
    return $result
}

proc tri_oracle_memory_native_clocks_preserved {before} {
    set nets 0
    set wires 0
    foreach net [get_db nets -if {.is_clock == true}] {
        set name [get_db $net .name]
        if {![dict exists $before $name]} {error "Routing added/renamed a clock net"}
        incr wires [tri_oracle_memory_clock_wires $name [dict get $before $name] \
            [tri_oracle_memory_native_clock_status $net]]
        incr nets
    }
    if {$nets != [dict size $before]} {error "Routing lost an original clock net"}
    return [dict create nets $nets wires $wires]
}
