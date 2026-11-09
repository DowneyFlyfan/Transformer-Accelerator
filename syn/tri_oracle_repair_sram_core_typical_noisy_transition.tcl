# Repair the independently reproduced typical-view noisy transition violation.
# One equivalent drive-strength change, no logical or constraint relaxation.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set top tri_oracle_sram_memory_compute
set checkpoint_root $root/.cache/physical/pnr/$top
set out $checkpoint_root/qualification_typical_repair_44
if {[file exists $out]} {error "Refusing existing targeted resize"}
file mkdir $out
foreach helper {memory_route_scope memory_wire_scope memory_point_dbu memory_native_route_checks router_timing_interface require_clean_placement} {
    source [format {syn/tri_oracle_%s.tcl} $helper]
}
set_multi_cpu_usage -local_cpu 1
read_db $checkpoint_root/routed_residual_repair_40.db
set_multi_cpu_usage -local_cpu 19
if {[llength [get_db insts]] != 94471} {error "Wrong native input"}
set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}
set targets {
    {{compute_reduction[1].row[3].sum[0].value_reg[5]} DFMQD1BWP12T40P140 DFMQD2BWP12T40P140}
}
set original [tri_oracle_memory_native_cells_snapshot 94471]
set clocks [tri_oracle_memory_native_clocks_snapshot]
set logical [dict create]
foreach n [get_db nets] {
    dict set logical [get_db $n .name] [list [lsort [get_db $n .pins.name]] [lsort [get_db $n .driver_ports.name]] [lsort [get_db $n .load_ports.name]]]
}
set inventory [dict create]
foreach i [get_db insts] {dict set inventory [get_db $i .name] $i}
set expected_masters [dict create]
foreach tuple $targets {
    lassign $tuple name old new
    if {![dict exists $inventory $name]} {error "Missing exact measured driver"}
    set i [dict get $inventory $name]
    if {[get_db $i .base_cell.name] ne $old || [get_db $i .dont_touch_effective] ||
        [get_db $i .place_status] eq {fixed}} {error "Measured driver identity/protection changed"}
    if {[llength [get_db base_cells $new]] != 1} {error "Replacement not characterized"}
    dict set expected_masters $name $new
}
# Measure the exact typical-view base slew and the actual affected path margins.
set f [open $out/pre_edit_driver_slacks.tsv w]
set_db enable_ui_precision true
set_db ui_precision_timing 6
foreach tuple $targets {
    lassign $tuple name old new
    set i [dict get $inventory $name]
    set p [get_db $i .pins -if {.base_name == Q}]
    if {[llength $p] != 1} {error "Missing exact typical-view output"}
    set pin [get_db $p .name]
    set path [report_timing -early -view hold_fast -through [get_pins $pin] -max_paths 1 -collection]
    if {[sizeof_collection $path] != 1} {error "Missing affected hold path"}
    set hold [get_property $path slack]
    set path [report_timing -view setup_slow -check_type setup -through [get_pins $pin] -max_paths 1 -collection]
    if {[sizeof_collection $path] != 1} {error "Missing affected setup path"}
    set setup [get_property $path slack]
    report_timing -view setup_typ -check_type setup -through [get_pins $pin] > $out/pre_edit_typical_path.rpt
    set limit [get_db $p .max_transition -index {view setup_typ}]
    set actual [get_db $p .slew_max -index {view setup_typ}]
    set noisy [get_db $p .si_slew_max -index {view setup_typ}]
    puts $f [list $pin hold_fast_ns $hold setup_slow_ns $setup limit_ns $limit base_ns $actual noisy_ns $noisy]
    flush $f
    if {$noisy <= $limit} {error "Indexed typical noisy violation did not reproduce"}
    if {$hold < 0.02 || $setup < 0.02} {error "Affected driver lacks measured margin for a local resize"}
}
close $f

# Preserve the native equivalence/protection checks; never override them.
set_db eco_honor_dont_touch true
set_db eco_honor_dont_use true
set_db eco_honor_fixed_status true
set_db eco_check_logical_equivalence true
set_db eco_refine_place true
set_db eco_batch_mode true
foreach tuple $targets {
    lassign $tuple name old new
    eco_update_cell -insts $name -cells $new
}
set_db eco_batch_mode false
check_place > $out/after_resize_placement.rpt
tri_oracle_require_clean_placement $out/after_resize_placement.rpt
if {[llength [get_db insts]] != 94471} {error "Cell resize changed instance inventory"}
set changed_cells {}
set seen 0
set f [open $out/targeted_cell_changes.rpt w]
foreach i [get_db insts] {
    set name [get_db $i .name]
    if {![dict exists $original $name]} {error "Resize added unexpected cell"}
    set before [dict get $original $name]
    set after [tri_oracle_memory_native_cell_row $i]
    set master [lindex $after 0]
    if {[dict exists $expected_masters $name]} {
        if {$master ne [dict get $expected_masters $name]} {error "Native resize did not apply requested characterized master"}
    } elseif {$master ne [lindex $before 0]} {error "Non-target cell master changed"}
    if {[lindex $after 6] ne [lindex $before 6]} {error "Resize changed protection"}
    if {[lindex $before 3] eq {fixed} && $after ne $before} {error "Fixed macro/cell changed"}
    if {$after ne $before} {
        lappend changed_cells $name
        puts $f [list $name before $before after $after]
    }
    incr seen
}
puts $f "changed_cell_states: [llength $changed_cells]"
puts $f "requested_cell_master_changes: [dict size $expected_masters]"
close $f
if {$seen != 94471 || [llength $changed_cells] > 64} {error "Local resize moved an unexpectedly broad cell set"}
set sized [tri_oracle_memory_native_cells_snapshot 94471]
check_drc -out_file $out/before_eco_drc.rpt
set file [open $out/before_eco_drc.rpt r];set drc_text [read $file];close $file
set allowed_clocks {}
foreach n [get_db nets -if {.is_clock == true}] {
    set name [get_db $n .name]
    foreach p [get_db $n .pins] {
        if {[get_db $p .inst.name] in $changed_cells} {lappend allowed_clocks $name;break}
    }
}
# Include only actual clock counterparts of measured new geometry markers.
foreach {whole name} [regexp -all -inline {Regular Wire of Net ([^ ]+)} $drc_text] {
    if {[dict exists $clocks $name]} {lappend allowed_clocks $name}
}
set allowed_clocks [lsort -unique $allowed_clocks]
if {[llength $allowed_clocks] > 32} {error "Clock repair scope unexpectedly broad"}
foreach n [get_db nets -if {.is_clock == true}] {
    set_route_attributes -nets [get_db $n .name] -skip_routing [expr {[get_db $n .name] ni $allowed_clocks}]
}
set_db route_detail_end_iteration 20
set_db route_fix_clock_nets false
set_db route_route_clock_nets_first false
set_db route_selected_net_only false
set_db route_with_eco true
set_db route_with_timing_driven false
set_db route_with_si_driven false
set_db route_detail_fix_antenna true
set_db route_antenna_diode_insertion true
set_db route_antenna_cell_name ANTENNABWP12T40P140
tri_oracle_reset_router_timing
redirect $out/router.rpt {
    puts "TRI_ORACLE_TARGETED_RESIZE_GEOMETRIC_ECO"
    route_eco
} -tee
set f [open $out/router.rpt r];set routed [read $f];close $f
if {[regexp -nocase {NRIF-76.*droute_end_iteration|NRIG-87|NRCM-25|NRDB-187|NRDB-121|\*\*ERROR|\*\*FATAL} $routed] ||
    ![regexp -line {^#Complete route_global_detail on .+$} $routed] ||
    ![regexp -line {^#Total number of fails = 0$} $routed]} {error "Native targeted ECO did not finish"}
tri_oracle_reset_router_timing
connect_global_net VDD -type pg_pin -pin_base_name VDD -all
connect_global_net VSS -type pg_pin -pin_base_name VSS -all
set preserved [tri_oracle_memory_native_cells_preserved $sized]
set clock_seen 0
set protected_clock_wires 0
set repaired_clocks {}
foreach n [get_db nets -if {.is_clock == true}] {
    set name [get_db $n .name]
    if {![dict exists $clocks $name]} {error "New clock net"}
    set after [tri_oracle_memory_native_clock_status $n]
    if {$name in $allowed_clocks} {
        if {[llength $after] == 0} {error "Allowed clock remains unrouted"}
        lappend repaired_clocks [list $name before [llength [dict get $clocks $name]] after [llength $after]]
    } else {
        incr protected_clock_wires [tri_oracle_memory_clock_wires $name [dict get $clocks $name] $after]
    }
    incr clock_seen
}
if {$clock_seen != [dict size $clocks]} {error "Lost original clock"}
set net_seen 0
foreach n [get_db nets] {
    set name [get_db $n .name]
    if {![dict exists $logical $name]} {error "Added unexpected logical net"}
    lassign [dict get $logical $name] pins drivers loads
    if {$drivers ne [lsort [get_db $n .driver_ports.name]] ||
        $loads ne [lsort [get_db $n .load_ports.name]]} {error "Changed original logical ports"}
    set after [lsort [get_db $n .pins.name]]
    foreach pin $pins {if {$pin ni $after} {error "Lost original logical pin"}}
    foreach pin $after {
        if {$pin ni $pins && $pin ni [dict get $preserved allowed_diode_pins]} {error "Added non-diode logical pin"}
    }
    incr net_seen
}
if {$net_seen != [dict size $logical]} {error "Lost logical net"}
set f [open $out/preservation.rpt w]
puts $f "original_cell_identities_preserved: 94471"
puts $f "only_requested_master_changes: [dict size $expected_masters]"
puts $f "localized_cell_state_changes: [llength $changed_cells]"
puts $f "added_antenna_diodes: [llength [dict get $preserved added_antenna_diodes]]"
puts $f "all_original_logical_nets_preserved: $net_seen"
puts $f "protected_clock_nets: [expr {$clock_seen-[llength $allowed_clocks]}]"
puts $f "protected_clock_wires: $protected_clock_wires"
puts $f "allowed_clock_repairs: $repaired_clocks"
puts $f "native_route_scope: geometric_ECO_no_timing_file_claim"
close $f
unset original sized clocks logical inventory
write_db -rc_extract $checkpoint_root/routed_typical_repair_44.db
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
# Explicit modes prevent saved global state from concealing a view-specific row.
set scope [open $out/electrical_reporting_scope.rpt w]
set_db timing_max_transition_use_si_transition false
puts $scope "base_report_timing_max_transition_use_si_transition: [get_db timing_max_transition_use_si_transition]"
report_constraint -all_violators -drv_violation_type {max_capacitance max_transition} -view setup_slow > $out/electrical_base_slow.rpt
report_constraint -all_violators -drv_violation_type {max_capacitance max_transition} -view setup_typ > $out/electrical_base_typ.rpt
set_db timing_max_transition_use_si_transition true
set_db opt_post_route_report_si_transitions true
puts $scope "noisy_report_timing_max_transition_use_si_transition: [get_db timing_max_transition_use_si_transition]"
close $scope
report_constraint -all_violators -drv_violation_type {max_capacitance max_transition} -view setup_slow > $out/electrical_violators_slow.rpt
report_constraint -all_violators -drv_violation_type {max_capacitance max_transition} -view setup_typ > $out/electrical_violators_typ.rpt
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
puts TRI_ORACLE_SRAM_CORE_TYPICAL_REPAIR44_FINISHED
exit
