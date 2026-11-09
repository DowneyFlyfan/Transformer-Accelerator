# Distinguish unused database nets from active signal nets lacking routing.
source syn/tri_oracle_physical_config.tcl
set_multi_cpu_usage -local_cpu 18
read_db $out/routed.db
set file [open $out/unrouted_net_audit.tsv w]
puts $file "net\tconnections\tpower_or_ground"
set empty 0
set single 0
set pg 0
set active_missing 0
set routed 0
foreach net [get_db nets] {
    set wires [get_db $net .wires]
    if {[llength $wires] != 0} {incr routed;continue}
    set name [get_db $net .name]
    set connections [get_db $net .num_connections]
    set power [expr {[get_db $net .is_power] || [get_db $net .is_ground]}]
    puts $file "$name\t$connections\t$power"
    if {$power} {incr pg} elseif {$connections == 0} {
        incr empty
    } elseif {$connections == 1} {
        incr single
    } else {
        incr active_missing
    }
}
close $file
set file [open $out/extraction_audit.rpt w]
puts $file "Routed nets: $routed"
puts $file "Zero-connection signal nets without routing: $empty"
puts $file "Single-connection signal nets without routing: $single"
puts $file "Power/ground nets excluded from signal extraction: $pg"
puts $file "Signal nets with multiple connections but no wire shapes: $active_missing"
close $file
if {$active_missing == 0} {
    puts "TRI_ORACLE_ACTIVE_NET_ROUTING_AUDIT_PASS"
} else {
    puts "TRI_ORACLE_ACTIVE_NET_ROUTING_AUDIT_REQUIRES_REVIEW $active_missing"
}
exit
