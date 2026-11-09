# One observed VIA2 cut end-of-line spacing violation, not a rule waiver.
# Scope from route_drc_before_spacing_repair.rpt, expanded around both vias.
source syn/tri_oracle_physical_config.tcl
if {$top ne "tri_oracle_tile_executor"} {error "Repair coordinates belong to executor"}
set_multi_cpu_usage -local_cpu 18
read_db $out/routed.db
route_detail {105.5 67.2 107.8 69.5}
check_drc -out_file $out/route_drc.rpt
check_connectivity -type all -out_file $out/route_connectivity.rpt
report_timing > $out/postroute_setup.rpt
report_timing -early > $out/postroute_hold.rpt
write_db -rc_extract $out/routed.db
puts "TRI_ORACLE_EXECUTOR_SPACING_REPAIR_COMMANDS_FINISHED"
exit
