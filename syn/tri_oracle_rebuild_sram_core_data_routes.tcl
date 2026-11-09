# Repair current ordinary-data DRC/antenna and measured noisy-slew victims.
# Exact current database, original cell/clock/logical preservation, fresh timing.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set top tri_oracle_sram_memory_compute
set checkpoint_root $root/.cache/physical/pnr/$top
set out $checkpoint_root/qualification_rebuild_18
if {[file exists $out]} {error "Refusing existing residual-data trial"}
file mkdir $out
foreach helper {memory_route_scope memory_wire_scope memory_point_dbu memory_native_route_checks sram_core_report_targets router_timing_interface require_clean_placement} {
    source syn/tri_oracle_${helper}.tcl
}
set_multi_cpu_usage -local_cpu 1
read_db $checkpoint_root/routed_drv_opt_16.db
set_multi_cpu_usage -local_cpu 19
if {[get_db current_design .name] ne $top || [llength [get_db insts]] != 94290} {error "Wrong current SRAM core"}
set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}
set_db timing_analysis_check_type setup
set_db delaycal_enable_si true
set_db si_delay_enable_report true
set_db si_glitch_enable_report true
set_db timing_max_transition_use_si_transition true
set_db opt_post_route_report_si_transitions true
check_drc -out_file $out/cold_input_drc.rpt
check_antenna -out_file $out/cold_input_antenna.rpt
check_place > $out/cold_input_placement.rpt
tri_oracle_require_clean_placement $out/cold_input_placement.rpt

# Repair the measured new buffer's two supply terminals; then trim supply stubs.
route_special -nets {VDD VSS} -connect core_pin -area {190 300 199 306} \
    -core_pin_target {stripe ring} -allow_layer_change 1 -allow_jogging 1 -layer_change_range {M1 M7}
edit_trim_routes -nets {VDD VSS}
check_connectivity -type all -error 100000 -warning 100000 -check_pg_ports -out_file $out/after_supply_connectivity.rpt
# Fresh native report must reproduce the admitted complete6-row inventory.
time_design -post_route -drv_report -expanded_views -report_dir $out/before_si -report_prefix before_si
set slew [tri_oracle_sram_core_drv_targets [exec gzip -dc $out/before_si/before_si.tran.gz] max_tran 6]
if {[llength $slew] != 5} {error "Unexpected complete noisy-net inventory"}

set antennas {}
set target_file .cache/physical/sram_core_route18_targets.txt
if {[lindex [exec sha256sum $target_file] 0] ne {9650fa62a65965f0e7a623f0d8496bbc0623e02fe2f542708d76351061b45344}} {error "Target inventory changed"}
set f [open $target_file r];set names [split [string trim [read $f]] \n];close $f
if {[llength $names] != 298} {error "Incomplete ordinary-data rebuild scope"}
set original [tri_oracle_memory_native_cells_snapshot 94290]
set clocks [tri_oracle_memory_native_clocks_snapshot]
if {![dict exists $clocks CTS_191]} {error "Measured excluded counterpart is not a native clock"}
# Classify every intended edit before changing any ordinary wire; emit all flags.
set f [open $out/target_native_classes.tsv w]
puts $f "net\tuse\tis_clock\tis_power\tis_ground"
set rejected {}
foreach name $names {
    set n [get_db nets $name]
    if {[llength $n] != 1 || [get_db $n .name] ne $name} {error "Missing exact target"}
    puts $f [join [list $name [get_db $n .use] [get_db $n .is_clock] [get_db $n .is_power] [get_db $n .is_ground]] \t]
    if {[catch {tri_oracle_memory_native_data_net $name} reason]} {lappend rejected [list $name $reason]}
}
close $f
if {[llength $rejected]} {error "Non-data targets rejected before wire edits: $rejected"}

set logical [dict create]
set all_logical [dict create]
foreach n [get_db nets] {
    dict set all_logical [get_db $n .name] [list [lsort [get_db $n .pins.name]] [lsort [get_db $n .driver_ports.name]] [lsort [get_db $n .load_ports.name]]]
}
set original_wire_counts [dict create]
set missing_before 0
set f [open $out/targets.tsv w]
puts $f "net\tnoisy_victim\tantenna_victim\twires_before\tlogical_connections"
foreach name $names {
    set n [tri_oracle_memory_native_data_net $name]
    dict set logical $name [tri_oracle_memory_native_logical $n]
    dict set original_wire_counts $name [llength [get_db $n .wires]]
    if {[dict get $original_wire_counts $name] == 0} {incr missing_before}
    puts $f [join [list $name [expr {$name in $slew}] [expr {$name in $antennas}] [llength [get_db $n .wires]] [get_db $n .num_connections]] \t]
}
close $f
if {$missing_before != 3} {error "Expected three originally unrouted target nets"}
set saved [dict create]
foreach a {route_with_timing_driven route_with_si_driven route_selected_net_only route_fix_clock_nets \
    route_route_clock_nets_first route_detail_fix_antenna route_antenna_diode_insertion route_antenna_cell_name \
    route_detail_search_and_repair route_detail_end_iteration route_with_eco} {dict set saved $a [get_db $a]}
try {
    set_db route_with_eco false
    set_db route_with_timing_driven true
    set_db route_with_si_driven true
    set_db route_fix_clock_nets true
    set_db route_route_clock_nets_first false
    set_db route_detail_fix_antenna true
    set_db route_antenna_diode_insertion true
    set_db route_antenna_cell_name ANTENNABWP12T40P140
    set_db route_detail_search_and_repair true
    reset_db route_detail_end_iteration
    foreach name $slew {set_route_attributes -nets $name -si_post_route_fix true -preferred_extra_space_tracks 2}
    report_timing -view setup_slow > $out/before_setup_slow.rpt
    report_timing -view setup_typ > $out/before_setup_typ.rpt
    set timing [tri_oracle_export_router_timing $out/router.tif]
    deselect_obj -all
    foreach name $names {select_obj [tri_oracle_memory_native_data_net $name]}
    set_db route_selected_net_only true
    redirect $out/router.rpt {
        if {[get_db route_with_timing_driven] ne {true} || [get_db route_with_si_driven] ne {true} ||
            [get_db route_selected_net_only] ne {true} || [get_db route_fix_clock_nets] ne {true} ||
            [get_db route_route_clock_nets_first] ne {false}} {error "Native route settings changed"}
        puts "TRI_ORACLE_MEMORY_SELECTED_ROUTE_MODE true true true"
        
        set removed 0
        set removed_wires 0
        foreach name $names {
            set n [tri_oracle_memory_native_data_net $name]
            set before_wires [dict get $original_wire_counts $name]
            if {$before_wires > 0} {
                deselect_obj -all
                foreach wire [get_db $n .wires] {select_obj $wire}
                delete_routes -selected -type regular
                incr removed_wires [tri_oracle_memory_wire_deletion $name [dict get $logical $name] \
                    [tri_oracle_memory_native_logical $n] $before_wires [llength [get_db $n .wires]]]
                incr removed
            } elseif {[llength [get_db $n .wires]] != 0} {error "Unrouted target changed unexpectedly"}
        }
        if {$removed != 295 || $removed_wires < 295} {error "Incomplete physical wire removal"}
        deselect_obj -all
        foreach name $names {select_obj [tri_oracle_memory_native_data_net $name]}
        puts "TRI_ORACLE_SRAM_REBUILD_TARGETS298_WIRED295_MISSING3"
        route_design -selected

    } -tee
} finally {
    foreach a [dict keys $saved] {set_db $a [dict get $saved $a]}
    deselect_obj -all
    tri_oracle_reset_router_timing
}
set consumed [tri_oracle_require_router_timing_trace $out/router.rpt $timing]
if {[dict get $consumed instances] != 94290} {error "Router consumed wrong core timing instance count"}
set clock_result [tri_oracle_memory_native_clocks_preserved $clocks]
connect_global_net VDD -type pg_pin -pin_base_name VDD -all
connect_global_net VSS -type pg_pin -pin_base_name VSS -all
set cells [tri_oracle_memory_native_cells_preserved $original]
set preserved_targets 0
foreach name $names {
    set n [tri_oracle_memory_native_data_net $name]
    incr preserved_targets [tri_oracle_memory_wire_routed $name [dict get $logical $name] \
        [tri_oracle_memory_native_logical $n] [dict get $cells allowed_diode_pins] [llength [get_db $n .wires]]]
}
set seen 0
foreach n [get_db nets] {
    set name [get_db $n .name]
    if {![dict exists $all_logical $name]} {error "Router added unexpected logical net: $name"}
    lassign [dict get $all_logical $name] pins dports lports
    set after [lsort [get_db $n .pins.name]]
    if {$dports ne [lsort [get_db $n .driver_ports.name]] || $lports ne [lsort [get_db $n .load_ports.name]]} {error "Router changed logical ports"}
    foreach p $pins {if {$p ni $after} {error "Router lost original pin"}}
    foreach p $after {if {$p ni $pins && $p ni [dict get $cells allowed_diode_pins]} {error "Router added non-diode pin"}}
    incr seen
}
if {$seen != [dict size $all_logical] || $preserved_targets != 298} {error "Incomplete logical preservation"}
set f [open $out/preservation.rpt w]
puts $f "original_cells_seven_fields_preserved: [dict get $cells original_cells]"
puts $f "added_antenna_diodes: [llength [dict get $cells added_antenna_diodes]]"
puts $f "all_original_logical_nets_preserved: $seen"
puts $f "target_logical_nets_preserved: $preserved_targets"
puts $f "clock_preservation: $clock_result"
puts $f "exact_native_timing_consumption: $consumed"
close $f
unset original clocks logical all_logical
check_place > $out/post_route_placement.rpt
tri_oracle_require_clean_placement $out/post_route_placement.rpt
write_db -rc_extract $checkpoint_root/routed_rebuild_18.db
# Saved optimizer state can have a pruned setup view. Qualify the original
# complete view set, rather than accepting an unconstrained typical report.
set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}
# Display precision only; these attributes do not change timing constraints or
# numerical-analysis accuracy. Do not infer more precision by padding zeros.
set_db enable_ui_precision true
set_db ui_precision_timing 6
set file [open $out/special_cell_inventory.rpt w]
puts $file "antenna_diode_instances: [llength [get_db insts -if {.base_cell.name == ANTENNABWP12T40P140}]]"
puts $file "explicit_feedback_delay_instances: [llength [get_db insts *TRI_FEEDBACK_HOLD*]]"
puts $file "explicit_endpoint_delay_instances: [llength [get_db insts *TRI_ENDPOINT_HOLD_*]]"
close $file
set file [open $out/optimizer_settings.rpt w]
foreach attribute {timing_analysis_type timing_analysis_cppr opt_hold_allow_overlap opt_post_route_allow_overlap opt_hold_target_slack opt_post_route_hold_recovery opt_post_route_area_reclaim} {
    puts $file "$attribute: [get_db $attribute]"
}
close $file

# Keep the saved analysis views, constraints and on-chip variation settings.
# Signal-integrity delay reporting must be enabled before timing is updated.
set_db si_delay_enable_report true
set_db si_glitch_enable_report true
set_db timing_check_timing_report_all_checks true
set saved_check_type [get_db timing_analysis_check_type]
set_db timing_analysis_check_type setup
check_timing -verbose -view setup_slow > $out/constraint_coverage_slow.rpt
set_db timing_analysis_check_type hold
check_timing -verbose -view hold_fast > $out/constraint_coverage_fast.rpt
set_db timing_analysis_check_type $saved_check_type
set slack_file [open $out/timing_slack_properties.rpt w]
report_timing -view setup_slow -check_type setup > $out/export_setup_slow.rpt
set exact_path [report_timing -view setup_slow -check_type setup -max_paths 1 -collection]
if {[sizeof_collection $exact_path] != 1} {error "Missing exact slow setup path"}
puts $slack_file "setup_slow_ns: [get_property $exact_path slack]"
report_timing -view setup_typ -check_type setup > $out/export_setup_typ.rpt
set exact_path [report_timing -view setup_typ -check_type setup -max_paths 1 -collection]
if {[sizeof_collection $exact_path] != 1} {error "Missing exact typical setup path"}
puts $slack_file "setup_typ_ns: [get_property $exact_path slack]"
report_timing -early -view hold_fast > $out/export_hold_fast.rpt
set exact_path [report_timing -early -view hold_fast -max_paths 1 -collection]
if {[sizeof_collection $exact_path] != 1} {error "Missing exact fast hold path"}
puts $slack_file "hold_fast_ns: [get_property $exact_path slack]"
puts $slack_file "Precision: native timing-path property values; no extra precision inferred"
close $slack_file
report_timing -view setup_slow -check_type setup -max_paths 10000 -nworst 1 -max_slack 0 -path_type summary > $out/setup_violating_paths.rpt
report_timing -early -view hold_fast -max_paths 10000 -nworst 1 -max_slack 0 -path_type summary > $out/hold_violating_paths.rpt
report_constraint -all_violators -late -view setup_slow > $out/constraint_violators_slow.rpt
report_constraint -all_violators -early -view hold_fast > $out/constraint_violators_fast.rpt
report_constraint -all_violators -drv_violation_type {max_capacitance max_transition} -view setup_slow > $out/electrical_violators_slow.rpt
report_constraint -all_violators -drv_violation_type {max_capacitance max_transition} -view setup_typ > $out/electrical_violators_typ.rpt
set_db timing_max_transition_use_si_transition true
set_db opt_post_route_report_si_transitions true
# In this release report_constraint still reports base slew with the flag set.
# Noisy-slew violations must be assessed from these time_design outputs instead.
set file [open $out/electrical_reporting_scope.rpt w]
puts $file "report_constraint: base slew, both setup views"
puts $file "time_design: noisy slew enabled, expanded setup views"
puts $file "timing_max_transition_use_si_transition: [get_db timing_max_transition_use_si_transition]"
puts $file "opt_post_route_report_si_transitions: [get_db opt_post_route_report_si_transitions]"
close $file
time_design -post_route -drv_report -expanded_views -report_dir $out/qualification_si_reports -report_prefix qualification_si
if {$top eq {tri_oracle_feedforward_core}} {
    # Read-only diagnosis of the actual freshly reported noisy-slew victims.
    # Pin/instance/net attributes are defined in the installed DBcom reference.
    source syn/tri_oracle_signal_repair_targets.tcl
    set victims [tri_oracle_route_slew_targets [exec gzip -dc $out/qualification_si_reports/qualification_si.tran.gz]]
    if {[llength $victims] > 100} {error "Unexpectedly large slew-driver diagnostic set"}
    set file [open $out/noisy_slew_drivers.tsv w]
    puts $file "net\tdriver_pin\tinstance\tbase_cell\tinstance_dont_touch\teffective_dont_touch\tnet_dont_touch\tload_pins\tparent\tparent_module\tmodule_instances"
    foreach name $victims {
        set net [get_db nets $name]
        if {[llength $net] != 1 || [get_db $net .name] ne $name} {error "Missing exact noisy-slew net: $name"}
        foreach driver [get_db $net .driver_pins] {
            set inst [get_db $driver .inst]
            set parent [get_db $inst .parent]
            set parent_name [get_db $parent .name]
            if {$parent_name eq $top} {
                set module_name $top
                set module_instances 1
            } else {
                set module [get_db $parent .module]
                set module_name [get_db $module .name]
                set module_instances [llength [get_db $module .hinsts]]
            }
            puts $file [join [list $name [get_db $driver .name] [get_db $inst .name] [get_db $inst .base_cell.name] [get_db $inst .dont_touch] [get_db $inst .dont_touch_effective] [get_db $net .dont_touch] [llength [get_db $net .load_pins]] $parent_name $module_name $module_instances] \t]
        }
        foreach port [get_db $net .driver_ports] {
            puts $file [join [list $name [get_db $port .name] external_port {} {} {} [get_db $net .dont_touch] [llength [get_db $net .load_pins]] {} {} {}] \t]
        }
    }
    close $file
}
# This tool supports bumpy-waveform reporting only in maximum-delay analysis.
# The default negative-slack filter would omit the present positive-setup paths;
# use an explicit one-microsecond reporting ceiling without changing constraints.
report_noise -noisy_waveform -delay max -threshold 0 -slack 1e-6 -view setup_slow -out_file $out/bumpy_waveforms_slow

check_place > $out/final_placement.rpt
check_drc -out_file $out/route_drc.rpt
check_connectivity -type all -error 100000 -warning 100000 -check_pg_ports -out_file $out/route_connectivity.rpt
check_antenna -out_file $out/antenna.rpt
report_area > $out/final_area.rpt
write_netlist $out/routed_netlist.v -exclude_leaf_cells
write_def $out/routed.def -routing
write_parasitics -spef_file $out/rc_slow.spef -rc_corner rc_slow
write_parasitics -spef_file $out/rc_fast.spef -rc_corner rc_fast

# Empty aliases and single-connection nets need no signal route. A functional
# signal net with multiple connections and no wire shapes is an open gate.
set file [open $out/unrouted_net_audit.tsv w]
puts $file "net\tconnections\tpower_or_ground"
set empty 0
set single 0
set pg 0
set active_missing 0
set routed 0
foreach net [get_db nets] {
    if {[llength [get_db $net .wires]] != 0} {incr routed;continue}
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
puts TRI_ORACLE_SRAM_CORE_DATA_REBUILD_COMMANDS_FINISHED
exit
