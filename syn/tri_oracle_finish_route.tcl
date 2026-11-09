# Shared final phase; both normal and checkpoint-resume flows source this file.
# OCV mode is required by the SI-aware post-route optimizer. No custom process
# derates are introduced here; variation-model signoff remains a separate gate.
set_db timing_analysis_type ocv
set_db timing_analysis_cppr both
# Local 20 ps hold-repair margin: the zero-target pass left a 1 ps
# post-extraction short-path violation. Timing constraints remain unchanged.
set_db opt_hold_target_slack 0.020
opt_design -post_route -setup -hold -report_dir $out/route_reports
report_timing > $out/postroute_setup.rpt
report_timing -early > $out/postroute_hold.rpt
check_drc -out_file $out/route_drc.rpt
check_connectivity -type all -out_file $out/route_connectivity.rpt
write_db -rc_extract $out/routed.db
puts "TRI_ORACLE_CLOCK_AND_ROUTE_COMMANDS_FINISHED"
