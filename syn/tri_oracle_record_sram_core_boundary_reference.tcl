# Golden boundary timing from a fresh full routed core44 database.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set top tri_oracle_sram_memory_compute
set base $root/.cache/physical/pnr/$top
set out $base/hierarchy_boundary_reference_59
if {[file exists $out]} {error "Existing boundary reference"}
file mkdir $out
set_multi_cpu_usage -local_cpu 1
read_db $base/routed_typical_repair_44.db
set_multi_cpu_usage -local_cpu 19
if {[llength [get_db insts]] != 94471} {error "Wrong routed core"}
set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}
set_db enable_ui_precision true
set_db ui_precision_timing 6
set_db timing_analysis_type ocv
set_db timing_analysis_cppr both
set_db si_delay_enable_report true
set_db si_glitch_enable_report true
set_db timing_max_transition_use_si_transition true
set_db si_enable_drv_with_delta_slew true
set_db opt_post_route_report_si_transitions true
source syn/tri_oracle_hierarchy_boundary_paths.tcl
tri_oracle_record_boundary_paths $out
puts TRI_ORACLE_SRAM_CORE_BOUNDARY59_RECORDED
exit
