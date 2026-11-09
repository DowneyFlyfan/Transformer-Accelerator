# Only these logic-equivalent sizing pairs were checked in native Icarus.
proc tri_oracle_slew_resize_cell {cell} {
    switch -- $cell {
        INVD1P25BWP12T40P140 {return INVD2BWP12T40P140}
        BUFFD1BWP12T40P140 {return BUFFD2BWP12T40P140}
        OR4D0BWP12T40P140 {return OR4D1BWP12T40P140}
        default {error "Unverified slew-driver sizing pair: $cell"}
    }
}

# Each inventory row is {base_cell {x y} orientation}. Target cells may move
# during legalization; every other original cell must retain all three fields.
proc tri_oracle_resize_point {value} {
    # get_db returns a list of points even for one instance; test fixtures may
    # supply the single point directly. Both representations denote one point.
    if {[llength $value] == 1} {set value [lindex $value 0]}
    if {[llength $value] != 2} {error "Expected one physical coordinate pair"}
    foreach coordinate $value {
        if {![string is double -strict $coordinate]} {error "Non-numeric physical coordinate"}
        if {[catch {expr {abs($coordinate) < 10000000.0}} finite] || !$finite} {error "Non-finite physical coordinate"}
    }
    return $value
}

proc tri_oracle_require_slew_resize_inventory {before after expected {allow_antenna false}} {
    if {[dict size $expected] != 4 || [dict size $before] < 4} {
        error "This repair requires exactly four independently admitted drivers"
    }
    dict for {name replacement} $expected {
        if {![dict exists $before $name] || ![dict exists $after $name]} {error "Missing resized driver: $name"}
        if {[tri_oracle_slew_resize_cell [lindex [dict get $before $name] 0]] ne $replacement} {
            error "Replacement differs from the checked logic pair at $name"
        }
    }
    set maximum_displacement 0.0
    dict for {name original} $before {
        if {[llength $original] != 3 || ![dict exists $after $name]} {error "Missing original physical instance: $name"}
        set current [dict get $after $name]
        if {[llength $current] != 3} {error "Malformed physical inventory at $name"}
        if {[dict exists $expected $name]} {
            if {[lindex $current 0] ne [dict get $expected $name]} {error "Driver was not resized as admitted: $name"}
            lassign [tri_oracle_resize_point [lindex $original 1]] old_x old_y
            lassign [tri_oracle_resize_point [lindex $current 1]] new_x new_y
            set dx [expr {$new_x - $old_x}]
            set dy [expr {$new_y - $old_y}]
            set displacement [expr {sqrt($dx*$dx + $dy*$dy)}]
            # The preceding unconstrained ECO placement moved drivers50-405um
            # and broke setup. This experiment permits only local legalization.
            if {$displacement > 10.0} {error "Driver legalization exceeded10um: $name"}
            set maximum_displacement [expr {max($maximum_displacement,$displacement)}]
        } elseif {$current ne $original} {
            error "Non-target cell, position or orientation changed: $name"
        }
    }
    set antennas 0
    dict for {name current} $after {
        if {[dict exists $before $name]} {continue}
        if {!$allow_antenna || [llength $current] != 3 || [lindex $current 0] ne {ANTENNABWP12T40P140}} {
            error "Unexpected added physical instance: $name"
        }
        incr antennas
    }
    if {$antennas > 8} {error "Unexpectedly large antenna insertion set"}
    return [dict create resized_instances 4 retained_original_instances [dict size $before] added_antenna_instances $antennas maximum_target_displacement_um $maximum_displacement]
}
