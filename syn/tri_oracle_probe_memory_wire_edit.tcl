# Diagnostic changes are confined to memory; never save a modified database.
source syn/tri_oracle_memory_physical_config.tcl
set tag postroute_probe_data_wire_edit
if {$::env(TRI_ORACLE_PHYSICAL_STAGE) ne $tag} {error "Unexpected wire-edit probe"}
set report $out/${tag}.rpt
if {![catch {file lstat $report ignored}]} {error "Refusing existing wire probe"}
set_multi_cpu_usage -local_cpu 20
set input $out/postroute_slot_selected_routes_03.db
read_db $input
tri_oracle_require_memory_design
set name {core/cache/memory[284][15]}
set net [get_db nets $name]
if {[llength $net] != 1 || [get_db $net .name] ne $name} {error "Missing exact failing net"}
set channel [open $report w]
try {
    puts $channel "net: $name"
    puts $channel "use: [get_db $net .use]"
    foreach attribute {is_clock is_power is_ground num_connections} {
        puts $channel "$attribute: [get_db $net .$attribute]"
    }
    puts $channel "original_pin_names: [lsort [get_db [get_db $net .pins] .name]]"
    set before [llength [get_db $net .wires]]
    puts $channel "wires_before: $before"
    puts $channel "wire_statuses_before: [get_db [get_db $net .wires] .status]"
    if {[get_db $net .is_clock] || [get_db $net .is_power] || [get_db $net .is_ground] ||
        [get_db $net .use] ni {signal scan tieoff}} {
        puts $channel "physical_edit_skipped: nonordinary_native_use"
    } else {
        delete_routes -nets [list $net] -type regular -use signal
        puts $channel "wires_after_typed_net_regular_signal: [llength [get_db $net .wires]]"
        deselect_obj -all
        foreach wire [get_db $net .wires] {select_obj $wire}
        delete_routes -selected -use signal
        set remaining [llength [get_db $net .wires]]
        puts $channel "wires_after_selected_signal: $remaining"
        set winner selected_signal
        if {$remaining != 0} {
            deselect_obj -all
            foreach wire [get_db $net .wires] {select_obj $wire}
            delete_routes -selected
            puts $channel "wires_after_selected_only: [llength [get_db $net .wires]]"
            set winner selected_only
        }
        # Retest the chosen command on a fresh exact input, including indexes.
        deselect_obj -all
        read_db $input
        tri_oracle_require_memory_design
        set net [get_db nets $name]
        puts $channel "fresh_original_wires: [llength [get_db $net .wires]]"
        set pins [lsort [get_db [get_db $net .pins] .name]]
        foreach wire [get_db $net .wires] {select_obj $wire}
        if {$winner eq {selected_signal}} {delete_routes -selected -use signal} else {delete_routes -selected}
        puts $channel "fresh_selected_method: $winner"
        puts $channel "fresh_remaining_wires: [llength [get_db $net .wires]]"
        puts $channel "fresh_connections_after: [get_db $net .num_connections]"
        puts $channel "fresh_pin_names_unchanged: [expr {$pins eq [lsort [get_db [get_db $net .pins] .name]]}]"
        deselect_obj -all
    }
} finally {close $channel}
puts "TRI_ORACLE_MEMORY_WIRE_EDIT_PROBE_FINISHED"
exit
