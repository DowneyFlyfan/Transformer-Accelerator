set checks 0
proc require {condition message} {
    if {![uplevel 1 [list expr $condition]]} {error $message}
    incr ::checks
}
proc rejects {script} {
    require {[catch {uplevel 1 $script}]} "Unsafe route target admitted by [lindex $script 0]"
}
try {
    set policy [lindex $argv 0]
    if {$policy eq {}} {set policy syn/tri_oracle_memory_route_pair_policy.tcl}
    source $policy
    set cut {CUTSPACING: ( Cut EolSpacing ) Regular Wire of Net core/data[0] & Regular Wire of Net core/CTS_9  ( VIA4 )}
    set bounds {Bounds : ( 708.250, 1109.425 ) ( 708.310, 1109.475 )}
    set report "$cut\n$bounds\n  Total Violations : 1 Viols.\n"
    set pairs [tri_oracle_memory_route_drc_pairs $report]
    require {[llength $pairs] == 1} "Measured via4 cut pair was dropped"
    require {[dict get [lindex $pairs 0] first] eq {core/data[0]}} "Indexed data net identity lost"
    require {[dict get [lindex $pairs 0] second] eq {core/CTS_9}} "Clock counterpart identity lost"
    require {[dict get [lindex $pairs 0] layer] eq {VIA4}} "Reported layer lost"
    set flags [dict create {core/data[0]} {is_clock false is_power false is_ground false} \
        core/CTS_9 {is_clock true is_power false is_ground false}]
    require {[tri_oracle_memory_route_data_targets $pairs $flags] eq [list {core/data[0]}]} \
        "Clock net selected when ordinary data counterpart is available"
    set all_data $flags
    dict set all_data core/CTS_9 is_clock false
    require {[tri_oracle_memory_route_data_targets $pairs $all_data] eq \
        [list core/CTS_9 {core/data[0]}]} "Ordinary data counterpart was lost"
    foreach field {is_clock is_power is_ground} {
        set bad $flags
        dict set bad {core/data[0]} $field true
        rejects [list tri_oracle_memory_route_data_targets $pairs $bad]
    }
    set bad $flags
    dict set bad core/CTS_9 is_clock invalid
    rejects [list tri_oracle_memory_route_data_targets $pairs $bad]
    rejects [list tri_oracle_memory_route_data_targets $pairs [dict remove $flags core/CTS_9]]
    foreach bad [list {} "$cut\n$bounds" "$cut\n  Total Violations : 1 Viols.\n" \
        [string map {VIA4 VIA5} $report] \
        [string map {{1 Viols.} {2 Viols.}} $report] \
        [string map {{708.310, 1109.475} {708.200, 1109.475}} $report] \
        "$report  Total Violations : 1 Viols.\n" \
        "SPACING: another rule\n$bounds\n  Total Violations : 1 Viols.\n"] {
        rejects [list tri_oracle_memory_route_drc_pairs $bad]
    }
    require {[llength [tri_oracle_memory_route_drc_pairs {No DRC violations were found}]] == 0} \
        "Native clean geometry result was rejected"
    set channel [open .cache/physical/pnr/tri_oracle_memory_feedforward_core/qualification_postroute_qualify_before_endpoint_repair/route_drc.rpt r]
    try {set actual [tri_oracle_memory_route_drc_pairs [read $channel]]} finally {close $channel}
    require {[llength $actual] == 96} "Complete actual cut-spacing inventory was truncated"
    set counts [dict create]
    foreach pair $actual {dict incr counts [dict get $pair layer]}
    foreach {layer count} {VIA2 72 VIA3 23 VIA4 1} {
        require {[dict get $counts $layer] == $count} "Actual via layer coverage lost"
    }
    puts "MEMORY_ROUTE_PAIR_POLICY_PASS checks=$checks pairs=[llength $actual]"
} on error {message options} {
    puts stderr $message
    exit 1
}
