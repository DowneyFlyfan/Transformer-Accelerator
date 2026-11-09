# Read-only diagnosis: same routed database, explicit reporting-mode sequence.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set top tri_oracle_sram_memory_compute
set checkpoint_root $root/.cache/physical/pnr/$top
set out $checkpoint_root/noisy_settings_diagnosis_49
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
# Controlled additions to the saved database state; no physical mutations.
qualify_mode saved_mode
set_db si_delay_enable_report true
set_db si_glitch_enable_report true
qualify_mode with_report_flags
set saved_check_type [get_db timing_analysis_check_type]
set_db timing_analysis_check_type setup
check_timing -verbose -view setup_slow > $out/check_slow.rpt
set_db timing_analysis_check_type hold
check_timing -verbose -view hold_fast > $out/check_fast.rpt
set_db timing_analysis_check_type $saved_check_type
report_timing -view setup_slow -check_type setup > $out/path_slow.rpt
report_timing -view setup_typ -check_type setup > $out/path_typ.rpt
report_timing -early -view hold_fast > $out/path_fast.rpt
report_constraint -all_violators -late -view setup_slow > $out/setup_violators.rpt
report_constraint -all_violators -early -view hold_fast > $out/hold_violators.rpt
qualify_mode after_timing_checks
set_db timing_analysis_check_type setup
qualify_mode explicit_setup_mode
puts TRI_ORACLE_SRAM_CORE_NOISY_SETTINGS49_FINISHED
exit
