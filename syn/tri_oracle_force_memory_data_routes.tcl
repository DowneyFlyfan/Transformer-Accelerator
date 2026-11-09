# Remove only the reported ordinary-data routes, then run selected global/detail
# routing. Search-and-repair alone left their existing physical wires unchanged.
source syn/tri_oracle_memory_physical_config.tcl
source syn/tri_oracle_memory_route_pair_policy.tcl
source syn/tri_oracle_memory_route_scope.tcl
source syn/tri_oracle_memory_wire_scope.tcl
source syn/tri_oracle_signal_repair_targets.tcl
source syn/tri_oracle_memory_point_dbu.tcl
source syn/tri_oracle_require_clean_placement.tcl
set tag postroute_memory_forced_routes_02
if {$::env(TRI_ORACLE_PHYSICAL_STAGE) ne $tag} {error "Unexpected forced-routing stage"}
set destination $out/${tag}.db
foreach path [list $destination $out/${tag}_router.rpt $out/${tag}_router.tif] {
    if {![catch {file lstat $path ignored}]} {error "Refusing existing forced-routing output: $path"}
}
set prefix postroute_slot_selected_routes_03
foreach {relative checksum} {
    postroute_slot_selected_routes_03_drc_after.rpt 061b8d6b7513f595200d50140d0524bae3a19848abba4edb43c25d43a35ebba2
    postroute_slot_selected_routes_03_antenna_after.rpt c87f0e790ad384c0f3cddf0d5531f11293fae24c7a7a5cee13eede9d308ab1b1
    postroute_slot_selected_routes_03_after/postroute_slot_selected_routes_03.tran.gz 759a4dcbe218619e090108aa0671a2cdb8cf044d338cbf95b09fedf607c92f52
    postroute_slot_selected_routes_03_after/postroute_slot_selected_routes_03.cap.gz f6ee804520289672e5ac10cc9570e0bbd954470e787398987599253885133aff
    postroute_slot_selected_routes_03_after/postroute_slot_selected_routes_03.SI_Glitches.rpt.gz 1f759e2a70e0c88a8d639bf7386660cb0b77d73e4fbb287fa97cf550cc7f7a4a
} {
    if {[lindex [exec sha256sum $out/$relative] 0] ne $checksum} {
        error "Forced-routing native diagnostic input changed: $relative"
    }
}
proc tri_oracle_memory_force_read {path} {
    set channel [open $path r]
    try {return [read $channel]} finally {close $channel}
}
set pairs [tri_oracle_memory_route_drc_pairs [tri_oracle_memory_force_read $out/${prefix}_drc_after.rpt]]
set antenna [tri_oracle_route_antenna_targets [tri_oracle_memory_force_read $out/${prefix}_antenna_after.rpt]]
set slew [tri_oracle_route_slew_targets [exec gzip -dc $out/${prefix}_after/${prefix}.tran.gz]]
set capacitance [tri_oracle_route_capacitance_targets [exec gzip -dc $out/${prefix}_after/${prefix}.cap.gz]]
set glitch [tri_oracle_route_glitch_targets [exec gzip -dc $out/${prefix}_after/${prefix}.SI_Glitches.rpt.gz]]
if {[llength $pairs] != 39 || [llength $antenna] != 0 || [llength $slew] != 155 ||
    [llength $capacitance] != 0 || [llength $glitch] != 1} {
    error "Complete measured forced-routing inventory changed"
}
set signal [lsort -unique [concat $slew $capacitance $glitch]]
set candidates $signal
foreach pair $pairs {lappend candidates [dict get $pair first] [dict get $pair second]}
set candidates [lsort -unique $candidates]
set_multi_cpu_usage -local_cpu 20
read_db $out/${prefix}.db
tri_oracle_require_memory_design
source syn/tri_oracle_memory_postroute_settings.tcl
set_db delaycal_enable_si true
set_db si_delay_enable_report true
set_db si_glitch_enable_report true
set classifications [dict create]
set net_objects [dict create]
set channel [open $out/${tag}_native_classification.tsv w]
try {
    puts $channel "net\tis_clock\tis_power\tis_ground"
    foreach name $candidates {
        if {[regexp {[*?]} $name]} {error "Ambiguous native candidate pattern: $name"}
        set net [get_db nets $name]
        if {[llength $net] != 1 || [get_db $net .name] ne $name} {error "Missing exact candidate net: $name"}
        set flags [dict create]
        foreach attribute {is_clock is_power is_ground} {
            set value [get_db $net .$attribute]
            if {![string is boolean -strict $value]} {error "Unknown native classification: $name"}
            dict set flags $attribute $value
        }
        dict set classifications $name $flags
        dict set net_objects $name $net
        puts $channel "$name\t[dict get $flags is_clock]\t[dict get $flags is_power]\t[dict get $flags is_ground]"
    }
} finally {close $channel}
set geometry [tri_oracle_memory_route_data_targets $pairs $classifications]
foreach name $signal {
    set flags [dict get $classifications $name]
    tri_oracle_route_require_data_net $name [dict get $flags is_clock] \
        [dict get $flags is_power] [dict get $flags is_ground]
}
set names [lsort -unique [concat $geometry $signal]]
if {[llength $names] == 0 || [llength $names] > 600} {error "Unbounded forced data-net inventory"}
set delays [get_db insts *TRI_MEMORY_ENDPOINT_HOLD_*]
if {[llength $delays] != 6568} {error "Exact repaired endpoint inventory changed"}
foreach inst $delays {
    if {[get_db $inst .base_cell.name] ne {DEL100D1BWP12T40P140} ||
        [get_db $inst .dont_touch] ne {true}} {error "Endpoint delay identity/protection changed"}
}
proc tri_oracle_memory_force_names {objects} {
    if {[llength $objects] == 0} {return {}}
    return [get_db $objects .name]
}
proc tri_oracle_memory_force_logical {net} {
    set pins [tri_oracle_memory_force_names [get_db $net .pins]]
    set ports [lsort -unique [concat [get_db $net .driver_ports] [get_db $net .load_ports]]]
    set ports [tri_oracle_memory_force_names $ports]
    return [tri_oracle_memory_wire_inventory [get_db $net .num_connections] $pins $ports]
}
proc tri_oracle_memory_force_native_row {inst} {
    return [list [get_db $inst .base_cell.name] \
        [tri_oracle_memory_point_dbu [get_db $inst .location]] \
        [get_db $inst .orient] [get_db $inst .place_status] \
        [get_db $inst .place_status_cts] [get_db $inst .place_status_effective] \
        [get_db $inst .dont_touch]]
}
# Complete logical inventories before any timing export or physical removal.
set logical [dict create]
set wire_counts [dict create]
set native_use [dict create]
foreach name $names {
    set net [dict get $net_objects $name]
    tri_oracle_memory_wire_data_use [get_db $net .use] [get_db $net .is_clock] \
        [get_db $net .is_power] [get_db $net .is_ground]
    dict set native_use $name [get_db $net .use]
    dict set logical $name [tri_oracle_memory_force_logical $net]
    set count [llength [get_db $net .wires]]
    if {$count < 1} {error "Expected existing routed signal: $name"}
    dict set wire_counts $name $count
}
set original [dict create]
foreach inst [get_db insts] {
    set row [tri_oracle_memory_force_native_row $inst]
    tri_oracle_memory_route_valid_row $row
    dict set original [get_db $inst .name] $row
}
if {[dict size $original] != 906420} {error "Exact antenna-repaired producer inventory changed"}
check_place > $out/${tag}_placement_before.rpt
tri_oracle_require_clean_placement $out/${tag}_placement_before.rpt
set channel [open $out/${tag}_targets.tsv w]
try {
    puts $channel "net\tgeometry\tsignal_integrity\twires_before\tlogical_connections\tnative_use"
    foreach name $names {
        puts $channel "$name\t[expr {$name in $geometry}]\t[expr {$name in $signal}]\t[dict get $wire_counts $name]\t[lindex [dict get $logical $name] 0]\t[dict get $native_use $name]"
    }
} finally {close $channel}
set diode ANTENNABWP12T40P140
if {[llength [get_db base_cells $diode]] != 1} {error "Characterized antenna diode is absent"}
set_db route_detail_fix_antenna true
set_db route_antenna_diode_insertion true
set_db route_antenna_cell_name $diode
reset_db route_detail_end_iteration
set_db route_detail_search_and_repair true
set saved_timing [get_db route_with_timing_driven]
set saved_si [get_db route_with_si_driven]
set saved_selected [get_db route_selected_net_only]
set saved_check_type [get_db timing_analysis_check_type]
set saved_fix_clock [get_db route_fix_clock_nets]
set saved_clock_first [get_db route_route_clock_nets_first]
set_db route_with_timing_driven true
set_db route_with_si_driven true
set_db route_fix_clock_nets true
set_db route_route_clock_nets_first false
if {[get_db route_fix_clock_nets] ne {true} || [get_db route_route_clock_nets_first] ne {false}} {
    error "Clock routing preservation settings were not honored"
}
foreach name $signal {
    set_route_attributes -nets $name -si_post_route_fix true -preferred_extra_space_tracks 2
}
set_db timing_analysis_check_type setup
report_timing -view setup_slow > $out/${tag}_setup_slow_before.rpt
report_timing -view setup_typ > $out/${tag}_setup_typ_before.rpt
set timing [tri_oracle_export_router_timing $out/${tag}_router.tif]
set clock_status [dict create]
foreach net [get_db nets -if {.is_clock == true}] {
    set wires [get_db $net .wires]
    set statuses {}
    if {[llength $wires]} {set statuses [get_db $wires .status]}
    if {[llength $statuses] != [llength $wires]} {error "Incomplete native clock-wire status inventory"}
    tri_oracle_memory_clock_wires [get_db $net .name] $statuses $statuses
    dict set clock_status [get_db $net .name] $statuses
}
if {[dict size $clock_status] < 2 || [dict size $clock_status] > 20000} {error "Unexpected native clock inventory"}
set router_report $out/${tag}_router.rpt
deselect_obj -all
set_db route_selected_net_only true
try {
    redirect $router_report {
        puts "TRI_ORACLE_MEMORY_FORCED_ROUTE_MODE [get_db route_with_timing_driven] [get_db route_with_si_driven] [get_db route_selected_net_only]"
        if {[get_db route_fix_clock_nets] ne {true} || [get_db route_route_clock_nets_first] ne {false}} {
            error "Clock preservation settings changed before physical wire removal"
        }
        puts "TRI_ORACLE_MEMORY_FORCED_CLOCK_MODE [get_db route_fix_clock_nets] [get_db route_route_clock_nets_first]"
        set removed_nets 0
        set removed_wires 0
        set channel [open $out/${tag}_wire_removals.tsv w]
        try {
            puts $channel "net\twires_before\twires_after\tlogical_connections\tnative_use"
            foreach name $names {
                set net [dict get $net_objects $name]
                tri_oracle_memory_wire_data_use [get_db $net .use] [get_db $net .is_clock] \
                    [get_db $net .is_power] [get_db $net .is_ground]
                if {[get_db $net .use] ne [dict get $native_use $name]} {error "Native data use changed before edit"}
                # Select physical wire objects: indexed net arguments were a
                # no-op in this release. A signal-use filter also omits the
                # six measured scan-data nets, so whitelist native uses above.
                deselect_obj -all
                foreach wire [get_db $net .wires] {select_obj $wire}
                delete_routes -selected -type regular
                deselect_obj -all
                set count [llength [get_db $net .wires]]
                incr removed_wires [tri_oracle_memory_wire_deletion $name \
                    [dict get $logical $name] [tri_oracle_memory_force_logical $net] \
                    [dict get $wire_counts $name] $count]
                incr removed_nets
                puts $channel "$name\t[dict get $wire_counts $name]\t$count\t[lindex [dict get $logical $name] 0]\t[dict get $native_use $name]"
            }
        } finally {close $channel}
        tri_oracle_memory_wire_scope_counts $removed_nets [llength $names] $removed_wires
        foreach name $names {
            set net [dict get $net_objects $name]
            if {[tri_oracle_memory_force_logical $net] ne [dict get $logical $name]} {
                error "A later deletion changed earlier logical connections: $name"
            }
            select_obj $net
        }
        puts "TRI_ORACLE_MEMORY_FORCED_WIRES_REMOVED $removed_nets $removed_wires"
        route_design -selected
    } -tee
} finally {
    set_db route_selected_net_only $saved_selected
    set_db route_with_timing_driven $saved_timing
    set_db route_with_si_driven $saved_si
    set_db timing_analysis_check_type $saved_check_type
    set_db route_fix_clock_nets $saved_fix_clock
    set_db route_route_clock_nets_first $saved_clock_first
    deselect_obj -all
    tri_oracle_reset_router_timing
}
set consumed [tri_oracle_require_router_timing_trace $router_report $timing]
set clock_nets_preserved 0
set clock_wires_preserved 0
foreach net [get_db nets -if {.is_clock == true}] {
    set name [get_db $net .name]
    if {![dict exists $clock_status $name]} {error "Routing added or renamed a clock net"}
    set wires [get_db $net .wires]
    set statuses {}
    if {[llength $wires]} {set statuses [get_db $wires .status]}
    if {[llength $statuses] != [llength $wires]} {error "Incomplete native clock-wire status inventory"}
    incr clock_wires_preserved [tri_oracle_memory_clock_wires $name [dict get $clock_status $name] $statuses]
    incr clock_nets_preserved
}
if {$clock_nets_preserved != [dict size $clock_status]} {error "Routing lost a clock net"}
unset clock_status
connect_global_net VDD -type pg_pin -pin_base_name VDD -all
connect_global_net VSS -type pg_pin -pin_base_name VSS -all
set preserved 0
set added {}
set diode_pins {}
foreach inst [get_db insts] {
    set name [get_db $inst .name]
    set row [tri_oracle_memory_force_native_row $inst]
    if {[dict exists $original $name]} {
        tri_oracle_memory_route_original_row $name [dict get $original $name] $row
        incr preserved
    } else {
        tri_oracle_memory_route_added_row $name $row
        lappend added [list $name $row]
        set diode_pins [concat $diode_pins [tri_oracle_memory_force_names [get_db $inst .pins]]]
    }
}
tri_oracle_memory_route_scope_counts $preserved [dict size $original] [llength $added]
unset original
set routed_nets 0
foreach name $names {
    set net [get_db nets $name]
    if {[llength $net] != 1 || [get_db $net .name] ne $name} {error "Routing lost exact original net: $name"}
    tri_oracle_memory_wire_data_use [get_db $net .use] [get_db $net .is_clock] \
        [get_db $net .is_power] [get_db $net .is_ground]
    incr routed_nets [tri_oracle_memory_wire_routed $name [dict get $logical $name] \
        [tri_oracle_memory_force_logical $net] $diode_pins [llength [get_db $net .wires]]]
}
if {$routed_nets != [llength $names] || [llength [get_db insts *TRI_MEMORY_ENDPOINT_HOLD_*]] != 6568} {
    error "Rerouting coverage or protected delay inventory changed"
}
set channel [open $out/${tag}_preservation.rpt w]
try {
    puts $channel "original_model_location_orientation_status_and_protection_preserved: $preserved"
    puts $channel "protected_endpoint_delays: 6568"
    puts $channel "added_antenna_diodes: [llength $added]"
    puts $channel "added_cell_inventory: $added"
    puts $channel "selected_nets_removed_and_rerouted: $routed_nets"
    puts $channel "original_target_logical_pins_and_ports_preserved: $routed_nets"
    puts $channel "removed_physical_wires: $removed_wires"
    puts $channel "clock_nets_with_unchanged_wire_statuses: $clock_nets_preserved"
    puts $channel "clock_wires_with_unchanged_statuses: $clock_wires_preserved"
    puts $channel "exact_native_timing_consumption: $consumed"
} finally {close $channel}
check_place > $out/${tag}_placement_after.rpt
tri_oracle_require_clean_placement $out/${tag}_placement_after.rpt
set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}
write_db -rc_extract $destination
puts "TRI_ORACLE_MEMORY_FORCED_ROUTE_CHECKPOINT_WRITTEN"
report_timing -view setup_slow > $out/${tag}_setup_slow.rpt
report_timing -view setup_typ > $out/${tag}_setup_typ.rpt
report_timing -early -view hold_fast > $out/${tag}_hold_fast.rpt
check_drc -out_file $out/${tag}_drc_after.rpt
check_antenna -out_file $out/${tag}_antenna_after.rpt
check_connectivity -type all -out_file $out/${tag}_connectivity.rpt
time_design -post_route -drv_report -expanded_views \
    -report_dir $out/${tag}_after -report_prefix $tag
puts "TRI_ORACLE_MEMORY_FORCED_ROUTE_COMMANDS_FINISHED"
exit
