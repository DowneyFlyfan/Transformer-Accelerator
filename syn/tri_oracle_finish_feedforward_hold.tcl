source syn/tri_oracle_physical_config.tcl
read_db $out/routed_before_optimization.db
source syn/tri_oracle_feedforward_postroute_settings.tcl
set tag postroute_hold_pass
opt_design -post_route -hold -report_dir $out/${tag}_reports -report_prefix $tag
check_place > $out/${tag}_placement.rpt
source syn/tri_oracle_require_clean_placement.tcl
tri_oracle_require_clean_placement $out/${tag}_placement.rpt
connect_global_net VDD -type pg_pin -pin_base_name VDD -all
connect_global_net VSS -type pg_pin -pin_base_name VSS -all
# Save the full-design legal hold-repair checkpoint before additional reports.
# Original complete analysis views are restored in the next process/qualifier.
write_db -rc_extract $out/${tag}.db
puts "TRI_ORACLE_FEEDFORWARD_HOLD_CHECKPOINT_WRITTEN"
report_timing -early -view hold_fast > $out/${tag}_hold_fast.rpt
report_timing -view setup_slow > $out/${tag}_setup_slow.rpt
puts "TRI_ORACLE_FEEDFORWARD_HOLD_PASS_COMMANDS_FINISHED"
exit
