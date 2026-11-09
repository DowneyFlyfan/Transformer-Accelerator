# Combined setup/hold repair with noisy-slew fixing enabled across all nets.
# The preceding targeted hold pass excludes unrelated noisy-slew offenders.
# Signal-integrity slew evidence comes from time_design, since this release
# explicitly reports that report_constraint continues to use base slews.
source syn/tri_oracle_physical_config.tcl
source syn/tri_oracle_require_clean_placement.tcl
if {$top ne "tri_oracle_memory_compute"} {error "Core-only signal-integrity/hold repair"}
set_multi_cpu_usage -local_cpu 18
read_db $out/routed.db
set tag $::env(TRI_ORACLE_PHYSICAL_STAGE)
if {[file exists $out/${tag}_input.db]} {error "Refusing to overwrite input backup"}
write_db -rc_extract $out/${tag}_input.db
set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}
set_db enable_ui_precision true
set_db ui_precision_timing 6
set protected [dict create]
foreach inst [get_db insts *TRI_FEEDBACK_HOLD*] {
    if {[get_db $inst .base_cell.name] ne "DEL100D1BWP12T40P140" || ![get_db $inst .dont_touch]} {error "Feedback protection missing"}
    dict set protected [get_db $inst .name] [get_db $inst .base_cell.name]
}
if {[dict size $protected] != 71} {error "Expected 71 protected feedback delays"}
set_db opt_resize_flip_flops false
set_db opt_post_route_area_reclaim none
set_db opt_post_route_allow_overlap true
set_db opt_hold_allow_overlap true
set_db opt_hold_allow_setup_tns_degradation false
# This global pass repairs actual negative hold slack. It does not ask the
# optimizer to add a new margin to hundreds of thousands of already met paths.
# Clock uncertainty and all saved timing constraints remain unchanged.
set_db opt_hold_target_slack 0.000
set_db opt_post_route_hold_recovery true
set_db timing_max_transition_use_si_transition true
set_db opt_post_route_report_si_transitions true
set_db opt_post_route_fix_si_transitions true
time_design -post_route -drv_report -expanded_views -report_dir $out/${tag}_before -report_prefix $tag
# A whole-design pass allows repair of the remaining noisy-slew nets; combining
# setup and hold optimization enables the documented post-route hold recovery.
opt_design -post_route -setup -hold -report_dir $out/${tag}_reports -report_prefix $tag
# Optimization may prune the typical view. Restore the original required view
# set explicitly before direct timing reports and before saving the next layout.
set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}
set remaining [get_db insts *TRI_FEEDBACK_HOLD*]
if {[llength $remaining] != [dict size $protected]} {error "Feedback delay count changed"}
foreach inst $remaining {
    set name [get_db $inst .name]
    if {![dict exists $protected $name] || [get_db $inst .base_cell.name] ne [dict get $protected $name] || ![get_db $inst .dont_touch]} {error "Feedback delay identity/protection changed: $name"}
}
check_place > $out/${tag}_placement.rpt
puts "TRI_ORACLE_CORE_SI_HOLD_PLACEMENT_PASS [tri_oracle_require_clean_placement $out/${tag}_placement.rpt]"
connect_global_net VDD -type pg_pin -pin_base_name VDD -all
connect_global_net VSS -type pg_pin -pin_base_name VSS -all
report_timing -view setup_slow -check_type setup > $out/${tag}_setup_slow.rpt
report_timing -view setup_typ -check_type setup > $out/${tag}_setup_typ.rpt
report_timing -early -view hold_fast > $out/${tag}_hold_fast.rpt
foreach view {setup_slow setup_typ} {
    report_constraint -all_violators -drv_violation_type {max_capacitance max_transition} -view $view > $out/${tag}_base_electrical_${view}.rpt
}
time_design -post_route -drv_report -expanded_views -report_dir $out/${tag}_after -report_prefix $tag
check_drc -out_file $out/${tag}_drc.rpt
check_connectivity -type all -out_file $out/${tag}_connectivity.rpt
check_antenna -out_file $out/${tag}_antenna.rpt
write_db -rc_extract $out/routed.db
puts "TRI_ORACLE_CORE_SI_HOLD_REPAIR_COMMANDS_FINISHED"
exit
