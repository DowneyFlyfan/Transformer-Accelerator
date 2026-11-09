# Unreduced counterfactual for validating the compact model in the same parent.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set top tri_oracle_sram_memory_compute
set base $root/.cache/physical/pnr/$top
set out $base/hierarchy_full_control_68
if {[file exists $out]} {error "Existing full hierarchy control"}
file mkdir $out
set_multi_cpu_usage -local_cpu 1
read_db $base/routed_typical_repair_44.db
set_multi_cpu_usage -local_cpu 19
if {[llength [get_db insts]] != 94471} {error "Wrong routed core"}
set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}
set_db enable_ui_precision true
set_db ui_precision_timing 6
set_db ilm_keep_async true
set_db si_delay_enable_report true
set_db si_glitch_enable_report true
set_db timing_max_transition_use_si_transition true
set_db si_enable_drv_with_delta_slew true
set_db opt_post_route_report_si_transitions true
time_design -post_route -drv_report -expanded_views -report_dir $out/source_si -report_prefix source_si
write_netlist $out/source_netlist_before.v -exclude_leaf_cells
write_ilm -to_dir $out/ilm -model_type all -opt_stage postcts -keep_all
write_netlist $out/source_netlist_after.v -exclude_leaf_cells
puts TRI_ORACLE_SRAM_CORE_FULL_HIERARCHY68_EXPORTED
exit
