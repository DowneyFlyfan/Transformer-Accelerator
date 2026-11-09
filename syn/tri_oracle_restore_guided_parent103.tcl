# A fresh process restores every original routed core after guidance optimization.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set parent $root/.cache/physical/pnr/tri_oracle_predicted_fabric_registered_reset30
set base $root/.cache/physical/pnr/tri_oracle_sram_memory_compute
set guide $::env(TRI_ORACLE_GUIDED_PARENT_DIRECTORY)
set out $::env(TRI_ORACLE_RESTORED_PARENT_DIRECTORY)
source $root/syn/tri_oracle_guided_parent_checks103.tcl
read_db $guide/guided.db
set_multi_cpu_usage -local_cpu 4
if {[get_db current_design .name] ne "tri_oracle_predicted_fabric"} {error "RESTORE86_WRONG_PARENT"}
unflatten_ilm
set file [open $guide/macros_before.tsv r]; set original_macros [string trimright [read $file] "\n"]; close $file
if {[guided85_macros] ne $original_macros} {error "RESTORE86_ORIGINAL_MACRO_CHANGED"}
read_ilm -cell tri_oracle_sram_memory_compute -directory $base/hierarchy_full_control_68/ilm
set constraints $root/.cache/physical/synthesis/tri_oracle_predicted_fabric_registered_reset30/constraints.sdc
update_constraint_mode -name functional -sdc_files [list $constraints] -ilm_sdc_files [list $constraints]
set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}
set_db enable_ui_precision true
set_db ui_precision_timing 6
set_db timing_analysis_type ocv
set_db timing_analysis_cppr both
set_db delaycal_enable_si true
set_ilm_type -model si
flatten_ilm
set counts [guided85_snapshot $out/full_after.tsv 94471]
set file [open $out/core_prefixes.txt w]
foreach name [lsort [dict keys $counts]] {puts $file $name}
close $file
exec python3 -B $root/syn/tri_oracle_core_preservation.py \
    $parent/placement79/core_after.tsv $out/full_after.tsv $out/core_prefixes.txt > $out/full_preservation.json
report_ilm_status > $out/full_model.rpt
unflatten_ilm
if {[guided85_macros] ne $original_macros} {error "RESTORE86_ORIGINAL_MACRO_CHANGED_AFTER_RESTORE"}
guided85_parent_legal $out/placement.rpt
guided85_registered_reset $root $out
write_netlist $out/full_parent.v -exclude_leaf_cells
write_def $out/full_parent.def
set_ilm_type -model si
flatten_ilm
write_db $out/restored_full.db
puts TRI_ORACLE_RESTORE103_ALL_ORIGINAL_CORES_RESTORED_REQUIRES_COLD_TIMING
exit
