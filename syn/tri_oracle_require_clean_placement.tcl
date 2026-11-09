# Fail before routing if this flow's actual check_place report is incomplete or
# reports illegal cells. This is a placement gate, not full physical signoff.
proc tri_oracle_require_clean_placement {report} {
    set file [open $report r]
    set text [read $file]
    close $file
    set placed_matches [regexp -all -line -inline {^[ \t]*\*info:[ \t]*Placed[ \t]*=[ \t]*([0-9]+)} $text]
    if {[llength $placed_matches] != 2 || [lindex $placed_matches 1] == 0} {
        error "Missing positive placed-cell count in $report"
    }
    set placed [lindex $placed_matches 1]
    set unplaced_matches [regexp -all -line -inline {^[ \t]*\*info:[ \t]*Unplaced[ \t]*=[ \t]*([0-9]+)} $text]
    if {[llength $unplaced_matches] != 2 || [lindex $unplaced_matches 1] != 0} {
        error "Unplaced cells or incomplete placement report: $report"
    }
    if {[regexp -all -line {^Finished check_place([ \t]|$)} $text] != 1} {error "Incomplete or repeated placement report: $report"}
    set density_matches [regexp -all -line -inline {^Placement Density:([0-9.]+)%} $text]
    if {[llength $density_matches] != 2} {error "Missing or repeated placement density in $report"}
    set density [lindex $density_matches 1]
    if {$density <= 0 || $density > 100} {
        error "Missing or invalid placement density in $report"
    }
    if {[regexp -nocase {\m(violations?|overlap(s|ped|ping)?|illegal|errors?|warnings?)\M} $text]} {
        error "Placement diagnostic requires repair before routing: $report"
    }
    return [list $placed $density]
}
