source syn/tri_oracle_point272.tcl
set failures 0
set cases 0
proc point_case {label raw expected} {
    global failures cases
    incr cases
    if {[catch {tri272_point $raw} got] || [llength $got]!=2 || ![string is double -strict [lindex $got 0]] || ![string is double -strict [lindex $got 1]] || [lindex $got 0]!=[lindex $expected 0] || [lindex $got 1]!=[lindex $expected 1]} {puts "FAIL $label";incr failures}
}
proc bad_point {label raw} {
    global failures cases
    incr cases
    if {![catch {tri272_point $raw}]} {puts "FAIL $label accepted invalid point";incr failures}
}
point_case nested_native_point {{314.4 2958.0}} {314.4 2958.0}
point_case flat_point {3.5 -2.25} {3.5 -2.25}
point_case scientific_point {{1e2 2.5e-1}} {100.0 0.25}
bad_point empty {}
bad_point scalar {1}
bad_point extra_coordinates {1 2 3}
bad_point multiple_points {{1 2} {3 4}}
bad_point nonnumeric {{foo 2}}
bad_point infinite {{Inf 0}}
bad_point overflow {{1e999 0}}
bad_point nan {{NaN 0}}
set stream [open records/controller272_driver_coordinates.tsv r]
gets $stream header
if {$header ne "tree\tlocation"} {error WRONG_NATIVE_POINT_HEADER}
set native_count 0
while {[gets $stream line]>=0} {
    lassign [split $line "\t"] id raw
    # This fixture records one point per cell, as a one-element native list.
    if {[llength $raw]!=1 || [llength [lindex $raw 0]]!=2} {error UNEXPECTED_NATIVE_POINT_SCHEMA}
    point_case native_$id $raw [lindex $raw 0]
    incr native_count
}
close $stream
if {$native_count!=61} {error INCOMPLETE_NATIVE_POINT_REPLAY}
if {$failures} {puts "FAILED $failures/$cases";exit 1}
puts "POINT_TESTS_PASS cases=$cases native=$native_count"
