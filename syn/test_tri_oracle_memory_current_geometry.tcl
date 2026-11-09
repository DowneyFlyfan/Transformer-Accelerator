set checks 0
proc require {condition message} {
    if {![uplevel 1 [list expr $condition]]} {error $message}
    incr ::checks
}
proc rejects {script} {require {[catch {uplevel 1 $script}]} "Unsafe geometry report admitted"}
try {
    set policy [lindex $argv 0]
    if {$policy eq {}} {set policy syn/tri_oracle_memory_current_geometry.tcl}
    source $policy
    set cut {CUTSPACING: ( Cut EolSpacing ) Regular Wire of Net data[0] & Regular Wire of Net clock_1  ( VIA1 )}
    set metal {EndOfLine: ( EndOfLine Spacing ) Regular Wire of Net a & Regular Wire of Net b  ( M2 )}
    set bounds {Bounds : ( 1.000, 2.000 ) ( 1.050, 2.050 )}
    set report "$cut\n$bounds\n$metal\n$bounds\nTotal Violations : 2 Viols.\n"
    set pairs [tri_oracle_memory_current_geometry_pairs $report]
    require {[llength $pairs] == 2} "Mixed native rule inventory lost"
    require {[dict get [lindex $pairs 0] layer] eq {VIA1}} "VIA1 lost"
    require {[dict get [lindex $pairs 0] first] eq {data[0]}} "Indexed net identity lost"
    require {[dict get [lindex $pairs 1] kind] eq {EndOfLine}} "Metal rule identity lost"
    require {[dict get [lindex $pairs 1] layer] eq {M2}} "Metal layer lost"
    foreach bad [list {} "$cut\n$bounds" "$cut\nTotal Violations : 1 Viols.\n" \
        [string map {VIA1 VIA5} $report] [string map {{( M2 )} {( M3 )}} $report] \
        [string map {{2 Viols.} {1 Viols.}} $report] \
        [string map {{1.050, 2.050} {0.950, 2.050}} $report] \
        "$report$cut\n$bounds\n" "$report Total Violations : 2 Viols.\n" \
        "$report unsupported native rule\n"] {
        rejects [list tri_oracle_memory_current_geometry_pairs $bad]
    }
    require {[llength [tri_oracle_memory_current_geometry_pairs {No DRC violations were found}]] == 0} "Clean report rejected"
    set root .cache/physical/pnr/tri_oracle_memory_feedforward_core
    foreach {file expected} {postroute_slot_selected_routes_03_drc_after.rpt 39 postroute_memory_wire_spread.drc.rpt 29} {
        set f [open $root/$file r]
        try {set actual [tri_oracle_memory_current_geometry_pairs [read $f]]} finally {close $f}
        require {[llength $actual] == $expected} "Actual native geometry coverage incomplete"
    }
    set kinds [dict create]
    set layers [dict create]
    foreach pair $actual {dict incr kinds [dict get $pair kind];dict incr layers [dict get $pair layer]}
    foreach {key value} {CUTSPACING 26 EndOfLine 3} {
        require {[dict get $kinds $key] == $value} "Native kind total lost"
    }
    foreach {key value} {VIA1 1 VIA2 24 VIA4 1 M2 3} {
        require {[dict get $layers $key] == $value} "Native layer total lost"
    }
    puts "MEMORY_CURRENT_GEOMETRY_PASS checks=$checks"
} on error {message options} {puts stderr $message;exit 1}
