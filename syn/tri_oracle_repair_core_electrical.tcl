# Repair the measured capacitance/transition violations without changing clocks,
# I/O constraints, flip-flop sizes or the explicit feedback hold-delay cells.
source syn/tri_oracle_physical_config.tcl
source syn/tri_oracle_require_clean_placement.tcl
if {$top ne "tri_oracle_memory_compute"} {error "Core-only electrical repair"}
set_multi_cpu_usage -local_cpu 18
read_db $out/routed.db
set tag $::env(TRI_ORACLE_PHYSICAL_STAGE)
set backup $out/${tag}_input.db
if {[file exists $backup]} {error "Refusing to overwrite electrical input backup"}
write_db -rc_extract $backup

set delays [get_db insts *TRI_FEEDBACK_HOLD*]
if {[llength $delays] != 71} {error "Expected the 71 qualified feedback delay instances"}
set protected [dict create]
foreach inst $delays {
    set name [get_db $inst .name]
    set cell [get_db $inst .base_cell.name]
    if {$cell ne "DEL100D1BWP12T40P140"} {error "Unexpected feedback cell $name: $cell"}
    dict set protected $name $cell
    set_db $inst .dont_touch true
    if {![get_db $inst .dont_touch]} {error "Failed to protect feedback cell $name"}
}
set_db opt_resize_flip_flops false
set_db opt_post_route_area_reclaim none
set_db opt_post_route_allow_overlap false
set_db opt_post_route_fix_si_transitions true
set_db opt_post_route_report_si_transitions true
set file [open $out/${tag}_settings.rpt w]
foreach attribute {opt_resize_flip_flops opt_post_route_area_reclaim opt_post_route_allow_overlap opt_post_route_fix_si_transitions opt_post_route_report_si_transitions} {
    puts $file "$attribute: [get_db $attribute]"
}
puts $file "protected_feedback_delay_cells: [dict size $protected]"
close $file
report_constraint -all_violators -drv_violation_type {max_capacitance max_transition} -view setup_slow > $out/${tag}_electrical_before.rpt
puts "TRI_ORACLE_CORE_ELECTRICAL_REPAIR_STARTED"
opt_design -post_route -drv -report_dir $out/${tag}_reports -report_prefix $tag
set remaining [get_db insts *TRI_FEEDBACK_HOLD*]
if {[llength $remaining] != [dict size $protected]} {error "Feedback delay count changed"}
foreach inst $remaining {
    # Compare literal names instead of treating indexed hierarchy as a pattern.
    set name [get_db $inst .name]
    if {![dict exists $protected $name] || [get_db $inst .base_cell.name] ne [dict get $protected $name] || ![get_db $inst .dont_touch]} {
        error "Feedback delay identity/protection changed: $name"
    }
}
check_place > $out/${tag}_placement.rpt
puts "TRI_ORACLE_CORE_ELECTRICAL_PLACEMENT_PASS [tri_oracle_require_clean_placement $out/${tag}_placement.rpt]"
connect_global_net VDD -type pg_pin -pin_base_name VDD -all
connect_global_net VSS -type pg_pin -pin_base_name VSS -all
report_constraint -all_violators -drv_violation_type {max_capacitance max_transition} -view setup_slow > $out/${tag}_electrical_after.rpt
# report_constraint uses base slew even when SI-slew fixing is enabled. Keep the
# separate documented time_design transition report to assess SI-induced slew.
time_design -post_route -drv_report -expanded_views -report_dir $out/${tag}_si_reports -report_prefix $tag
report_timing -view setup_slow -check_type setup > $out/${tag}_setup_slow.rpt
report_timing -view setup_typ -check_type setup > $out/${tag}_setup_typ.rpt
report_timing -early -view hold_fast > $out/${tag}_hold_fast.rpt
check_drc -out_file $out/${tag}_drc.rpt
check_connectivity -type all -out_file $out/${tag}_connectivity.rpt
check_antenna -out_file $out/${tag}_antenna.rpt
write_db -rc_extract $out/routed.db
puts "TRI_ORACLE_CORE_ELECTRICAL_REPAIR_COMMANDS_FINISHED"
exit
