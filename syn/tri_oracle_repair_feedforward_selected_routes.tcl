# Repair fresh reported data nets using the supplied rules and diode model.
# SI victim nets receive extra preferred spacing; no design rule is relaxed.
source syn/tri_oracle_physical_config.tcl
read_db $out/routed.db
source syn/tri_oracle_feedforward_postroute_settings.tcl
source syn/tri_oracle_require_clean_placement.tcl
source syn/tri_oracle_route_repair_targets.tcl
source syn/tri_oracle_signal_repair_targets.tcl
set tag postroute_selected_route_fix
if {![file isdirectory $out/${tag}_input_exact.db]} {
    error "An independently fingerprinted exact predecessor backup is required"
}
set_db si_delay_enable_report true
set_db si_glitch_enable_report true
check_drc -out_file $out/${tag}_drc_before.rpt
check_antenna -out_file $out/${tag}_antenna_before.rpt
time_design -post_route -drv_report -expanded_views \
    -report_dir $out/${tag}_before -report_prefix $tag
set file [open $out/${tag}_drc_before.rpt r]
set geometry [tri_oracle_route_drc_targets [read $file]]
close $file
set file [open $out/${tag}_antenna_before.rpt r]
set antenna [tri_oracle_route_antenna_targets [read $file]]
close $file
set slew [tri_oracle_route_slew_targets [exec gzip -dc $out/${tag}_before/${tag}.tran.gz]]
set capacitance [tri_oracle_route_capacitance_targets [exec gzip -dc $out/${tag}_before/${tag}.cap.gz]]
set glitch [tri_oracle_route_glitch_targets [exec gzip -dc $out/${tag}_before/${tag}.SI_Glitches.rpt.gz]]
set signal [lsort -unique [concat $slew $capacitance $glitch]]
set names [lsort -unique [concat $geometry $antenna $signal]]
if {[llength $names] == 0 || [llength $names] > 600} {error "Unexpected selected-route repair target count"}
set objects {}
foreach name $names {
    if {[regexp {[*?]} $name]} {error "Ambiguous native net pattern: $name"}
    set net [get_db nets $name]
    if {[llength $net] != 1 || [get_db $net .name] ne $name} {error "Missing or ambiguous target net: $name"}
    tri_oracle_route_require_data_net $name [get_db $net .is_clock] [get_db $net .is_power] [get_db $net .is_ground]
    lappend objects $net
}
set delays [get_db insts *TRI_ENDPOINT_HOLD_*]
if {[llength $delays] != 72} {error "The qualified endpoint-delay inventory changed"}
foreach inst $delays {
    if {![get_db $inst .dont_touch]} {error "Endpoint delay protection is missing"}
}
set diode ANTENNABWP12T40P140
if {[llength [get_db base_cells $diode]] != 1} {error "Characterized antenna diode is absent"}
set_db route_detail_fix_antenna true
set_db route_antenna_diode_insertion true
set_db route_antenna_cell_name $diode
reset_db route_detail_end_iteration
set_db route_detail_search_and_repair true
set_db route_with_timing_driven true
set_db route_with_si_driven true
foreach name $signal {
    set_route_attributes -nets $name -si_post_route_fix true -preferred_extra_space_tracks 2
}
set file [open $out/${tag}_targets.tsv w]
puts $file "net\tgeometry\tantenna\tsignal_integrity"
foreach name $names {
    puts $file "$name\t[expr {$name in $geometry}]\t[expr {$name in $antenna}]\t[expr {$name in $signal}]"
}
close $file
set file [open $out/${tag}_settings.rpt w]
foreach attribute {route_detail_fix_antenna route_antenna_diode_insertion route_antenna_cell_name route_detail_end_iteration route_detail_search_and_repair route_with_timing_driven route_with_si_driven} {
    puts $file "$attribute: [get_db $attribute]"
}
puts $file "signal_victim_preferred_extra_space_tracks: 2"
puts $file "selected_data_nets: [llength $names]"
close $file
deselect_obj -all
foreach net $objects {select_obj $net}
puts "TRI_ORACLE_FEEDFORWARD_SELECTED_ROUTE_TARGETS [llength $names]"
route_detail -selected
deselect_obj -all
connect_global_net VDD -type pg_pin -pin_base_name VDD -all
connect_global_net VSS -type pg_pin -pin_base_name VSS -all
check_place > $out/${tag}_placement.rpt
tri_oracle_require_clean_placement $out/${tag}_placement.rpt
if {[llength [get_db insts *TRI_ENDPOINT_HOLD_*]] != 72} {error "Routing changed the endpoint-delay inventory"}
write_db -rc_extract $out/routed.db
puts "TRI_ORACLE_FEEDFORWARD_SELECTED_ROUTE_CHECKPOINT_WRITTEN"
set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}
report_timing -view setup_slow > $out/${tag}_setup_slow.rpt
report_timing -view setup_typ > $out/${tag}_setup_typ.rpt
report_timing -early -view hold_fast > $out/${tag}_hold_fast.rpt
check_drc -out_file $out/${tag}_drc_after.rpt
check_antenna -out_file $out/${tag}_antenna_after.rpt
check_connectivity -type all -out_file $out/${tag}_connectivity.rpt
time_design -post_route -drv_report -expanded_views \
    -report_dir $out/${tag}_after -report_prefix $tag
puts "TRI_ORACLE_FEEDFORWARD_SELECTED_ROUTE_REPAIR_COMMANDS_FINISHED"
exit
