# Insert characterized delay cells only on admitted short data paths, after
# checking both setup views at every endpoint. Keep every timing constraint.
source syn/tri_oracle_physical_config.tcl
read_db $out/routed.db
source syn/tri_oracle_feedforward_postroute_settings.tcl
source syn/tri_oracle_endpoint_hold_policy.tcl
source syn/tri_oracle_require_clean_placement.tcl
set tag postroute_endpoint_hold
if {[info exists ::env(TRI_ORACLE_PHYSICAL_STAGE)]} {
    if {$::env(TRI_ORACLE_PHYSICAL_STAGE) ni {postroute_endpoint_hold postroute_final_input_hold postroute_short_input_hold postroute_short_eco_hold}} {error "Unexpected endpoint-repair stage"}
    set tag $::env(TRI_ORACLE_PHYSICAL_STAGE)
}
if {![file isdirectory $out/${tag}_input_exact.db]} {
    error "An independently fingerprinted exact predecessor backup is required"
}
set existing_delays [get_db insts *TRI_ENDPOINT_HOLD_*]
set existing_names {}
foreach inst $existing_delays {
    if {![get_db $inst .dont_touch]} {error "Existing endpoint-delay protection is missing"}
    lappend existing_names [get_db $inst .name]
}
if {$tag in {postroute_final_input_hold postroute_short_input_hold postroute_short_eco_hold} && [llength $existing_names] != 72} {error "Expected all72 previously inserted endpoint delays"}
set delay_cell DEL100D1BWP12T40P140
if {$tag in {postroute_short_input_hold postroute_short_eco_hold}} {set delay_cell DEL025D1BWP12T40P140}
set paths [report_timing -early -view hold_fast -collection -max_paths 1000 -nworst 1 -max_slack 0]
set count [sizeof_collection $paths]
if {$count == 0 || $count >= 1000} {error "Expected a bounded nonempty negative hold set: $count"}
set seen [dict create]
set file [open $out/${tag}_targets.tsv w]
puts $file "launch\tendpoint\thold_slack_ns\tclassification"
foreach_in_collection path $paths {
    set launch [get_object_name [get_property $path launching_point]]
    set capture [get_object_name [get_property $path capturing_point]]
    set slack [get_property $path slack]
    set kind [tri_oracle_endpoint_hold_kind $launch $capture $slack]
    dict set seen $capture 1
    puts $file "$launch\t$capture\t$slack\t$kind"
}
close $file
if {[dict size $seen] == 0 || [dict size $seen] > 200} {error "Unexpected endpoint count"}
# Preserve native pin objects before switching the timing check type/views.
set targets [copy_collection [get_property $paths capturing_point]]
set names {}
set checked [dict create]
set file [open $out/${tag}_setup_headroom.tsv w]
puts $file "endpoint\tview\tsetup_slack_ns\tdelay_cell"
foreach_in_collection endpoint $targets {
    set name [get_object_name $endpoint]
    if {[dict exists $checked $name]} {continue}
    dict set checked $name 1
    set slacks [dict create]
    foreach view {setup_slow setup_typ} {
        set setup [report_timing -view $view -check_type setup -to $endpoint -max_paths 1 -collection]
        if {[sizeof_collection $setup] != 1} {error "Missing $view setup path at $name"}
        set slack [get_property $setup slack]
        dict set slacks $view $slack
        puts $file "$name\t$view\t$slack\t$delay_cell"
        flush $file
    }
    tri_oracle_endpoint_hold_headroom $name $slacks $delay_cell
    lappend names $name
}
close $file
if {[llength $names] != [dict size $seen]} {error "Endpoint collection changed during setup admission"}
if {[llength [get_db base_cells $delay_cell]] != 1} {error "Characterized delay cell is absent"}
set_db eco_update_timing false
set_db eco_refine_place false
set_db eco_check_logical_equivalence true
set_db eco_batch_mode true
set results {}
set index [tri_oracle_endpoint_hold_next_index $existing_names]
set status [catch {
    foreach endpoint $names {
        set name TRI_ENDPOINT_HOLD_$index
        if {[llength [get_db insts $name]] != 0} {error "Delay instance already exists: $name"}
        # -pins takes a string; do not add literal Tcl braces to indexed names.
        set result [eco_add_repeater -cells $delay_cell -pins $endpoint -name $name -no_place]
        if {[llength $result] != 3} {error "Unexpected delay insertion result at $endpoint: $result"}
        lappend results [list $endpoint {*}$result]
        incr index
    }
} message options]
set_db eco_batch_mode false
if {$status} {return -options $options $message}
set file [open $out/${tag}_insertions.tsv w]
puts $file "endpoint\tinstance\tinput_net\toutput_net"
foreach result $results {puts $file [join $result \t]}
close $file
puts "TRI_ORACLE_FEEDFORWARD_ENDPOINT_DELAYS_INSERTED [llength $results]"
place_eco -fix_placed_insts true
check_place > $out/${tag}_placement.rpt
tri_oracle_require_clean_placement $out/${tag}_placement.rpt
connect_global_net VDD -type pg_pin -pin_base_name VDD -all
connect_global_net VSS -type pg_pin -pin_base_name VSS -all
set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}
# Complete the two changed connections geometrically. The native ECO command
# did not emit the standalone timing-file reader trace in the prior attempt.
# Full timing and signal-integrity analysis remain enabled for qualification.
set saved_timing_driven [get_db route_with_timing_driven]
set saved_si_driven [get_db route_with_si_driven]
set_db route_with_timing_driven false
set_db route_with_si_driven false
set router_report $out/${tag}_router.rpt
if {![catch {file lstat $router_report ignored}]} {error "Refusing existing endpoint router trace"}
set status [catch {
    redirect $router_report {
        puts "TRI_ORACLE_LOCAL_ECO_MODE [get_db route_with_timing_driven] [get_db route_with_si_driven]"
        route_eco
    } -tee
} message options]
set_db route_with_timing_driven $saved_timing_driven
set_db route_with_si_driven $saved_si_driven
tri_oracle_reset_router_timing
if {$status} {return -options $options $message}
set geometry [tri_oracle_require_geometric_eco_trace $router_report]
set file [open $out/${tag}_routing_evidence.rpt w]
puts $file $geometry
close $file
puts "TRI_ORACLE_ENDPOINT_GEOMETRIC_ECO_VERIFIED"
foreach result $results {
    set name [lindex $result 1]
    set inst [get_db insts $name]
    if {[llength $inst] != 1 || [get_db $inst .name] ne $name} {error "Delay instance missing: $name"}
    set_db $inst .dont_touch true
}
if {[llength [get_db insts *TRI_ENDPOINT_HOLD_*]] != [llength $existing_names]+[llength $results]} {
    error "Endpoint-delay inventory does not match preserved and newly inserted cells"
}
set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}
write_db -rc_extract $out/routed.db
puts "TRI_ORACLE_FEEDFORWARD_ENDPOINT_HOLD_CHECKPOINT_WRITTEN"
set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}
report_timing -view setup_slow > $out/${tag}_setup_slow.rpt
report_timing -view setup_typ > $out/${tag}_setup_typ.rpt
report_timing -early -view hold_fast > $out/${tag}_hold_fast.rpt
puts "TRI_ORACLE_FEEDFORWARD_ENDPOINT_HOLD_COMMANDS_FINISHED"
exit
