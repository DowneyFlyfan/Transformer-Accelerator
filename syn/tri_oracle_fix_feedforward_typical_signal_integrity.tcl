# The previous optimizer retained only setup_slow, while the complete reports
# still contain typical-view glitches/slews. Use the documented view-subset
# control for this repair, then restore every original view before saving.
source syn/tri_oracle_physical_config.tcl
read_db $out/routed.db
source syn/tri_oracle_feedforward_postroute_settings.tcl
source syn/tri_oracle_require_clean_placement.tcl
set tag postroute_typical_si_fix
if {![file isdirectory $out/${tag}_input_exact.db]} {
    error "An independently fingerprinted exact predecessor backup is required"
}
set delays [get_db insts *TRI_ENDPOINT_HOLD_*]
if {[llength $delays] != 72} {error "Endpoint-delay inventory changed"}
foreach inst $delays {
    if {![get_db $inst .dont_touch]} {error "Endpoint-delay protection is missing"}
}
set_db opt_post_route_fix_clock_drv false
set_db opt_resize_flip_flops false
set_db opt_post_route_fix_glitch true
set_db opt_drv_margin 0.0
set_db si_delay_enable_report true
set_db si_glitch_enable_report true
time_design -post_route -drv_report -expanded_views \
    -report_dir $out/${tag}_before -report_prefix $tag
# This chooses the repair's optimization view; no clock/interface, uncertainty,
# process/library or path constraint is changed. Full-view checks remain gates.
set_analysis_view -setup {setup_typ} -hold {hold_fast}
report_analysis_views -type setup > $out/${tag}_optimization_views.rpt
opt_design -post_route -drv -expanded_views \
    -report_dir $out/${tag}_reports -report_prefix $tag
check_place > $out/${tag}_placement.rpt
tri_oracle_require_clean_placement $out/${tag}_placement.rpt
connect_global_net VDD -type pg_pin -pin_base_name VDD -all
connect_global_net VSS -type pg_pin -pin_base_name VSS -all
set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}
report_analysis_views -type active > $out/${tag}_restored_views.rpt
if {[llength [get_db insts *TRI_ENDPOINT_HOLD_*]] != 72} {error "Optimization changed endpoint-delay inventory"}
write_db -rc_extract $out/routed.db
puts "TRI_ORACLE_FEEDFORWARD_TYPICAL_SI_REPAIR_CHECKPOINT_WRITTEN"
report_timing -view setup_slow > $out/${tag}_setup_slow.rpt
report_timing -view setup_typ > $out/${tag}_setup_typ.rpt
report_timing -early -view hold_fast > $out/${tag}_hold_fast.rpt
time_design -post_route -drv_report -expanded_views \
    -report_dir $out/${tag}_after -report_prefix $tag
puts "TRI_ORACLE_FEEDFORWARD_TYPICAL_SI_REPAIR_COMMANDS_FINISHED"
exit
