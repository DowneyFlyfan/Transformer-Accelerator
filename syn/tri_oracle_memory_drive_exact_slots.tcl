# Explicit reviewed coordinates replace a heuristic motion radius. Cell/state
# equivalence and all original scan clock-load positions remain mandatory.
proc tri_oracle_memory_drive_canonical_row {row} {
    tri_oracle_memory_route_valid_row $row
    return [list [lindex $row 0] [list {*}[lindex $row 1]] {*}[lrange $row 2 end]]
}
proc tri_oracle_memory_drive_exact_slot_row {name before after replacement expected_rows} {
    if {[dict size $expected_rows] != 16 || ![dict exists $expected_rows $name]} {
        error "Incomplete or unknown exact driver-slot target"
    }
    set before [tri_oracle_memory_drive_canonical_row $before]
    set after [tri_oracle_memory_drive_canonical_row $after]
    set expected [tri_oracle_memory_drive_canonical_row [dict get $expected_rows $name]]
    if {[lindex $before 0] eq {SDFQD0BWP12T40P140} &&
        [lindex $expected 1] ne [lindex $before 1]} {
        error "Exact-slot plan moves a scan clock load: $name"
    }
    if {$after ne $expected} {error "Target differs from its exact reviewed cell/point/state: $name"}
    # Reuse the proved pair/protection/orientation/placement checks at zero
    # motion. Actual movement is accepted only at the exact bound point above.
    set neutral [lreplace $after 1 1 [lindex $before 1]]
    set result [tri_oracle_memory_drive_resize_row $name $before $neutral $replacement]
    lassign [lindex $before 1] bx by
    lassign [lindex $after 1] ax ay
    dict set result displacement_squared_dbu2 [expr {($ax-$bx)*($ax-$bx)+($ay-$by)*($ay-$by)}]
    return $result
}
