# get_db .location returns a one-element collection of points in this release.
# Accept that exact shape or a single flat point; reject multiple/nested points.
# This project uses the bound DEF/technology scale of2000 database units per um.
proc tri_oracle_memory_point_dbu {native} {
    if {[llength $native] == 1} {set native [lindex $native 0]}
    if {[llength $native] != 2} {error "Expected exactly one two-coordinate point"}
    set result {}
    foreach coordinate $native {
        if {![string is double -strict $coordinate] ||
            [catch {expr {abs($coordinate) < 1000000}} finite] || !$finite} {
            error "Nonfinite or out-of-range physical coordinate"
        }
        lappend result [expr {round($coordinate*2000)}]
    }
    return $result
}
