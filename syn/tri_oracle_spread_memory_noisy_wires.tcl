# Spread only the complete cold-reported data victims. Clock, interface and
# process constraints stay unchanged; independent reports determine success.
source syn/tri_oracle_memory_physical_config.tcl
source syn/tri_oracle_memory_route_scope.tcl
source syn/tri_oracle_memory_wire_scope.tcl
source syn/tri_oracle_memory_point_dbu.tcl
source syn/tri_oracle_memory_native_route_checks.tcl
source syn/tri_oracle_signal_repair_targets.tcl
source syn/tri_oracle_require_clean_placement.tcl
set tag postroute_memory_wire_spread
if {$::env(TRI_ORACLE_PHYSICAL_STAGE) ne $tag} {error "Unexpected memory wire-spread stage"}
set stem "$out/$tag"
foreach path [list $stem.db $stem.router.rpt $stem.router.tif] {
    if {![catch {file lstat $path ignored}]} {error "Refusing existing wire-spread output: $path"}
}
set reports $out/qualification_postroute_qualify_after_forced_data_routes/qualification_si_reports
foreach {relative checksum} {
    qualification_si.tran.gz 898405bb92d745f974d29bb7b4d6c03c07ebfa7b16a31859b88a79ccdc13269d
    qualification_si.cap.gz 12f80f910e9a934fefbf0a95079ef29a623bfc135faa3b7492031376164d00ec
    qualification_si.SI_Glitches.rpt.gz 73560f09941f0d4237504ff9b9bf5a6ec03d7fc17d811be919c91fb195c8600e
} {
    if {[lindex [exec sha256sum $reports/$relative] 0] ne $checksum} {error "Cold electrical input changed: $relative"}
}
set names [tri_oracle_route_slew_targets [exec gzip -dc $reports/qualification_si.tran.gz]]
set capacitance [tri_oracle_route_capacitance_targets [exec gzip -dc $reports/qualification_si.cap.gz]]
set glitch [tri_oracle_route_glitch_targets [exec gzip -dc $reports/qualification_si.SI_Glitches.rpt.gz]]
if {[llength $names] != 28 || [llength $capacitance] || [llength $glitch]} {error "Complete cold electrical inventory changed"}
set_multi_cpu_usage -local_cpu 20
read_db $out/postroute_memory_forced_routes_02.db
tri_oracle_require_memory_design
source syn/tri_oracle_memory_postroute_settings.tcl
set_db delaycal_enable_si true
set_db si_delay_enable_report true
set_db si_glitch_enable_report true
set saved_check_type [get_db timing_analysis_check_type]
set saved [dict create]
foreach attribute {route_with_timing_driven route_with_si_driven route_selected_net_only \
    route_fix_clock_nets route_route_clock_nets_first route_detail_post_route_wire_widen \
    route_detail_post_route_spread_wire route_detail_min_slack_for_opt_wire} {
    dict set saved $attribute [get_db $attribute]
}
try {
    set_db timing_analysis_check_type setup
    report_timing -view setup_slow > $stem.before_setup_slow.rpt
    report_timing -view setup_typ > $stem.before_setup_typ.rpt
    set logical [dict create]
    set channel [open $stem.targets.tsv w]
    try {
        puts $channel "net\tnative_use\twires_before\tlogical_connections"
        foreach name $names {
            set net [tri_oracle_memory_native_data_net $name]
            dict set logical $name [tri_oracle_memory_native_logical $net]
            set wires [llength [get_db $net .wires]]
            if {$wires < 1} {error "Cold victim has no original routing: $name"}
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
    set_db route_detail_post_route_wire_widen none
    set_db route_detail_post_route_spread_wire 1
    # Installed command documentation defines this as an eligibility threshold,
    # not a path/clock timing constraint. Include all28 selected noisy victims.
    set_db route_detail_min_slack_for_opt_wire 10.0
    foreach name $names {
        set_route_attributes -nets $name -si_post_route_fix true -preferred_extra_space_tracks 2
    }
    set channel [open $stem.settings.rpt w]
    try {
        foreach attribute [dict keys $saved] {puts $channel "$attribute: [get_db $attribute]"}
        puts $channel "selected_data_nets: [llength $names]"
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
                [get_db route_route_clock_nets_first] ne {false}} {error "Native spread/clock routing settings changed"}
            puts "TRI_ORACLE_MEMORY_WIRE_SPREAD_MODE true true true"
            puts "TRI_ORACLE_MEMORY_WIRE_SPREAD_CLOCK_MODE true false"
            puts "TRI_ORACLE_MEMORY_WIRE_SPREAD_TARGETS [llength $names]"
            route_design -selected -wire_opt
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
if {$targets_preserved != 28} {error "Incomplete noisy-victim preservation"}
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
puts "TRI_ORACLE_MEMORY_WIRE_SPREAD_CHECKPOINT_WRITTEN"
report_timing -view setup_slow > $stem.setup_slow.rpt
report_timing -view setup_typ > $stem.setup_typ.rpt
report_timing -early -view hold_fast > $stem.hold_fast.rpt
check_drc -out_file $stem.drc.rpt
check_antenna -out_file $stem.antenna.rpt
check_connectivity -type all -out_file $stem.connectivity.rpt
time_design -post_route -drv_report -expanded_views -report_dir $stem.after -report_prefix $tag
puts "TRI_ORACLE_MEMORY_WIRE_SPREAD_COMMANDS_FINISHED"
exit
