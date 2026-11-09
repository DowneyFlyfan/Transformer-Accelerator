# Targeted repair retains the580MHz clock, interface budgets and uncertainty.
# The previous20ps optimization target ended at-16ps after final extraction.
source syn/tri_oracle_physical_config.tcl
if {$top ne "tri_oracle_memory_compute"} {error "This repair is qualified for the full-capacity core only"}
set_multi_cpu_usage -local_cpu 18
read_db $out/routed.db
set tag $::env(TRI_ORACLE_PHYSICAL_STAGE)
set backup $out/${tag}_input.db
if {[file exists $backup]} {error "Refusing to overwrite the input checkpoint backup"}
write_db -rc_extract $backup
puts "TRI_ORACLE_HOLD_REPAIR_INPUT_CHECKPOINT_WRITTEN $backup"
set_db timing_analysis_type ocv
set_db timing_analysis_cppr both
set_db opt_hold_target_slack 0.060
opt_design -post_route -hold -report_dir $out/${tag}_reports
# Preserve the repaired checkpoint before any later report/check command.
write_db -rc_extract $out/routed.db
puts "TRI_ORACLE_HOLD_REPAIR_CHECKPOINT_WRITTEN"
report_timing -view setup_slow -check_type setup > $out/postroute_setup.rpt
report_timing -early -view hold_fast > $out/postroute_hold.rpt
check_drc -out_file $out/route_drc.rpt
check_connectivity -type all -out_file $out/route_connectivity.rpt
puts "TRI_ORACLE_CORE_HOLD_REPAIR_COMMANDS_FINISHED"
exit
