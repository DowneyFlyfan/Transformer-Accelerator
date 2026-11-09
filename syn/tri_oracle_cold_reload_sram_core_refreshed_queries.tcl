# Independent native cold load of the repaired core44 with refreshed explicit base/noisy reports.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set top tri_oracle_sram_memory_compute
set checkpoint_root $root/.cache/physical/pnr/$top
set out $checkpoint_root/qualification_cold_reload_54
if {[file exists $out]} {error "Existing cold reload qualification"}
file mkdir $out
source syn/tri_oracle_require_clean_placement.tcl
set_multi_cpu_usage -local_cpu 1
read_db $checkpoint_root/routed_typical_repair_44.db
set_multi_cpu_usage -local_cpu 19
if {[llength [get_db insts]] != 94471} {error "Wrong fully routed core count"}
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
# Initialize complete post-route/SI timing before collection/path/coverage queries.
# Isolated cold runs49 are clean under the same flags and subsequent queries.
set_db timing_max_transition_use_si_transition true
set_db si_enable_drv_with_delta_slew true
set_db opt_post_route_report_si_transitions true
time_design -post_route -drv_report -expanded_views -report_dir $out/initial_si_reports -report_prefix initial_si
set saved_check_type [get_db timing_analysis_check_type]
set_db timing_analysis_check_type setup
check_timing -verbose -view setup_slow > $out/constraint_coverage_slow.rpt
set_db timing_analysis_check_type hold
check_timing -verbose -view hold_fast > $out/constraint_coverage_fast.rpt
set_db timing_analysis_check_type $saved_check_type
time_design -post_route -drv_report -expanded_views -report_dir $out/coverage_refresh -report_prefix coverage_refresh
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
time_design -post_route -drv_report -expanded_views -report_dir $out/path_refresh -report_prefix path_refresh
report_timing -view setup_slow -check_type setup -max_paths 10000 -nworst 1 -max_slack 0 -path_type summary > $out/setup_violating_paths.rpt
report_timing -early -view hold_fast -max_paths 10000 -nworst 1 -max_slack 0 -path_type summary > $out/hold_violating_paths.rpt
report_constraint -all_violators -late -view setup_slow > $out/constraint_violators_slow.rpt
report_constraint -all_violators -early -view hold_fast > $out/constraint_violators_fast.rpt
time_design -post_route -drv_report -expanded_views -report_dir $out/violator_refresh -report_prefix violator_refresh
# All original checks remain enabled; only full timing refresh boundaries differ.
# Switch report modes explicitly, then refresh timing before accepting noisy rows.
set scope [open $out/electrical_reporting_scope.rpt w]
set_db timing_max_transition_use_si_transition false
puts $scope "base_report_timing_max_transition_use_si_transition: [get_db timing_max_transition_use_si_transition]"
report_constraint -all_violators -drv_violation_type {max_capacitance max_transition} -view setup_slow > $out/electrical_base_slow.rpt
report_constraint -all_violators -drv_violation_type {max_capacitance max_transition} -view setup_typ > $out/electrical_base_typ.rpt
set_db timing_max_transition_use_si_transition true
set_db si_enable_drv_with_delta_slew true
set_db opt_post_route_report_si_transitions true
puts $scope "noisy_report_timing_max_transition_use_si_transition: [get_db timing_max_transition_use_si_transition]"
close $scope
time_design -post_route -drv_report -expanded_views -report_dir $out/qualification_si_reports -report_prefix qualification_si
report_constraint -all_violators -drv_violation_type {max_capacitance max_transition} -view setup_slow > $out/electrical_violators_slow.rpt
report_constraint -all_violators -drv_violation_type {max_capacitance max_transition} -view setup_typ > $out/electrical_violators_typ.rpt
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
puts TRI_ORACLE_SRAM_CORE_COLD_RELOAD54_FINISHED
exit
