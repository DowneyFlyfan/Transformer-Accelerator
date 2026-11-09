set checks 0
proc require {condition message} {
    if {![uplevel 1 [list expr $condition]]} {error $message}
    incr ::checks
}
proc rejects {script} {
    require {[catch {uplevel 1 $script}]} "Unsafe wire edit admitted by [lindex $script 0]"
}
try {
    set policy [lindex $argv 0]
    if {$policy eq {}} {set policy syn/tri_oracle_memory_wire_scope.tcl}
    source $policy
    set signature [tri_oracle_memory_wire_inventory 3 {u/Q v/D} {{out[3]}}]
    require {$signature eq {3 {u/Q v/D} {{out[3]}}}} "Logical identities were lost"
    set reordered [tri_oracle_memory_wire_inventory 3 {v/D u/Q} {{out[3]}}]
    require {$signature eq $reordered} "Native order became a connectivity change"
    require {[tri_oracle_memory_wire_deletion data $signature $reordered 123 0] == 123} "Valid physical-only deletion rejected"
    foreach args [list \
        [list data $signature $signature 0 0] \
        [list data $signature $signature 123 1] \
        [list data $signature $signature -1 0] \
        [list data $signature $signature 123 0.0] \
        [list data $signature [list 3 {u/Q w/D} {{out[3]}}] 123 0] \
        [list data $signature [list 3 {u/Q v/D} {{out[4]}}] 123 0] \
        [list data $signature [list 2 {u/Q v/D} {}] 123 0] \
        [list data {} $signature 123 0]] {
        rejects [list tri_oracle_memory_wire_deletion {*}$args]
    }
    foreach args {{0 {} {}} {1 {u/Q} {}} {3 {u/Q v/D} {}} \
        {3 {u/Q u/Q} {out}} {3 {u/Q v/D} {out out}} {2.0 {u/Q v/D} {}} \
        {2 {{u/Q bad} v/D} {}}} {
        rejects [list tri_oracle_memory_wire_inventory {*}$args]
    }
    tri_oracle_memory_wire_scope_counts 232 232 951
    incr checks
    foreach args {{231 232 951} {233 232 951} {0 0 0} {601 601 951} \
        {232 232 231} {232 232 0} {232 232 951.5}} {
        rejects [list tri_oracle_memory_wire_scope_counts {*}$args]
    }
    require {[tri_oracle_memory_wire_routed data $signature $signature {} 91] == 1} "Preserved routed net rejected"
    set diode [tri_oracle_memory_wire_inventory 4 {u/Q v/D DIODE_2/I} {{out[3]}}]
    require {[tri_oracle_memory_wire_routed data $signature $diode {DIODE_2/I} 92] == 1} "Qualified diode load rejected"
    foreach args [list \
        [list data $signature $signature {} 0] \
        [list data $signature $signature {} 1.0] \
        [list data $signature [list 2 {u/Q} {{out[3]}}] {} 92] \
        [list data $signature [list 3 {u/Q w/D} {{out[3]}}] {} 92] \
        [list data $signature $diode {} 92] \
        [list data $signature $diode {BUFFER/I} 92] \
        [list data $signature [list 4 {u/Q v/D} {{out[3]} new_out}] {} 92]] {
        rejects [list tri_oracle_memory_wire_routed {*}$args]
    }
    require {[tri_oracle_memory_clock_wires clock {fixed routed} {routed fixed}] == 2} "Reordered clock status rejected"
    require {[tri_oracle_memory_clock_wires alias {} {}] == 0} "Empty clock alias rejected"
    foreach args {{clock {fixed fixed} {fixed routed}} {clock {fixed fixed} {fixed}} \
        {clock {invalid} {invalid}}} {
        rejects [list tri_oracle_memory_clock_wires {*}$args]
    }
    foreach use {signal scan} {
        require {[tri_oracle_memory_wire_data_use $use false false false] == 1} "Native signal/scan data type rejected"
    }
    foreach use {clock power ground analog tieoff unknown} {
        rejects [list tri_oracle_memory_wire_data_use $use false false false]
    }
    foreach args {{signal true false false} {scan false true false} \
        {scan false false true} {signal unknown false false}} {
        rejects [list tri_oracle_memory_wire_data_use {*}$args]
    }
    puts "MEMORY_WIRE_SCOPE_PASS checks=$checks"
} on error {message options} {
    puts stderr $message
    exit 1
}
