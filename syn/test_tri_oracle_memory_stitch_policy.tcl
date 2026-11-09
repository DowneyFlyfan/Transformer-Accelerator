set checks 0
proc require {condition message} {if {![uplevel 1 [list expr $condition]]} {error $message};incr ::checks}
proc rejects {script} {require {[catch {uplevel 1 $script}]} "Incomplete/incorrect stitch evidence admitted"}
try {
    set policy [lindex $argv 0]
    if {$policy eq {}} {set policy syn/tri_oracle_memory_stitch_policy.tcl}
    source $policy
    set file [open .cache/physical/pnr/tri_oracle_memory_feedforward_core/postroute_memory_driver_resize_slots_02.router.rpt r]
    try {set native [read $file]} finally {close $file}
    # This is a parser fixture derived from the real completed command shape;
    # changed declarations do not assert that a geometric pass already ran.
    set fixture [string map {
        {TRI_ORACLE_MEMORY_DRIVER_EXACT_SLOTS_MODE true true true true} {TRI_ORACLE_MEMORY_GEOSTITCH_MODE false false true true}
        {TRI_ORACLE_MEMORY_DRIVER_EXACT_SLOTS_CLOCK_MODE true false} {TRI_ORACLE_MEMORY_GEOSTITCH_CLOCK_MODE true false}
    } $native]
    regsub -all -line {^(route_with_(?:timing|si)_driven[ \t]+)true[ \t]*$} $fixture {\1false} fixture
    set result [tri_oracle_memory_stitch_evidence $fixture]
    require {[dict get $result geometry_violations] == 17} "Intermediate DRC count lost"
    require {![dict get $result timing_driven] && ![dict get $result physical_closure_passed]} "False timed/closure claim"
    rejects [list tri_oracle_memory_stitch_evidence $native]
    foreach bad [list {} \
        [string map {{GEOSTITCH_MODE false false true true} {GEOSTITCH_MODE true false true true}} $fixture] \
        [string map {{GEOSTITCH_CLOCK_MODE true false} {GEOSTITCH_CLOCK_MODE false false}} $fixture] \
        [string map {{#Total number of DRC violations = 17} {#Total number of DRC violations = 1001}} $fixture] \
        [string map {{#Total number of DRC violations = 17} {#Total number of DRC violations = -1}} $fixture] \
        [string map {{#Total number of fails = 0} {#Total number of fails = 1}} $fixture] \
        [string map {{#Complete route_global_detail on} {#Incomplete route_global_detail on}} $fixture] \
        [string map {{#  Entire Command} {#  Missing Command}} $fixture] \
        "$fixture\n**ERROR: native failure\n" \
        "$fixture\nroute_with_timing_driven true\n" \
        "$fixture\nTRI_ORACLE_MEMORY_GEOSTITCH_MODE false false true true\n"] {
        rejects [list tri_oracle_memory_stitch_evidence $bad]
    }
    set file [open .cache/physical/pnr/tri_oracle_memory_feedforward_core/postroute_memory_wire_spread.connectivity.rpt r]
    try {set connected [read $file]} finally {close $file}
    require {[tri_oracle_memory_connected_evidence $connected] == 1} "Actual clean connectivity rejected"
    foreach bad [list {} \
        [string map {{Found no problems or warnings.} {Found 1 open.}} $connected] \
        [string map {{End Summary} {Missing Summary}} $connected] \
        "$connected\n$connected" "$connected\n**WARN: unresolved connectivity\n" \
        "$connected\n#WARNING: unresolved connectivity\n" "$connected\n#ERROR: unresolved open\n" \
        "$connected\nWARN: unresolved connectivity\n" \
        [string map {tri_oracle_memory_feedforward_core wrong_top} $connected]] {
        rejects [list tri_oracle_memory_connected_evidence $bad]
    }
    puts "MEMORY_GEOSTITCH_POLICY_PASS checks=$checks"
} on error {message options} {puts stderr $message;exit 1}
