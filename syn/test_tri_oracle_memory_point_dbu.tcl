set checks 0
proc require {condition message} {
    if {![uplevel 1 [list expr $condition]]} {error $message}
    incr ::checks
}
try {
    set policy [lindex $argv 0]
    if {$policy eq {}} {set policy syn/tri_oracle_memory_point_dbu.tcl}
    source $policy
    foreach {point expected} {
        {103.085 630.4} {206170 1260800}
        {{103.085 630.4}} {206170 1260800}
        {-0.25 0.125} {-500 250}
        {{226.565 374.8}} {453130 749600}
        {{193.525 756.4}} {387050 1512800}
    } {
        require {[tri_oracle_memory_point_dbu $point] eq $expected} "Wrong native point conversion"
    }
    foreach point {{} {1} {{1}} {{{1 2}}} {1 2 3} {{1 2} {3 4}} \
        {NaN 1} {Inf 1} {1 -Inf} {1 invalid} {1000000 1}} {
        require {[catch {tri_oracle_memory_point_dbu $point}]} "Malformed or nonfinite point accepted"
    }
    set channel [open .cache/physical/pnr/tri_oracle_memory_feedforward_core/native_endpoint_point_values.rpt r]
    try {set lines [split [string trimright [read $channel] \n] \n]} finally {close $channel}
    set expected {{206170 1260800} {453130 749600} {387050 1512800}}
    require {[llength $lines] == 3} "Native point probe is incomplete"
    foreach row $lines want $expected {
        require {[tri_oracle_memory_point_dbu [dict get $row point]] eq $want} \
            "Installed native point output was not normalized correctly"
    }
    puts "MEMORY_NATIVE_POINT_DBU_PASS checks=$checks"
} on error {message options} {
    puts stderr $message
    exit 1
}
