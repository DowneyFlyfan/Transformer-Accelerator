if {[llength $argv] > 1} {error "Expected at most one policy source"}
if {[llength $argv]} {
    source [lindex $argv 0]
} else {source syn/tri_oracle_memory_resized_cell_geometry.tcl}
set fixture .cache/physical/pnr/tri_oracle_memory_feedforward_core/postroute_memory_driver_stitch_slots_03.drc.rpt
set file [open $fixture r]
try {set text [read $file]} finally {close $file}
set checks 0
proc require {value label} {
    global checks
    incr checks
    if {!$value} {error "Failed: $label"}
}
proc rejected {body label} {require [catch {uplevel 1 $body}] $label}
set pairs [tri_oracle_memory_resized_cell_geometry_pairs $text]
require [expr {[llength $pairs] == 17}] actual_native_total
set counts [dict create]
set layers [dict create]
set classes [dict create]
set cells {}
foreach pair $pairs {
    dict incr counts [dict get $pair kind]
    dict incr layers [dict get $pair layer]
    dict set classes [dict get $pair first] [dict create is_clock false is_power false is_ground false]
    lappend cells [dict get $pair second]
}
foreach {kind count} {SPACING 7 SHORT 8 EndOfLine 1 CUTSPACING 1} {
    require [expr {[dict get $counts $kind] == $count}] $kind
}
foreach {layer count} {M1 10 M2 6 VIA1 1} {
    require [expr {[dict get $layers $layer] == $count}] $layer
}
set cells [lsort -unique $cells]
set names [tri_oracle_memory_resized_cell_data_targets $pairs $classes $cells]
require [expr {[llength $names] == 7}] seven_actual_regular_net_counterparts
require [expr {[llength $cells] == 6}] six_actual_resized_cells
foreach {label broken} [list \
    wrong_total [string map {{Total Violations : 17 Viols.} {Total Violations : 16 Viols.}} $text] \
    duplicate_header "$text\n# Design: wrong_top\n" \
    missing_total [regsub {Total Violations : 17 Viols\.} $text {}] \
    unknown_reason [string map {{Metal Short} {Unknown Rule}} $text] \
    wrong_counterpart [string map {{Blockage of Cell} {Regular Wire of Net}} $text] \
    missing_bounds [regsub {Bounds : [^\n]+} $text {}] \
    inverted_bounds [string map {{1384.690, 699.500} {1384.760, 699.500}} $text] \
    nonfinite_bounds [string map {{1384.690, 699.500} {NaN, 699.500}} $text] \
    trailing_record "$text\nUNKNOWN record\n" \
    conflicting_clean "$text\nNo DRC violations were found.\n"] {
    require [expr {$broken ne $text}] ${label}_control_changed
    rejected {tri_oracle_memory_resized_cell_geometry_pairs $broken} $label
}
set bad_classes $classes
dict set bad_classes [lindex $names 0] is_clock true
rejected {tri_oracle_memory_resized_cell_data_targets $pairs $bad_classes $cells} clock_counterpart
dict set bad_classes [lindex $names 0] is_clock unknown
rejected {tri_oracle_memory_resized_cell_data_targets $pairs $bad_classes $cells} unknown_clock_class
set bad_classes $classes
dict unset bad_classes [lindex $names 0]
rejected {tri_oracle_memory_resized_cell_data_targets $pairs $bad_classes $cells} missing_native_net
rejected {tri_oracle_memory_resized_cell_data_targets $pairs $classes [lrange $cells 1 end]} unrelated_cell
set clean "# Design: tri_oracle_memory_feedforward_core\nNo DRC violations were found.\n"
require [expr {[llength [tri_oracle_memory_resized_cell_geometry_pairs $clean]] == 0}] clean_native_form
puts "RESIZED_CELL_GEOMETRY_POLICY_PASS $checks"
