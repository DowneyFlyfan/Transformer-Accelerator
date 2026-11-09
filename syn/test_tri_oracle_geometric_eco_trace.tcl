set root .cache/geometric_eco_trace_test_[pid]
if {[file exists $root]} {error "Refusing existing test directory"}
file mkdir $root
set status [catch {
    source syn/tri_oracle_router_timing_interface.tcl
    set good "TRI_ORACLE_LOCAL_ECO_MODE false false\nroute_with_timing_driven false\nroute_with_si_driven false\n#Total number of DRC violations = 0\n#Total number of process antenna violations = 0\n#Total number of net violated process antenna rule = 0\n#route_detail Statistics:\n#  Entire Command         | 00:11:15|     00:02:05|         5.4|\n"
    set report $root/router.rpt
    set channel [open $report w];puts -nonewline $channel $good;close $channel
    set result [tri_oracle_require_geometric_eco_trace $report]
    if {[dict get $result geometry_violations] != 0 || [dict get $result timing_driven] ne {false}} {error "Wrong geometric ECO evidence"}
    foreach bad [list \
        [string map {{route_with_timing_driven false} {route_with_timing_driven true}} $good] \
        [string map {{DRC violations = 0} {DRC violations = 1}} $good] \
        [string map {{process antenna violations = 0} {process antenna violations = 1}} $good] \
        [string range $good 0 [expr {[string first {#route_detail Statistics:} $good]-1}]] \
        "$good#WARNING (NRIF-78) ECO and timing-driven combination\n"] {
        set channel [open $report w];puts -nonewline $channel $bad;close $channel
        if {![catch {tri_oracle_require_geometric_eco_trace $report}]} {error "Unsafe or incomplete geometric trace admitted"}
    }
    if {![catch {tri_oracle_require_geometric_eco_trace .cache/physical/pnr/tri_oracle_feedforward_core/postroute_short_input_hold_router.rpt}]} {error "Actual timing-driven ECO trace admitted as geometric"}
    puts "PASS: geometric ECO mode, complete clean geometry/antenna results and native completion required"
} message options]
file delete -force $root
if {$status} {puts stderr $message;exit 1}
