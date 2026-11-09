# get_db point collections serialize one point as {{x y}}; scalar points
# may already be flat. Reject ambiguous collections and nonfinite geometry.
proc tri272_point {raw} {
    if {[llength $raw]==1} {set point [lindex $raw 0]} else {set point $raw}
    if {[llength $point]!=2} {error TWO_COORDINATES_REQUIRED}
    set answer {}
    foreach coordinate $point {
        if {![string is double -strict $coordinate] || [catch {expr {abs(double($coordinate)) < Inf}} finite] || !$finite} {error FINITE_COORDINATES_REQUIRED}
        lappend answer [expr {double($coordinate)}]
    }
    return $answer
}
