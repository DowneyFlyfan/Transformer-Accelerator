# Land the M4 supply within one native macro rail instead of bridging two.
# The measured old wire and contact straddle the0.13um gap between native VDD
# shapes y462.980..463.580 and463.710..464.210 of outputs[0].
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set top tri_oracle_sram_memory_compute
set checkpoint_root $root/.cache/physical/pnr/$top
set out $checkpoint_root/qualification_pg_reland_14
if {[file exists $out]} {error "Refusing existing rail-landing trial"}
file mkdir $out
set_multi_cpu_usage -local_cpu 1
read_db $checkpoint_root/routed_data_route_13.db
set_multi_cpu_usage -local_cpu 19
if {[get_db current_design .name] ne $top || [llength [get_db insts]] != 94274} {error "Wrong current core with two diodes"}
foreach helper {memory_route_scope memory_wire_scope memory_point_dbu memory_native_route_checks} {source syn/tri_oracle_${helper}.tcl}
proc core_logic {} {
    set result {}
    foreach n [get_db nets] {
        lappend result [list [get_db $n .name] [lsort [get_db $n .pins.name]] \
            [lsort [get_db $n .driver_ports.name]] [lsort [get_db $n .load_ports.name]]]
    }
    return [lsort $result]
}
set before [tri_oracle_memory_native_cells_snapshot 94274]
set logic [core_logic]
check_drc -out_file $out/cold_input_drc.rpt
check_connectivity -type all -error 100000 -warning 100000 -check_pg_ports -out_file $out/cold_input_connectivity.rpt
set wires {}
foreach w [get_obj_in_area -obj_type special_wire -areas {{26 463 31.1 464}}] {
    if {[get_db $w .net.name] ne "VDD" || [get_db $w .layer.name] ne "M4"} {continue}
    set r [get_db $w .rect]
    if {[llength $r] == 1} {set r [lindex $r 0]}
    if {$r eq {26.595 463.475 30.99 463.725}} {lappend wires $w}
}
set vias {}
foreach v [get_obj_in_area -obj_type special_via -areas {{30 463.4 31 463.8}}] {
    if {[get_db $v .net.name] eq "VDD" && [get_db $v .via_def.bottom_layer.name] eq "M4" &&
        [get_db $v .via_def.top_layer.name] eq "M5"} {lappend vias $v}
}
if {[llength $wires] != 1 || [llength $vias] != 1} {error "Exact bridging geometry changed"}
set old [lindex $vias 0]
set point [get_db $old .point]
if {[llength $point] == 1} {set point [lindex $point 0]}
if {$point ne {30.495 463.595} || [llength [get_db $old .cut_rects]] != 10} {error "Exact measured contact changed"}
set master [get_db $old .via_def]
create_via -via_def $master -location {30.495 463.25} -net VDD -shape corewire -status routed
# Put the vertical jog outside the macro boundary x30um. Preserve its M3 feed.
foreach path {{26.66 463.6 28.5 463.6} {28.5 463.6 28.5 463.25} {28.5 463.25 30.495 463.25}} {
    create_shape -net VDD -layer M4 -path_segment $path -width 0.25 -shape corewire -status routed
}
delete_obj $old
delete_obj [lindex $wires 0]
check_drc -out_file $out/after_reland_drc.rpt
check_connectivity -type all -error 100000 -warning 100000 -check_pg_ports -out_file $out/after_reland_connectivity.rpt
set f [open $out/after_reland_connectivity.rpt r];set connectivity [read $f];close $f
if {[string first {Found no problems or warnings.} $connectivity] < 0} {error "Rail landing disconnected supply geometry"}
set preserved [tri_oracle_memory_native_cells_preserved $before]
if {[llength [dict get $preserved added_antenna_diodes]] || [core_logic] ne $logic} {error "Power-only change modified logic or original cells"}
set f [open $out/preservation.rpt w]
puts $f "original_cells_seven_fields_preserved: [dict get $preserved original_cells]"
puts $f "all_logical_nets_preserved: true"
puts $f "old_bridging_M4_wire_deleted: 1"
puts $f "old_M4_M5_contact_replaced_same_master: 1"
puts $f "new_contact_point: 30.495 463.25"
puts $f "native_macro_rail_untouched: x30..51.88 y462.98..463.58"
close $f
write_db -rc_extract $checkpoint_root/routed_pg_reland_14.db
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
puts TRI_ORACLE_SRAM_CORE_PG_RELAND_COMMANDS_FINISHED
exit
