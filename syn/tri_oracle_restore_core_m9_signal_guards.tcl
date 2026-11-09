# The power-access abstract opens real supply exits on metal nine. Restore the
# original abstract's conservative signal keepouts while allowing supplies.
proc tri_oracle_restore_core_m9_signal_guards {instance report_path} {
    set block [get_db insts $instance]
    if {[llength $block] != 1 || [get_db $block .orient] ne "r0" ||
        [get_db $block .place_status] ne "fixed" || ![get_db $block .dont_touch]} {
        error "CORE_POWER43_EXPECTED_PROTECTED_R0_CORE: $instance"
    }
    set location [get_db $block .location]
    if {[llength $location] == 1} {set location [lindex $location 0]}
    if {[llength $location] != 2} {error "CORE_POWER43_INVALID_LOCATION: $location"}
    lassign $location offset_x offset_y
    # Exact original hierarchy_export_58 M9 obstruction rectangles, also bound
    # by records/core_power_access42_interface_qualification.json.
    set original_rectangles {
        {0.0 668.7 719.955 670.0}
        {5.49 664.7 714.35 668.7}
        {9.49 4.5 710.35 664.7}
        {719.35 0.5 719.955 668.7}
        {5.49 0.5 714.35 4.5}
        {0.0 0.5 0.49 668.7}
        {0.0 0.0 719.955 0.5}
    }
    set file [open $report_path w]
    puts $file "name\tlayer\texcept_power_ground\trectangle"
    set index 0
    set guard_prefix [string map {/ _} $instance]
    foreach rectangle $original_rectangles {
        lassign $rectangle x1 y1 x2 y2
        set translated [list [expr {$offset_x+$x1}] [expr {$offset_y+$y1}] \
            [expr {$offset_x+$x2}] [expr {$offset_y+$y2}]]
        set name tri_oracle_${guard_prefix}_m9_signal_guard_${index}
        create_route_blockage -name $name -layers M9 -except_pg_nets -rects $translated
        puts $file "$name\tM9\t1\t$translated"
        incr index
    }
    close $file
    return $index
}
