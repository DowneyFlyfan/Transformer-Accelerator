# Explicit delay insertion on the remaining short same-flop feedback paths.
# The automatic optimizer left these paths after two bounded failing-net passes.
source syn/tri_oracle_physical_config.tcl
source syn/tri_oracle_require_clean_placement.tcl
if {$top ne "tri_oracle_memory_compute"} {error "Core-only feedback hold repair"}
set_multi_cpu_usage -local_cpu 18
set input_database $out/routed.db
if {[info exists ::env(TRI_ORACLE_FEEDBACK_INPUT_DB)]} {
    set input_database [file normalize $::env(TRI_ORACLE_FEEDBACK_INPUT_DB)]
    if {[string first "$out/" $input_database] != 0} {error "Feedback input must be a project checkpoint"}
}
read_db $input_database
set tag $::env(TRI_ORACLE_PHYSICAL_STAGE)
set backup $out/${tag}_input.db
if {[file exists $backup]} {error "Refusing to overwrite ECO input backup"}
write_db -rc_extract $backup
puts "TRI_ORACLE_FEEDBACK_HOLD_INPUT_CHECKPOINT_WRITTEN"

set paths [report_timing -early -view hold_fast -collection -max_paths 1000 -nworst 1 -max_slack 0]
if {[sizeof_collection $paths] == 0 || [sizeof_collection $paths] >= 1000} {
    error "Expected a bounded, nonempty set of remaining negative hold paths"
}
foreach_in_collection path $paths {
    set launch [get_object_name [get_property $path launching_point]]
    set capture [get_object_name [get_property $path capturing_point]]
    set launch_cell [string range $launch 0 [expr {[string last / $launch]-1}]]
    set capture_cell [string range $capture 0 [expr {[string last / $capture]-1}]]
    if {$launch_cell ne $capture_cell || [string last / $capture] < 0} {
        error "Manual feedback repair does not cover this non-feedback path: $launch -> $capture"
    }
}
# Copy physical endpoint pins before switching from hold to setup analysis.
set targets [copy_collection [get_property $paths capturing_point]]
set names {}
set seen [dict create]
set file [open $out/${tag}_setup_headroom.tsv w]
puts $file "endpoint\tview\tsetup_slack_ns"
foreach_in_collection endpoint $targets {
    set name [get_object_name $endpoint]
    if {[dict exists $seen $name]} {continue}
    dict set seen $name 1
    foreach view {setup_slow setup_typ} {
        set setup [report_timing -view $view -check_type setup -to $endpoint -max_paths 1 -collection]
        if {[sizeof_collection $setup] != 1} {error "Missing $view setup path for feedback endpoint $name"}
        set slack [get_property $setup slack]
        if {$slack < 0.400} {error "Insufficient $view setup headroom at $name: $slack"}
        puts $file "$name\t$view\t$slack"
    }
    lappend names $name
}
close $file
if {[llength $names] == 0 || [llength $names] > 200} {error "Unexpected feedback endpoint count"}
set delay_cell DEL100D1BWP12T40P140
if {[llength [get_db base_cells $delay_cell]] != 1} {error "Required characterized delay cell is absent"}

# Batch logical buffer additions, then legalize and route once. Functional
# equivalence and existing dont-touch/power rules remain enabled.
set_db eco_update_timing false
set_db eco_refine_place false
set_db eco_check_logical_equivalence true
set_db eco_batch_mode true
set results {}
set index 0
set status [catch {
    foreach endpoint $names {
        # -pins is a string argument here. Wrapping an indexed hierarchical
        # name in another Tcl list passes literal braces to this native command.
        # Introduce an unplaced logical cell. Preplacing at a dense feedback
        # sink prevented legalizing seven cells in the previous experiment.
        set result [eco_add_repeater -cells $delay_cell -pins $endpoint -name TRI_FEEDBACK_HOLD_$index -no_place]
        if {[llength $result] != 3} {error "Delay insertion failed at $endpoint: $result"}
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
puts "TRI_ORACLE_FEEDBACK_DELAY_CELLS_INSERTED $index"
place_eco -fix_placed_insts true
check_place > $out/${tag}_preroute_placement.rpt
puts "TRI_ORACLE_FEEDBACK_PREROUTE_PLACEMENT_PASS [tri_oracle_require_clean_placement $out/${tag}_preroute_placement.rpt]"
connect_global_net VDD -type pg_pin -pin_base_name VDD -all
connect_global_net VSS -type pg_pin -pin_base_name VSS -all
route_eco
write_db -rc_extract $out/routed.db
puts "TRI_ORACLE_FEEDBACK_HOLD_OUTPUT_CHECKPOINT_WRITTEN"
report_timing -view setup_slow -check_type setup > $out/postroute_setup.rpt
report_timing -early -view hold_fast > $out/postroute_hold.rpt
check_place > $out/feedback_hold_placement.rpt
check_drc -out_file $out/route_drc.rpt
check_connectivity -type all -out_file $out/route_connectivity.rpt
puts "TRI_ORACLE_CORE_FEEDBACK_HOLD_COMMANDS_FINISHED"
exit
