# Catch changes to original cells/delays and unexpected logic or clock additions.
set checks 0
proc require {condition message} {
    if {![uplevel 1 [list expr $condition]]} {error $message}
    incr ::checks
}
proc rejects {script} {
    require {[catch {uplevel 1 $script}]} "Unsafe route scope admitted by [lindex $script 0]"
}
try {
    set policy [lindex $argv 0]
    if {$policy eq {}} {set policy syn/tri_oracle_memory_route_scope.tcl}
    source $policy
    # Complete native inventory:899851 "none",6568 "true"; not a Boolean.
    set original {DFMQD1BWP12T40P140 {20250 20000} r0 placed unset placed none}
    set delay {DEL100D1BWP12T40P140 {22490 22400} mx placed unset placed true}
    require {[tri_oracle_memory_route_original_row register $original $original] == 1} "Original row rejected"
    require {[tri_oracle_memory_route_original_row delay $delay $delay] == 1} "Protected delay rejected"
    foreach {index replacement} {0 DFMQD2BWP12T40P140 1 {20530 20000} 2 mx \
        3 fixed 4 fixed 5 fixed 6 true} {
        set changed $original
        lset changed $index $replacement
        rejects [list tri_oracle_memory_route_original_row register $original $changed]
    }
    set changed $delay
    lset changed 6 none
    rejects [list tri_oracle_memory_route_original_row delay $delay $changed]
    set antenna {ANTENNABWP12T40P140 {22490 20000} r0 placed unset placed none}
    require {[tri_oracle_memory_route_added_row diode $antenna] == 1} "Native antenna diode rejected"
    foreach status {fixed soft_fixed} {
        set row $antenna
        lset row 3 $status
        lset row 5 $status
        require {[tri_oracle_memory_route_added_row diode $row] == 1} "Placed/fixed diode rejected"
    }
    foreach {index replacement} {0 BUFFD1BWP12T40P140 1 {NaN 20000} 2 r90 \
        3 unplaced 4 fixed 5 unplaced 6 invalid} {
        set changed $antenna
        lset changed $index $replacement
        rejects [list tri_oracle_memory_route_added_row unknown $changed]
    }
    foreach row {{} {CELL {1 2}} {CELL {1 2 3} r0 placed unset placed false} \
        {CELL {{1 2}} r0 placed unset placed none} \
        {CELL {1 2} r0 placed unset placed false}} {
        rejects [list tri_oracle_memory_route_original_row malformed $row $row]
    }
    foreach counts {{1 1 0} {906419 906419 1} {906419 906419 8}} {
        tri_oracle_memory_route_scope_counts {*}$counts
        incr checks
    }
    foreach counts {{0 1 0} {1 2 0} {2 1 0} {0 0 0} {1 1 -1} {1 1 9} \
        {1 1 1.5} {1.0 1 0} {1000001 1000001 0}} {
        rejects [list tri_oracle_memory_route_scope_counts {*}$counts]
    }
    set trace "TRI_ORACLE_MEMORY_SELECTED_ROUTE_MODE true true true\n#Total number of DRC violations = 39\n#Total number of process antenna violations = 2\n#Total number of net violated process antenna rule = 1\n#route_detail Statistics:\n#Total number of fails = 0\n#Complete route_detail on Sat Nov 7 12:24:07 2026\n#  Entire Command         | 00:11:15|     00:02:05|         5.4|\n"
    set evidence [tri_oracle_memory_selected_route_evidence $trace]
    require {[dict get $evidence geometry_violations] == 39} "Routing diagnostic count was lost"
    require {![dict get $evidence physical_closure_passed]} "Router completion became closure"
    foreach bad [list \
        [string map {{MODE true true true} {MODE false true true}} $trace] \
        [string map {{#Total number of DRC violations = 39} {}} $trace] \
        [string range $trace 0 [expr {[string first {#route_detail Statistics:} $trace]-1}]] \
        "$trace**ERROR native failure\n" \
        "$trace#WARNING No slack were found\n" \
        [string map {{#Total number of fails = 0} {#Total number of fails = 1}} $trace] \
        [string map {{#Complete route_detail on Sat Nov 7 12:24:07 2026} {}} $trace]] {
        rejects [list tri_oracle_memory_selected_route_evidence $bad]
    }
    # Use the complete real233-net native run, not just a synthetic heading.
    set channel [open .cache/physical/pnr/tri_oracle_memory_feedforward_core/postroute_slot_selected_routes_02_router.rpt r]
    try {set native [tri_oracle_memory_selected_route_evidence [read $channel]]} finally {close $channel}
    require {[dict get $native geometry_violations] == 0} "Actual final router geometry count lost"
    require {[dict get $native antenna_violations] == 0} "Actual final router antenna count lost"
    require {![dict get $native physical_closure_passed]} "Actual router completion became closure"
    puts "MEMORY_SELECTED_ROUTE_SCOPE_PASS checks=$checks"
} on error {message options} {
    puts stderr $message
    exit 1
}
