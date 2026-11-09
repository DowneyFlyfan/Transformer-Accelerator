# Revalidate the saved99 candidate; never repeat optimization here.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set parent $root/.cache/physical/pnr/tri_oracle_predicted_fabric_registered_reset30
set out $::env(TRI_ORACLE_GUIDED_PARENT_DIRECTORY)
source $root/syn/tri_oracle_guided_parent_checks103.tcl
read_db $parent/guided99_drv/guided.db
set_multi_cpu_usage -local_cpu 4
if {[get_db current_design .name] ne "tri_oracle_predicted_fabric"} {error "CANDIDATE103_WRONG_PARENT"}
unflatten_ilm
set file [open $parent/guided99_drv/macros_before.tsv r]
set original_macros [string trimright [read $file] "\n"];close $file
if {[guided85_macros] ne $original_macros} {error "CANDIDATE103_ORIGINAL_MACRO_CHANGED"}
set file [open $out/macros_before.tsv w];puts $file $original_macros;close $file
guided85_parent_legal $out/placement.rpt
guided85_registered_reset $root $out
set_ilm_type -model si
flatten_ilm
guided85_snapshot $out/guidance_after.tsv 33818
report_ilm_status > $out/model_after.rpt
write_db $out/guided.db
puts TRI_ORACLE_CANDIDATE103_NATIVE_CHECKS_FINISHED_REQUIRES_FULL_RESTORE
exit
