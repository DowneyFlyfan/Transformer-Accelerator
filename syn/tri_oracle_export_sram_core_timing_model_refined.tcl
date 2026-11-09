# Extract the actual routed-core boundary model for hierarchical synthesis.
# Production physical analysis continues to use the complete keep_all models.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set top tri_oracle_sram_memory_compute
set base $root/.cache/physical/pnr/$top
set out $base/hierarchy_timing_model_80
if {[file exists $out]} {error "Existing extracted timing-model experiment"}
file mkdir $out
set_multi_cpu_usage -local_cpu 1
read_db $base/routed_typical_repair_44.db
set_multi_cpu_usage -local_cpu 19
if {[llength [get_db insts]] != 94471 || [llength [get_db ports]] != 3158} {
    error "Wrong original routed core or interface"
}
# Both early/late extraction must use the same typical PVT/RC view. This is a
# synthesis model; it does not replace the three-view physical qualification.
set_analysis_view -setup {setup_typ} -hold {setup_typ}
set_db enable_ui_precision true
set_db ui_precision_timing 6
set_db timing_analysis_type ocv
set_db timing_analysis_cppr both
set_db delaycal_enable_si true
set_db si_delay_enable_report true
set_db si_glitch_enable_report true
set_db timing_max_transition_use_si_transition true
set_db si_enable_drv_with_delta_slew true
set_db opt_post_route_report_si_transitions true
set saved_check [get_db timing_analysis_check_type]
set_db timing_analysis_check_type setup
check_timing -verbose -view setup_typ > $out/source_setup_coverage.rpt
set_db timing_analysis_check_type hold
check_timing -verbose -view setup_typ > $out/source_hold_coverage.rpt
set_db timing_analysis_check_type $saved_check
time_design -post_route -drv_report -expanded_views -report_dir $out/source_si -report_prefix source_si
write_netlist $out/source_netlist_before.v -exclude_leaf_cells
set file [open $out/extraction_scope.rpt w]
foreach attribute {timing_analysis_type timing_analysis_cppr delaycal_enable_si timing_max_transition_use_si_transition si_enable_drv_with_delta_slew} {
    puts $file "$attribute: [get_db $attribute]"
}
puts $file "original_instances: [llength [get_db insts]]"
puts $file "signal_ports: [llength [get_db ports]]"
puts $file "extraction_view: setup_typ used for both early and late"
puts $file "clock_period_ns: 1.72414 unchanged source constraint"
puts $file "scope: synthesis boundary model only; full models remain required for physical signoff"
close $file
puts TRI_ORACLE_CORE80_EXTRACTION_STARTED
write_timing_model $out/core_typ.lib \
    -view setup_typ -cell_name $top -lib_name tri_oracle_core44_typ \
    -include_power_ground -precision 6 -resolution 0.00001 -tolerance 0.01 \
    -assertions $out/core_typ.asrt \
    -validation_dir $out/native_validation \
    -absolute_tolerance_validation 0.001 \
    -absolute_tolerance_optimistic_validation 0.001 \
    -absolute_tolerance_pessimistic_validation 0.001 \
    -percent_tolerance_validation 0.1 \
    -percent_tolerance_optimistic_validation 0.1 \
    -percent_tolerance_pessimistic_validation 0.1 \
    -verilog_shell_file $out/model_shell.v \
    -verilog_shell_module tri_oracle_core44_timing_shell
write_netlist $out/source_netlist_after.v -exclude_leaf_cells
if {[llength [get_db insts]] != 94471} {error "Extraction changed the loaded source design"}
puts TRI_ORACLE_CORE_TIMING_MODEL80_EXPORTED
exit
