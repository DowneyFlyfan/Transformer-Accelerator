# Only the seven function/state-proved sizing pairs are eligible.
proc tri_oracle_memory_drive_resize_cell {cell} {
    switch -- $cell {
        NR2D1BWP12T40P140 {return NR2D2BWP12T40P140}
        BUFFD1BWP12T40P140 {return BUFFD2BWP12T40P140}
        AOI22D1BWP12T40P140 {return AOI22D2BWP12T40P140}
        SDFQD0BWP12T40P140 {return SDFQD1BWP12T40P140}
        CKND2D1BWP12T40P140 {return CKND2D2BWP12T40P140}
        INR2D1BWP12T40P140 {return INR2D2BWP12T40P140}
        INVD1BWP12T40P140 {return INVD2BWP12T40P140}
        default {error "Unproved memory-driver sizing pair: $cell"}
    }
}

# Preserve orientation and all placement/protection states. The eight scan
# clock loads cannot move; only combinational targets may move at most 10um.
proc tri_oracle_memory_drive_resize_row {name before after replacement} {
    tri_oracle_memory_route_valid_row $before
    tri_oracle_memory_route_valid_row $after
    set original [lindex $before 0]
    if {[tri_oracle_memory_drive_resize_cell $original] ne $replacement ||
        [lindex $after 0] ne $replacement} {error "Unexpected target sizing pair: $name"}
    if {[lindex $before 3] ne {placed} || [lindex $before 4] ne {unset} ||
        [lindex $before 5] ne {placed} || [lindex $before 6] ne {none}} {
        error "Target is fixed, clock-tree-placed or protected: $name"
    }
    if {[lrange $before 2 end] ne [lrange $after 2 end]} {
        error "Target orientation/placement/protection changed: $name"
    }
    lassign [lindex $before 1] bx by
    lassign [lindex $after 1] ax ay
    set displacement [expr {($ax-$bx)*($ax-$bx)+($ay-$by)*($ay-$by)}]
    set scan [expr {$original eq {SDFQD0BWP12T40P140}}]
    if {$scan && $displacement != 0} {error "Scan clock-load placement changed: $name"}
    if {!$scan && $displacement > 400000000} {error "Combinational target moved beyond10um: $name"}
    return [dict create scan_clock_load $scan displacement_squared_dbu2 $displacement]
}

proc tri_oracle_memory_drive_resize_scope_counts {seen expected resized scans added} {
    tri_oracle_memory_route_scope_counts $seen $expected $added
    foreach value [list $resized $scans] {
        if {![string is integer -strict $value]} {error "Noninteger driver repair coverage"}
    }
    if {$expected < 16 || $resized != 16 || $scans != 8} {
        error "Missing/extra driver target or scan-load coverage"
    }
}

# Incident pins may have a native single-connection unused net. Such a net
# must preserve its sole pin/port exactly, while active nets use the existing
# complete inventory policy and must be routed before final acceptance.
proc tri_oracle_memory_drive_net_inventory {connections pins ports} {
    if {[string is integer -strict $connections] && $connections == 1} {
        if {[llength $pins]+[llength $ports] != 1} {error "Incomplete inactive incident net"}
        foreach name [concat $pins $ports] {
            if {![regexp {^\S+$} $name]} {error "Invalid inactive incident connection"}
        }
        return [list 1 [lsort $pins] [lsort $ports]]
    }
    return [tri_oracle_memory_wire_inventory $connections $pins $ports]
}
