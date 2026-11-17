source [file join [file dirname [info script]] tri_oracle_place_detail_argument.tcl]
set names [list chip/plain {chip/cores[0]/row[17]} {chip/values[1].unit/reg[3]}]
if {[llength $argv] == 1} {
    set file [open [lindex $argv 0] r]
    set names [split [string trim [read $file]] "\n"]
    close $file
} elseif {[llength $argv] != 0} {error "Expected at most one scope file"}
set legacy [regexp -all -inline {\S+} $names]
set actual [regexp -all -inline {\S+} [tri_oracle_place_detail_argument $names]]
if {[llength $actual] != [llength $names]} {error "Changed scope length"}
set legacy_errors 0
foreach wanted $names old $legacy got $actual {
    if {$wanted ne $old} {incr legacy_errors}
    if {$wanted ne $got} {error "Changed instance name: $wanted -> $got"}
}
if {$legacy_errors == 0} {error "Regression control did not exercise indexed names"}
foreach bad [list {} [list {chip/a b}] [list "chip/a\{b"] [list chip/a chip/a]] {
    if {![catch {tri_oracle_place_detail_argument $bad}]} {error "Invalid scope was accepted: $bad"}
}
puts "LEGACY_SCOPE_REJECTIONS_REPRODUCED $legacy_errors"
puts "PLACE_DETAIL_SCOPE_NAMES_VERIFIED [llength $names]"
puts PLACE_DETAIL_SCOPE_ARGUMENT_TEST_PASS
