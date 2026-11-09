# Read every measured endpoint's actual cell and data-net type before extending
# the first repair's deliberately narrow model whitelist. No physical mutation.
source syn/tri_oracle_memory_physical_config.tcl
source syn/tri_oracle_memory_endpoint_policy.tcl
source syn/tri_oracle_signal_repair_targets.tcl
set inventory $out/postroute_endpoint_margin_probe.tsv
if {[lindex [exec sha256sum $inventory] 0] ne \
    "9a3d75a3897239710f0797a17b6fca9d2b4d03623c4587e346eddd284cd03681"} {
    error "Qualified endpoint inventory changed"
}
set channel [open $inventory r]
try {set measured [tri_oracle_memory_endpoint_inventory [read $channel]]} finally {close $channel}
set destination $out/postroute_endpoint_cell_probe.tsv
if {![catch {file lstat $destination ignored}]} {error "Refusing existing native cell inventory"}
set_multi_cpu_usage -local_cpu 20
read_db $out/routed.db
tri_oracle_require_memory_design
source syn/tri_oracle_memory_postroute_settings.tcl
set_db delaycal_enable_si true
set_db si_delay_enable_report true
set paths [report_timing -early -view hold_fast -collection \
    -max_paths 10000 -nworst 1 -max_slack 0]
if {[sizeof_collection $paths] != [dict size $measured]} {error "Negative hold inventory changed"}
set rows [dict create]
foreach_in_collection path $paths {
    set launch [get_object_name [get_property $path launching_point]]
    set capture [get_object_name [get_property $path capturing_point]]
    set hold [get_property $path slack]
    if {![dict exists $measured $capture] || [dict exists $rows $capture]} {
        error "Unexpected/repeated measured endpoint: $capture"
    }
    lassign [dict get $measured $capture] expected_launch expected_hold slow typical kind
    if {$launch ne $expected_launch || abs($hold-$expected_hold) > 0.000001 ||
        [tri_oracle_memory_endpoint_kind $launch $capture $hold] ne $kind} {
        error "Restored timing identity differs from measured producer: $capture"
    }
    set pin [get_db [get_property $path capturing_point]]
    if {[llength $pin] != 1 || [get_db $pin .name] ne $capture ||
        [get_db $pin .direction] ne {in}} {error "Expected exact native input pin: $capture"}
    set inst [get_db $pin .inst]
    set expected_inst [string range $capture 0 [expr {[string last / $capture]-1}]]
    if {[llength $inst] != 1 || [get_db $inst .name] ne $expected_inst} {
        error "Native instance identity differs: $capture"
    }
    set net [get_db $pin .net]
    if {[llength $net] != 1} {error "Expected one connected endpoint net: $capture"}
    tri_oracle_route_require_data_net [get_db $net .name] \
        [get_db $net .is_clock] [get_db $net .is_power] [get_db $net .is_ground]
    dict set rows $capture [list $launch $capture $hold $kind [get_db $inst .base_cell.name] \
        [get_db $net .name] [get_db $pin .direction]]
}
if {[dict size $rows] != [dict size $measured]} {error "Incomplete endpoint cell inventory"}
set channel [open $destination w]
puts $channel "launch\tendpoint\thold_fast_ns\tkind\tbase_cell\tnet\tdirection"
foreach capture [lsort [dict keys $rows]] {puts $channel [join [dict get $rows $capture] \t]}
close $channel
puts "TRI_ORACLE_MEMORY_ENDPOINT_CELLS_OBSERVED [dict size $rows]"
puts "TRI_ORACLE_MEMORY_ENDPOINT_CELLS_FINISHED"
exit
