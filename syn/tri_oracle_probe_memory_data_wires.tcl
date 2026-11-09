# Fresh-process physical edit diagnostic; never save a modified database.
source syn/tri_oracle_memory_physical_config.tcl
source syn/tri_oracle_memory_wire_scope.tcl
source syn/tri_oracle_signal_repair_targets.tcl
set tag postroute_probe_selected_wire_objects_02
if {$::env(TRI_ORACLE_PHYSICAL_STAGE) ne $tag} {error "Unexpected selected-wire probe"}
set report $out/${tag}.rpt
if {![catch {file lstat $report ignored}]} {error "Refusing existing selected-wire probe"}
set targets $out/postroute_memory_forced_routes_targets.tsv
if {[lindex [exec sha256sum $targets] 0] ne {ed4aa4b9818a132b71b9bb32bf9f01e21f424080ded8735fae9f2341b1e7043a}} {
    error "Exact failed-attempt target inventory changed"
}
set channel [open $targets r]
try {set lines [split [string trimright [read $channel] \n] \n]} finally {close $channel}
if {[lindex $lines 0] ne "net\tgeometry\tsignal_integrity\twires_before\tlogical_connections" ||
    [llength $lines] != 233} {error "Incomplete selected-wire probe targets"}
set_multi_cpu_usage -local_cpu 20
read_db $out/postroute_slot_selected_routes_03.db
tri_oracle_require_memory_design
proc tri_oracle_probe_wire_names {objects} {
    if {[llength $objects] == 0} {return {}}
    return [get_db $objects .name]
}
proc tri_oracle_probe_wire_logical {net} {
    set ports [lsort -unique [concat [get_db $net .driver_ports] [get_db $net .load_ports]]]
    return [tri_oracle_memory_wire_inventory [get_db $net .num_connections] \
        [tri_oracle_probe_wire_names [get_db $net .pins]] [tri_oracle_probe_wire_names $ports]]
}
set total 0
set count 0
set channel [open $report w]
try {
    puts $channel "net\tuse\twires_before\twires_after\tlogical_connections"
    foreach line [lrange $lines 1 end] {
        set fields [split $line \t]
        if {[llength $fields] != 5} {error "Malformed probe target row"}
        lassign $fields name geometry si expected_wires expected_connections
        set net [get_db nets $name]
        if {[llength $net] != 1 || [get_db $net .name] ne $name} {error "Missing exact probe net"}
        tri_oracle_route_require_data_net $name [get_db $net .is_clock] [get_db $net .is_power] [get_db $net .is_ground]
        tri_oracle_memory_wire_data_use [get_db $net .use] [get_db $net .is_clock] [get_db $net .is_power] [get_db $net .is_ground]
        set before [tri_oracle_probe_wire_logical $net]
        set wires [get_db $net .wires]
        if {[llength $wires] != $expected_wires || [lindex $before 0] != $expected_connections} {
            error "Probe input differs from exact failed-attempt snapshot"
        }
        deselect_obj -all
        foreach wire $wires {select_obj $wire}
        delete_routes -selected -type regular
        set remaining [llength [get_db $net .wires]]
        incr total [tri_oracle_memory_wire_deletion $name $before [tri_oracle_probe_wire_logical $net] \
            [llength $wires] $remaining]
        incr count
        puts $channel "$name\t[get_db $net .use]\t[llength $wires]\t$remaining\t[lindex $before 0]"
    }
    tri_oracle_memory_wire_scope_counts $count 232 $total
    if {$total != 16134} {error "Incomplete exact physical wire coverage"}
    puts $channel "TOTAL_NETS\t$count"
    puts $channel "TOTAL_REMOVED_WIRES\t$total"
} finally {close $channel}
deselect_obj -all
puts "TRI_ORACLE_MEMORY_SELECTED_WIRE_PROBE_PASS $count $total"
puts "TRI_ORACLE_MEMORY_SELECTED_WIRE_PROBE_FINISHED"
exit
