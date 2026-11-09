# Recreate fresh full-check geometry markers before selected ordinary-data routing.
# Preserve all original cells, connections, clock wires and timing constraints.
source syn/tri_oracle_memory_physical_config.tcl
source syn/tri_oracle_memory_route_scope.tcl
source syn/tri_oracle_memory_wire_scope.tcl
source syn/tri_oracle_memory_point_dbu.tcl
source syn/tri_oracle_memory_native_route_checks.tcl
source syn/tri_oracle_memory_route_pair_policy.tcl
source syn/tri_oracle_memory_current_geometry.tcl
source syn/tri_oracle_require_clean_placement.tcl
set tag postroute_memory_geometry_markers
if {$::env(TRI_ORACLE_PHYSICAL_STAGE) ne $tag} {error "Unexpected memory geometry-repair stage"}
set stem "$out/$tag"
foreach path [list $stem.db $stem.router.rpt $stem.router.tif] {
    if {![catch {file lstat $path ignored}]} {error "Refusing existing geometry-repair output: $path"}
}
set predecessor_geometry $out/postroute_memory_wire_spread.drc.rpt
if {[lindex [exec sha256sum $predecessor_geometry] 0] ne {6058b3cf14fd9c6e5ac5c0f978d495df1935bf18f456ee73061a837a1267e672}} {
    error "Qualified geometry report changed"
}
set file [open $predecessor_geometry r]
try {set expected_pairs [tri_oracle_memory_current_geometry_pairs [read $file]]} finally {close $file}
if {[llength $expected_pairs] != 29} {error "Qualified geometry total changed"}
proc tri_oracle_memory_geometry_signature {pairs} {
    set result {}
    foreach pair $pairs {
        lappend result [list [dict get $pair first] [dict get $pair second] [dict get $pair kind] \
            [dict get $pair layer] [dict get $pair bounds]]
    }
    return [lsort $result]
}
set_multi_cpu_usage -local_cpu 20
read_db $out/postroute_memory_wire_spread.db
tri_oracle_require_memory_design
source syn/tri_oracle_memory_postroute_settings.tcl
set_db delaycal_enable_si true
set_db si_delay_enable_report true
set_db si_glitch_enable_report true
set saved_check_type [get_db timing_analysis_check_type]
set saved [dict create]
foreach attribute {route_with_timing_driven route_with_si_driven route_selected_net_only \
    route_fix_clock_nets route_route_clock_nets_first route_detail_fix_antenna \
    route_antenna_diode_insertion route_antenna_cell_name route_detail_end_iteration \
    route_detail_search_and_repair} {
    dict set saved $attribute [get_db $attribute]
}
try {
    set_db timing_analysis_check_type setup
    report_timing -view setup_slow > $stem.before_setup_slow.rpt
    report_timing -view setup_typ > $stem.before_setup_typ.rpt
    check_drc -out_file $stem.before_drc.rpt
    check_antenna -out_file $stem.before_antenna.rpt
    time_design -post_route -drv_report -expanded_views -report_dir $stem.before -report_prefix $tag
    set file [open $stem.before_drc.rpt r]
    try {set pairs [tri_oracle_memory_current_geometry_pairs [read $file]]} finally {close $file}
    if {[tri_oracle_memory_geometry_signature $pairs] ne [tri_oracle_memory_geometry_signature $expected_pairs]} {
        error "Fresh geometry markers differ from exact qualified predecessor"
    }
    set classes [dict create]
    set candidates {}
    foreach pair $pairs {
        lappend candidates [dict get $pair first] [dict get $pair second]
    }
    set channel [open $stem.counterparts.tsv w]
    try {
        puts $channel "net\tnative_use\tis_clock\tis_power\tis_ground"
        foreach name [lsort -unique $candidates] {
            if {[regexp {[*?]} $name]} {error "Ambiguous geometry counterpart"}
            set net [get_db nets $name]
            if {[llength $net] != 1 || [get_db $net .name] ne $name} {error "Missing exact geometry counterpart"}
            set flags [dict create]
            foreach flag {is_clock is_power is_ground} {dict set flags $flag [get_db $net .$flag]}
            dict set classes $name $flags
            puts $channel "$name\t[get_db $net .use]\t[dict get $flags is_clock]\t[dict get $flags is_power]\t[dict get $flags is_ground]"
        }
    } finally {close $channel}
    set names [tri_oracle_memory_route_data_targets $pairs $classes]
    if {[llength $names] < 1 || [llength $names] > 58} {error "Unexpected selected geometry target count"}
    puts "TRI_ORACLE_MEMORY_GEOMETRY_FRESH_MARKERS [llength $pairs]"
    set logical [dict create]
    set channel [open $stem.targets.tsv w]
    try {
        puts $channel "net\tnative_use\twires_before\tlogical_connections"
        foreach name $names {
            set net [tri_oracle_memory_native_data_net $name]
            dict set logical $name [tri_oracle_memory_native_logical $net]
            set wires [llength [get_db $net .wires]]
            if {$wires < 1} {error "Geometry counterpart has no original routing: $name"}
            puts $channel "$name\t[get_db $net .use]\t$wires\t[lindex [dict get $logical $name] 0]"
        }
    } finally {close $channel}
    tri_oracle_memory_native_require_delays 6568
    set original [tri_oracle_memory_native_cells_snapshot 906420]
    check_place > $stem.before_placement.rpt
    tri_oracle_require_clean_placement $stem.before_placement.rpt
    set_db route_with_timing_driven true
    set_db route_with_si_driven true
    set_db route_fix_clock_nets true
    set_db route_route_clock_nets_first false
    set diode ANTENNABWP12T40P140
    if {[llength [get_db base_cells $diode]] != 1} {error "Characterized antenna diode is absent"}
    set_db route_detail_fix_antenna true
    set_db route_antenna_diode_insertion true
    set_db route_antenna_cell_name $diode
    reset_db route_detail_end_iteration
    set_db route_detail_search_and_repair true
    set channel [open $stem.settings.rpt w]
    try {
        foreach attribute [dict keys $saved] {puts $channel "$attribute: [get_db $attribute]"}
        puts $channel "selected_data_nets: [llength $names]"
        puts $channel "fresh_full_check_geometry_markers: [llength $pairs]"
    } finally {close $channel}
    set timing [tri_oracle_export_router_timing $stem.router.tif]
    set clocks [tri_oracle_memory_native_clocks_snapshot]
    set clock_wire_count 0
    foreach name [dict keys $clocks] {incr clock_wire_count [llength [dict get $clocks $name]]}
    if {[dict size $clocks] != 4250 || $clock_wire_count != 593878} {error "Exact producer clock-wire baseline changed"}
    deselect_obj -all
    foreach name $names {select_obj [tri_oracle_memory_native_data_net $name]}
    set_db route_selected_net_only true
    redirect $stem.router.rpt {
            if {[get_db route_with_timing_driven] ne {true} || [get_db route_with_si_driven] ne {true} ||
                [get_db route_selected_net_only] ne {true} || [get_db route_fix_clock_nets] ne {true} ||
                [get_db route_route_clock_nets_first] ne {false}} {error "Native geometry/clock routing settings changed"}
            puts "TRI_ORACLE_MEMORY_GEOMETRY_MARKERS_MODE true true true"
            puts "TRI_ORACLE_MEMORY_GEOMETRY_MARKERS_CLOCK_MODE true false"
            puts "TRI_ORACLE_MEMORY_GEOMETRY_MARKERS_TARGETS [llength $names]"
            route_detail -selected
        } -tee
} finally {
    foreach attribute [dict keys $saved] {set_db $attribute [dict get $saved $attribute]}
    set_db timing_analysis_check_type $saved_check_type
    deselect_obj -all
    tri_oracle_reset_router_timing
}
set consumed [tri_oracle_require_router_timing_trace $stem.router.rpt $timing]
set clock_result [tri_oracle_memory_native_clocks_preserved $clocks]
if {[dict get $clock_result nets] != 4250 || [dict get $clock_result wires] != 593878} {
    error "Exact producer clock-wire preservation changed"
}
unset clocks
connect_global_net VDD -type pg_pin -pin_base_name VDD -all
connect_global_net VSS -type pg_pin -pin_base_name VSS -all
set cells [tri_oracle_memory_native_cells_preserved $original]
unset original
tri_oracle_memory_native_require_delays 6568
set targets_preserved 0
foreach name $names {
    set net [tri_oracle_memory_native_data_net $name]
    incr targets_preserved [tri_oracle_memory_wire_routed $name [dict get $logical $name] \
        [tri_oracle_memory_native_logical $net] [dict get $cells allowed_diode_pins] \
        [llength [get_db $net .wires]]]
}
if {$targets_preserved != [llength $names]} {error "Incomplete geometry-target preservation"}
set channel [open $stem.preservation.rpt w]
try {
    puts $channel "original_cells_seven_fields_preserved: [dict get $cells original_cells]"
    puts $channel "protected_endpoint_delays: 6568"
    puts $channel "added_antenna_diodes: [llength [dict get $cells added_antenna_diodes]]"
    puts $channel "added_cell_inventory: [dict get $cells added_antenna_diodes]"
    puts $channel "original_target_logical_pins_and_ports_preserved: $targets_preserved"
    puts $channel "clock_nets_wire_statuses_preserved: [dict get $clock_result nets]"
    puts $channel "clock_wires_statuses_preserved: [dict get $clock_result wires]"
    puts $channel "exact_native_timing_consumption: $consumed"
} finally {close $channel}
check_place > $stem.placement.rpt
tri_oracle_require_clean_placement $stem.placement.rpt
set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}
write_db -rc_extract $stem.db
puts "TRI_ORACLE_MEMORY_GEOMETRY_MARKERS_CHECKPOINT_WRITTEN"
report_timing -view setup_slow > $stem.setup_slow.rpt
report_timing -view setup_typ > $stem.setup_typ.rpt
report_timing -early -view hold_fast > $stem.hold_fast.rpt
check_drc -out_file $stem.drc.rpt
check_antenna -out_file $stem.antenna.rpt
check_connectivity -type all -out_file $stem.connectivity.rpt
time_design -post_route -drv_report -expanded_views -report_dir $stem.after -report_prefix $tag
puts "TRI_ORACLE_MEMORY_GEOMETRY_MARKERS_COMMANDS_FINISHED"
exit
