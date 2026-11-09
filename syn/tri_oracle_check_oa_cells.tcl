set project /home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator
set_multi_cpu_usage -local_cpu 18
read_physical -oa_ref_libs {tcbn28hpcplusbwp12t40p140} -oa_tech_lib tri_tech
puts "OA_BASE_CELL_COUNT [llength [get_db base_cells]]"
write_lef_library $project/.cache/physical/library/combined_vendor_oa.lef
puts "TRI_ORACLE_OA_CELLS_READ_FINISHED"
exit
