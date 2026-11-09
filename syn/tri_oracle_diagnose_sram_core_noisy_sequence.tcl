# Read-only diagnosis: same routed database, explicit reporting-mode sequence.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set top tri_oracle_sram_memory_compute
set checkpoint_root $root/.cache/physical/pnr/$top
set out $checkpoint_root/noisy_sequence_diagnosis_51
if {[file exists $out]} {error "Refusing existing reporting diagnosis"}
file mkdir $out
set_multi_cpu_usage -local_cpu 1
read_db $checkpoint_root/routed_typical_repair_44.db
set_multi_cpu_usage -local_cpu 19
if {[llength [get_db insts]] != 94471} {error "Wrong diagnostic database"}
set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}
set_db enable_ui_precision true
set_db ui_precision_timing 6
set inventory [dict create]
foreach i [get_db insts] {dict set inventory [get_db $i .name] $i}
set probes {
    {{compute_reduction[1].row[3].sum[0].value_reg[5]} Q}
    {FE_PHC7963_load_data_178 Z}
}
proc qualify_mode {label} {
    global out top inventory probes
    set f [open $out/$label-settings.rpt w]
    foreach a {delaycal_enable_si si_enable_drv_with_delta_slew timing_max_transition_use_si_transition opt_post_route_report_si_transitions si_delay_enable_report si_glitch_enable_report timing_analysis_check_type} {
        puts $f "$a: [get_db $a]"
    }
    close $f
    time_design -post_route -drv_report -expanded_views -report_dir $out/$label-si -report_prefix $label
    foreach view {setup_slow setup_typ} {
        report_constraint -all_violators -drv_violation_type {max_capacitance max_transition} -view $view > [format {%s/%s-%s.rpt} $out $label $view]
    }
    set f [open $out/$label-probes.tsv w]
    puts $f "pin\tview\tlimit_ns\tbase_ns\tSI_ns"
    foreach tuple $probes {
        lassign $tuple name output
        set i [dict get $inventory $name]
        set p [get_db $i .pins -if {.base_name == $output}]
        if {[llength $p] != 1} {error "Missing exact reporting probe"}
        foreach view {setup_slow setup_typ} {
            set index [list view $view]
            puts $f [join [list [get_db $p .name] $view [get_db $p .max_transition -index $index] [get_db $p .slew_max -index $index] [get_db $p .si_slew_max -index $index]] \t]
        }
    }
    close $f
}
qualify_mode baseline
set saved_check_type [get_db timing_analysis_check_type]
set_db timing_analysis_check_type setup
check_timing -verbose -view setup_slow > $out/constraint_coverage_slow.rpt
set_db timing_analysis_check_type hold
check_timing -verbose -view hold_fast > $out/constraint_coverage_fast.rpt
set_db timing_analysis_check_type $saved_check_type

qualify_mode after_coverage
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

qualify_mode after_path_collections
report_timing -view setup_slow -check_type setup -max_paths 10000 -nworst 1 -max_slack 0 -path_type summary > $out/setup_violating_paths.rpt
report_timing -early -view hold_fast -max_paths 10000 -nworst 1 -max_slack 0 -path_type summary > $out/hold_violating_paths.rpt
report_constraint -all_violators -late -view setup_slow > $out/constraint_violators_slow.rpt
report_constraint -all_violators -early -view hold_fast > $out/constraint_violators_fast.rpt

qualify_mode after_violator_queries
set_db timing_max_transition_use_si_transition false
report_constraint -all_violators -drv_violation_type {max_capacitance max_transition} -view setup_slow > $out/electrical_base_slow.rpt
report_constraint -all_violators -drv_violation_type {max_capacitance max_transition} -view setup_typ > $out/electrical_base_typ.rpt
set_db timing_max_transition_use_si_transition true
qualify_mode after_base_switch
puts TRI_ORACLE_SRAM_CORE_NOISY_SEQUENCE51_FINISHED
exit
