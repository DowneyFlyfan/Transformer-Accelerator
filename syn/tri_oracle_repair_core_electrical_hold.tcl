# Finish the five measured cross-corner capacitance failures, then repair hold
# paths shortened by the preceding electrical optimization. No constraint edits.
source syn/tri_oracle_physical_config.tcl
source syn/tri_oracle_require_clean_placement.tcl
if {$top ne "tri_oracle_memory_compute"} {error "Core-only post-electrical hold repair"}
set_multi_cpu_usage -local_cpu 18
read_db $out/routed.db
set tag $::env(TRI_ORACLE_PHYSICAL_STAGE)
if {[file exists $out/${tag}_input.db]} {error "Refusing to overwrite input backup"}
write_db -rc_extract $out/${tag}_input.db
set protected [dict create]
foreach inst [get_db insts *TRI_FEEDBACK_HOLD*] {
    if {[get_db $inst .base_cell.name] ne "DEL100D1BWP12T40P140" || ![get_db $inst .dont_touch]} {error "Feedback protection missing"}
    dict set protected [get_db $inst .name] [get_db $inst .base_cell.name]
}
if {[dict size $protected] != 71} {error "Expected 71 protected feedback cells"}

# The combined-view time_design report identifies these five BUFFD0 outputs as
# real max-capacitance violations, even though their displayed slack is -0.000.
set stronger BUFFD1BWP12T40P140
if {[llength [get_db base_cells $stronger]] != 1} {error "Required stronger buffer is absent"}
set_db eco_update_timing false
set_db eco_refine_place true
set_db eco_batch_mode false
set_db eco_check_logical_equivalence true
set resized {}
foreach name {FE_PHC549_load_data_673 FE_PHC824_load_data_656 FE_PHC128650_load_data_253 FE_PHC294887_load_data_1234 FE_PHC1096_load_data_1636} {
    set inst [get_db insts $name]
    if {[llength $inst] != 1 || [get_db $inst .base_cell.name] ne "BUFFD0BWP12T40P140"} {error "Unexpected capacitance repair input $name"}
    eco_update_cell -insts $name -cells $stronger
    if {[get_db $inst .base_cell.name] ne $stronger} {error "Capacitance buffer update failed: $name"}
    lappend resized $name
}
check_place > $out/${tag}_resized_placement.rpt
puts "TRI_ORACLE_ELECTRICAL_HOLD_RESIZED_PLACEMENT_PASS [tri_oracle_require_clean_placement $out/${tag}_resized_placement.rpt]"
route_eco

set paths [report_timing -early -view hold_fast -collection -max_paths 10000 -nworst 1 -max_slack 0]
set count [sizeof_collection $paths]
if {$count == 0 || $count >= 10000} {error "Expected a bounded nonempty hold violation set: $count"}
set nets {}
set file [open $out/${tag}_targets.tsv w]
puts $file "endpoint\tnet\thold_slack_ns"
foreach_in_collection path $paths {
    set slack [get_property $path slack]
    if {$slack >= 0} {continue}
    set endpoint [get_property $path capturing_point]
    set net [get_nets -of_objects $endpoint]
    if {[sizeof_collection $endpoint] != 1 || [sizeof_collection $net] != 1} {error "Ambiguous failing hold endpoint/net"}
    set name [get_object_name $net]
    puts $file "[get_object_name $endpoint]\t$name\t$slack"
    lappend nets $name
}
close $file
set nets [lsort -unique $nets]
if {[llength $nets] == 0} {error "No negative hold data nets selected"}
set file [open $out/${tag}_nets.txt w]
foreach net $nets {puts $file $net}
close $file
puts "TRI_ORACLE_ELECTRICAL_HOLD_TARGETS nets=[llength $nets] paths=$count"
set_db opt_resize_flip_flops false
set_db opt_hold_allow_overlap true
set_db opt_hold_allow_setup_tns_degradation false
set_db opt_hold_target_slack 0.020
set_db opt_post_route_hold_recovery true
set_db opt_post_route_area_reclaim none
set_db timing_max_transition_use_si_transition true
set_db opt_post_route_report_si_transitions true
set_db opt_post_route_fix_si_transitions true
opt_design -post_route -hold -include_nets $out/${tag}_nets.txt -hold_violation_report $out/${tag}_remaining -report_dir $out/${tag}_reports
set remaining [get_db insts *TRI_FEEDBACK_HOLD*]
if {[llength $remaining] != [dict size $protected]} {error "Feedback delay count changed"}
foreach inst $remaining {
    set name [get_db $inst .name]
    if {![dict exists $protected $name] || [get_db $inst .base_cell.name] ne [dict get $protected $name] || ![get_db $inst .dont_touch]} {error "Feedback delay identity/protection changed: $name"}
}
check_place > $out/${tag}_placement.rpt
puts "TRI_ORACLE_ELECTRICAL_HOLD_PLACEMENT_PASS [tri_oracle_require_clean_placement $out/${tag}_placement.rpt]"
connect_global_net VDD -type pg_pin -pin_base_name VDD -all
connect_global_net VSS -type pg_pin -pin_base_name VSS -all
report_timing -view setup_slow -check_type setup > $out/${tag}_setup_slow.rpt
report_timing -view setup_typ -check_type setup > $out/${tag}_setup_typ.rpt
report_timing -early -view hold_fast > $out/${tag}_hold_fast.rpt
foreach view {setup_slow setup_typ} {
    report_constraint -all_violators -drv_violation_type {max_capacitance max_transition} -view $view > $out/${tag}_electrical_${view}.rpt
}
time_design -post_route -drv_report -expanded_views -report_dir $out/${tag}_si_reports -report_prefix $tag
check_drc -out_file $out/${tag}_drc.rpt
check_connectivity -type all -out_file $out/${tag}_connectivity.rpt
check_antenna -out_file $out/${tag}_antenna.rpt
write_db -rc_extract $out/routed.db
puts "TRI_ORACLE_CORE_ELECTRICAL_HOLD_REPAIR_COMMANDS_FINISHED"
exit
