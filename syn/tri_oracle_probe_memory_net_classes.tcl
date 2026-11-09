# Read-only complete classification before/after native timing-clock propagation.
source syn/tri_oracle_memory_physical_config.tcl
set tag postroute_probe_native_net_classes
if {$::env(TRI_ORACLE_PHYSICAL_STAGE) ne $tag} {error "Unexpected native classification probe"}
foreach suffix {before.tsv after.tsv setup.rpt} {
    if {![catch {file lstat $out/${tag}_$suffix ignored}]} {error "Refusing existing classification output"}
}
set candidates $out/postroute_memory_forced_routes_native_classification.tsv
if {[lindex [exec sha256sum $candidates] 0] ne {31dceac8f0e07f052f159ff73603c0175c86ed4e1dea8f88b973c02fcdbf8b2a}} {
    error "Complete candidate inventory changed"
}
set channel [open $candidates r]
try {set lines [split [string trimright [read $channel] \n] \n]} finally {close $channel}
if {[lindex $lines 0] ne "net\tis_clock\tis_power\tis_ground" || [llength $lines] != 235} {
    error "Incomplete native classification inventory"
}
set names {}
foreach line [lrange $lines 1 end] {lappend names [lindex [split $line \t] 0]}
set_multi_cpu_usage -local_cpu 20
read_db $out/postroute_slot_selected_routes_03.db
tri_oracle_require_memory_design
proc tri_oracle_probe_net_classes {names destination} {
    set channel [open $destination w]
    try {
        puts $channel "net\tuse\tis_clock\tis_power\tis_ground\twires\tconnections"
        foreach name $names {
            set net [get_db nets $name]
            if {[llength $net] != 1 || [get_db $net .name] ne $name} {error "Missing exact classification net"}
            puts $channel "$name\t[get_db $net .use]\t[get_db $net .is_clock]\t[get_db $net .is_power]\t[get_db $net .is_ground]\t[llength [get_db $net .wires]]\t[get_db $net .num_connections]"
        }
    } finally {close $channel}
}
tri_oracle_probe_net_classes $names $out/${tag}_before.tsv
source syn/tri_oracle_memory_postroute_settings.tcl
set_db timing_analysis_check_type setup
report_timing -view setup_slow > $out/${tag}_setup.rpt
tri_oracle_probe_net_classes $names $out/${tag}_after.tsv
puts "TRI_ORACLE_MEMORY_NET_CLASS_PROBE_FINISHED"
exit
