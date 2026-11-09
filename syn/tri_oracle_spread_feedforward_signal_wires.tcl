# Explicitly spread the freshly reported victim nets. The previous detail-route
# repair cleared geometry/antenna checks but left their noisy slews unchanged.
source syn/tri_oracle_physical_config.tcl
set_multi_cpu_usage -local_cpu 20
read_db $out/routed.db
source syn/tri_oracle_feedforward_postroute_settings.tcl
source syn/tri_oracle_signal_repair_targets.tcl
source syn/tri_oracle_require_clean_placement.tcl
set tag postroute_wire_spread
if {[info exists ::env(TRI_ORACLE_PHYSICAL_STAGE)]} {
    if {$::env(TRI_ORACLE_PHYSICAL_STAGE) ni {postroute_wire_spread postroute_wire_spread_timed}} {error "Unexpected wire-repair stage"}
    set tag $::env(TRI_ORACLE_PHYSICAL_STAGE)
}
if {![file isdirectory $out/${tag}_input_exact.db]} {
    error "An independently fingerprinted exact predecessor backup is required"
}
set delays [get_db insts *TRI_ENDPOINT_HOLD_*]
if {[llength $delays] != 72} {error "Endpoint-delay inventory changed"}
foreach inst $delays {
    if {![get_db $inst .dont_touch]} {error "Endpoint-delay protection is missing"}
}
set_db si_delay_enable_report true
set_db si_glitch_enable_report true
time_design -post_route -drv_report -expanded_views \
    -report_dir $out/${tag}_before -report_prefix $tag
set names [tri_oracle_route_slew_targets [exec gzip -dc $out/${tag}_before/${tag}.tran.gz]]
if {[llength $names] == 0 || [llength $names] > 100} {error "Expected bounded nonempty noisy-slew targets"}
set objects {}
foreach name $names {
    if {[regexp {[*?]} $name]} {error "Ambiguous native net pattern: $name"}
    set net [get_db nets $name]
    if {[llength $net] != 1 || [get_db $net .name] ne $name} {error "Missing or ambiguous victim net: $name"}
    tri_oracle_route_require_data_net $name [get_db $net .is_clock] [get_db $net .is_power] [get_db $net .is_ground]
    lappend objects $net
}
set_db route_with_timing_driven true
set_db route_with_si_driven true
set_db route_detail_post_route_wire_widen none
set_db route_detail_post_route_spread_wire 1
# Per installed documentation, spreading considers worst-setup slack LESS than
# this local eligibility threshold. This includes the selected victim set; it
# changes no clock, interface, path or process constraint.
set_db route_detail_min_slack_for_opt_wire 10.0
set file [open $out/${tag}_settings.rpt w]
foreach attribute {route_with_timing_driven route_with_si_driven route_detail_post_route_wire_widen route_detail_post_route_spread_wire route_detail_min_slack_for_opt_wire} {
    puts $file "$attribute: [get_db $attribute]"
}
puts $file "selected_data_nets: [llength $names]"
close $file
set file [open $out/${tag}_nets.txt w]
foreach name $names {puts $file $name}
close $file
set timing [tri_oracle_export_router_timing $out/${tag}_router.tif]
set router_report $out/${tag}_router.rpt
if {![catch {file lstat $router_report ignored}]} {error "Refusing an existing router-consumption report"}
deselect_obj -all
foreach net $objects {select_obj $net}
set_db route_selected_net_only true
puts "TRI_ORACLE_FEEDFORWARD_WIRE_SPREAD_TARGETS [llength $names]"
set status [catch {redirect $router_report {route_design -selected -wire_opt} -tee} message options]
set_db route_selected_net_only false
deselect_obj -all
tri_oracle_reset_router_timing
if {$status} {return -options $options $message}
set consumed [tri_oracle_require_router_timing_trace $router_report $timing]
set file [open $out/${tag}_timing_consumption.rpt w]
puts $file $consumed
close $file
puts "TRI_ORACLE_ROUTER_TIMING_CONSUMPTION_VERIFIED [dict get $consumed ports] [dict get $consumed instances]"
connect_global_net VDD -type pg_pin -pin_base_name VDD -all
connect_global_net VSS -type pg_pin -pin_base_name VSS -all
check_place > $out/${tag}_placement.rpt
tri_oracle_require_clean_placement $out/${tag}_placement.rpt
if {[llength [get_db insts *TRI_ENDPOINT_HOLD_*]] != 72} {error "Wire optimization changed delay inventory"}
set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}
write_db -rc_extract $out/routed.db
puts "TRI_ORACLE_FEEDFORWARD_WIRE_SPREAD_CHECKPOINT_WRITTEN"
report_timing -view setup_slow > $out/${tag}_setup_slow.rpt
report_timing -view setup_typ > $out/${tag}_setup_typ.rpt
report_timing -early -view hold_fast > $out/${tag}_hold_fast.rpt
check_drc -out_file $out/${tag}_drc.rpt
check_antenna -out_file $out/${tag}_antenna.rpt
check_connectivity -type all -out_file $out/${tag}_connectivity.rpt
time_design -post_route -drv_report -expanded_views \
    -report_dir $out/${tag}_after -report_prefix $tag
puts "TRI_ORACLE_FEEDFORWARD_WIRE_SPREAD_COMMANDS_FINISHED"
exit
