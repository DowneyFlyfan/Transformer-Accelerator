set project /home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator
set_multi_cpu_usage -local_cpu 18
set tech tri_tech
if {[info exists ::env(TRI_ORACLE_OA_TECH)]} {set tech $::env(TRI_ORACLE_OA_TECH)}
read_physical -oa_ref_libs [list $tech] -oa_tech_lib $tech
write_lef_library -tech_only $project/.cache/physical/library/technology_${tech}.lef
puts "TRI_ORACLE_OA_PHYSICAL_READ_FINISHED"
exit
