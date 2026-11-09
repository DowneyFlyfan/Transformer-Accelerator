# Repair the saved placement after removing synthesis-only preservation.
source syn/tri_oracle_physical_config.tcl
if {$top ne "tri_oracle_feedforward_core"} {error "Feed-forward top required"}
set_multi_cpu_usage -local_cpu 18
read_db $out/placed.db
set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}
set_db enable_ui_precision true
set_db ui_precision_timing 6
source syn/tri_oracle_release_feedforward_core.tcl
tri_oracle_release_feedforward_core
report_timing -view setup_slow > $out/unfrozen_before_setup.rpt
opt_design -pre_cts -report_dir $out/unfrozen_pre_cts_reports
place_detail
check_place > $out/unfrozen_placement_check.rpt
source syn/tri_oracle_require_clean_placement.tcl
tri_oracle_require_clean_placement $out/unfrozen_placement_check.rpt
report_timing -view setup_slow > $out/unfrozen_prects_setup_slow.rpt
# Optimization may prune the typical view. Restore the original full set.
set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}
report_timing -view setup_typ > $out/unfrozen_prects_setup_typ.rpt
write_db $out/placed_unfrozen.db
puts "TRI_ORACLE_FEEDFORWARD_PLACEMENT_REPAIR_FINISHED"
exit
