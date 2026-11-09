# Existing slew/glitch violations need explicit design-rule optimization;
# automatic recovery can skip them when they did not degrade during hold fixing.
source syn/tri_oracle_physical_config.tcl
read_db $out/routed.db
source syn/tri_oracle_feedforward_postroute_settings.tcl
set tag postroute_si_fix
if {![file isdirectory $out/${tag}_input_exact.db]} {
    error "The independently fingerprinted exact input backup is required"
}
# The measured violations are on data nets. Preserve the repaired clock tree
# and sequential-cell sizes; clocks and their actual constraints remain checked.
set_db opt_post_route_fix_clock_drv false
set_db opt_resize_flip_flops false
set_db opt_post_route_fix_glitch true
set_db si_delay_enable_report true
set_db si_glitch_enable_report true
set_db opt_drv_margin 0.0
time_design -post_route -drv_report -expanded_views \
    -report_dir $out/${tag}_before -report_prefix $tag
opt_design -post_route -drv -expanded_views \
    -report_dir $out/${tag}_reports -report_prefix $tag
check_place > $out/${tag}_placement.rpt
source syn/tri_oracle_require_clean_placement.tcl
tri_oracle_require_clean_placement $out/${tag}_placement.rpt
connect_global_net VDD -type pg_pin -pin_base_name VDD -all
connect_global_net VSS -type pg_pin -pin_base_name VSS -all
write_db -rc_extract $out/routed.db
puts "TRI_ORACLE_FEEDFORWARD_SI_REPAIR_CHECKPOINT_WRITTEN"
set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}
report_timing -view setup_slow > $out/${tag}_setup_slow.rpt
report_timing -view setup_typ > $out/${tag}_setup_typ.rpt
report_timing -early -view hold_fast > $out/${tag}_hold_fast.rpt
time_design -post_route -drv_report -expanded_views \
    -report_dir $out/${tag}_after -report_prefix $tag
puts "TRI_ORACLE_FEEDFORWARD_SI_REPAIR_COMMANDS_FINISHED"
exit
