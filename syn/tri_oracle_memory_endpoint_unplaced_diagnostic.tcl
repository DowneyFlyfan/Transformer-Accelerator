# This is intentionally an UNPLACED producer, not a repaired/routed checkpoint.
# Native IMPSP-2020 documents missing power/ground connections as one possible
# source of legalization failure. Measure before and after connection first.
if {$tag ne {postroute_measured_endpoint_unplaced} || [llength $results] != 6568} {
    error "Complete admitted insertion is required for the unplaced diagnostic"
}
proc tri_oracle_memory_endpoint_pg_snapshot {label results channel} {
    set counts [dict create]
    foreach rail {VDD VSS} {
        dict set counts $rail expected 0
        dict set counts $rail missing 0
        dict set counts $rail wrong 0
    }
    foreach result $results {
        set name [lindex $result 1]
        set inst [get_db insts $name]
        if {[llength $inst] != 1 || [get_db $inst .name] ne $name ||
            [get_db $inst .base_cell.name] ne {DEL100D1BWP12T40P140}} {
            error "Diagnostic inserted-cell identity changed"
        }
        set pins [get_db $inst .pg_pins]
        if {[llength $pins] != 2} {error "Unexpected power-pin count for $name"}
        set rails {}
        foreach pin $pins {
            set rail [get_db $pin .base_name]
            if {$rail ni {VDD VSS} || $rail in $rails} {error "Unexpected power-pin identity"}
            lappend rails $rail
            set net [get_db $pin .net]
            if {[llength $net] > 1} {error "Ambiguous native power connection"}
            set net_name {}
            if {[llength $net] == 1} {set net_name [get_db $net .name]}
            if {$net_name eq {}} {set kind missing} elseif {$net_name eq $rail} {
                set kind expected
            } else {set kind wrong}
            dict set counts $rail $kind [expr {[dict get $counts $rail $kind]+1}]
            puts $channel [join [list $label $name $rail $net_name $kind] \t]
        }
    }
    return $counts
}
set channel [open $out/${tag}_pg_pins.tsv w]
puts $channel "stage\tinstance\tbase_pin\tnet\tclassification"
set before [tri_oracle_memory_endpoint_pg_snapshot before $results $channel]
connect_global_net VDD -type pg_pin -pin_base_name VDD -all
connect_global_net VSS -type pg_pin -pin_base_name VSS -all
set after [tri_oracle_memory_endpoint_pg_snapshot after $results $channel]
close $channel
set channel [open $out/${tag}_placement_settings.rpt w]
foreach attribute {place_detail_preroute_as_obs place_detail_check_route \
    place_detail_eco_max_distance place_detail_eco_priority_insts} {
    puts $channel "$attribute: [get_db $attribute]"
}
puts $channel "inserted_cell_pg_before: $before"
puts $channel "inserted_cell_pg_after: $after"
set same_cell [get_db insts -if {.base_cell.name == DEL100D1BWP12T40P140}]
puts $channel "existing_delay_cells_before_this_insertion: [expr {[llength $same_cell]-6568}]"
close $channel
foreach rail {VDD VSS} {
    if {[dict get $after $rail expected] != 6568 || [dict get $after $rail missing] != 0 ||
        [dict get $after $rail wrong] != 0} {error "Power connection remains incomplete at $rail"}
}
puts "TRI_ORACLE_MEMORY_ENDPOINT_PG_BEFORE $before"
puts "TRI_ORACLE_MEMORY_ENDPOINT_PG_AFTER $after"
# Do not extract or call any placer/router on an intentionally unplaced design.
write_db $destination
puts "TRI_ORACLE_MEMORY_ENDPOINT_UNPLACED_DIAGNOSTIC_FINISHED"
exit
