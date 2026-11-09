# Bounded electrical repair only; setup optimization runs after a saved checkpoint.
# Compact core guidance is never final timing. Original constraints remain.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set parent $root/.cache/physical/pnr/tri_oracle_predicted_fabric_registered_reset30
set base $root/.cache/physical/pnr/tri_oracle_sram_memory_compute
set out $::env(TRI_ORACLE_GUIDED_PARENT_DIRECTORY)
source $root/syn/tri_oracle_guided_parent_checks99.tcl
read_db $parent/guidance96/prepare/prepared_guidance.db
set_multi_cpu_usage -local_cpu 2
if {[get_db current_design .name] ne "tri_oracle_predicted_fabric"} {error "GUIDED85_WRONG_PARENT"}
unflatten_ilm
set macro_baseline [guided85_macros]
set file [open $out/macros_before.tsv w]; puts $file $macro_baseline; close $file
set constraints $root/.cache/physical/synthesis/tri_oracle_predicted_fabric_registered_reset30/constraints.sdc
update_constraint_mode -name functional -sdc_files [list $constraints] -ilm_sdc_files [list $constraints]
set_analysis_view -setup {setup_slow} -hold {setup_slow}
set_db enable_ui_precision true
set_db ui_precision_timing 6
set_db timing_analysis_type ocv
set_db timing_analysis_cppr both
set_db delaycal_enable_si true
# Guidance mapping was already persisted and cold-qualified by96.
set_ilm_type -model si
flatten_ilm
guided85_snapshot $out/guidance_before.tsv 33818
report_ilm_status > $out/model_before.rpt
unflatten_ilm
set_db place_design_floorplan_mode false
opt_design -pre_cts -drv -report_dir $out/optimization_reports -report_prefix guidance
unflatten_ilm
place_detail
# Preserve the expensive native result even if a later checker rejects it.
# This checkpoint is unqualified until every native AND Python check passes.
set status [open $out/candidate_validation_pending.txt w]
puts $status "Unqualified candidate: no restoration, timing, or paper acceptance."
close $status
write_netlist $out/guided_parent.v -exclude_leaf_cells
write_def $out/guided_parent.def
set_ilm_type -model si
flatten_ilm
write_db $out/guided.db
unflatten_ilm
guided85_parent_legal $out/placement.rpt
if {[guided85_macros] ne $macro_baseline} {error "GUIDED85_ORIGINAL_MACRO_CHANGED"}
guided85_registered_reset $root $out
set_ilm_type -model si
flatten_ilm
guided85_snapshot $out/guidance_after.tsv 33818
report_ilm_status > $out/model_after.rpt
puts TRI_ORACLE_GUIDED99_DRV_PARENT_OPTIMIZATION_FINISHED_REQUIRES_FULL_RESTORE
exit
