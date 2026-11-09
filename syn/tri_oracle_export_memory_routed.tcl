source syn/tri_oracle_memory_physical_config.tcl
set_multi_cpu_usage -local_cpu 20
read_db $out/routed.db
tri_oracle_require_memory_design
check_place > $out/final_placement.rpt
check_antenna -out_file $out/antenna.rpt
report_area > $out/final_area.rpt
write_netlist $out/routed_netlist.v -exclude_leaf_cells
write_def $out/routed.def -routing
write_parasitics -spef_file $out/rc_slow.spef -rc_corner rc_slow
write_parasitics -spef_file $out/rc_fast.spef -rc_corner rc_fast
report_timing -view setup_slow -check_type setup > $out/export_setup_slow.rpt
report_timing -view setup_typ -check_type setup > $out/export_setup_typ.rpt
report_timing -early -view hold_fast > $out/export_hold_fast.rpt
puts "TRI_ORACLE_ROUTED_EXPORT_COMMANDS_FINISHED"
exit
