# Repair only currently negative hold paths. Preserve the original clock,
# interface budgets, uncertainty and complete analysis views.
source syn/tri_oracle_physical_config.tcl
read_db $out/routed.db
source syn/tri_oracle_feedforward_postroute_settings.tcl
set tag postroute_hold_refine
if {![file isdirectory $out/${tag}_input_exact.db]} {
    error "The independently fingerprinted exact input backup is required"
}
set paths [report_timing -early -view hold_fast -collection -max_paths 10000 -nworst 1 -max_slack 0]
set path_count [sizeof_collection $paths]
if {$path_count == 0 || $path_count >= 10000} {
    error "Expected a nonempty bounded negative-hold set; got $path_count"
}
set file [open $out/${tag}_targets.tsv w]
puts $file "endpoint\tnet\thold_slack_ns"
set target_nets {}
foreach_in_collection path $paths {
    set slack [get_property $path slack]
    if {$slack >= 0} {continue}
    set endpoint [get_property $path capturing_point]
    set net [get_nets -of_objects $endpoint]
    if {[sizeof_collection $endpoint] != 1 || [sizeof_collection $net] != 1} {
        error "Ambiguous hold endpoint or data net"
    }
    set name [get_object_name $net]
    puts $file "[get_object_name $endpoint]\t$name\t$slack"
    lappend target_nets $name
}
close $file
set target_nets [lsort -unique $target_nets]
if {[llength $target_nets] == 0} {error "No negative-hold data nets selected"}
set target_file $out/${tag}_nets.txt
set file [open $target_file w]
foreach net $target_nets {puts $file $net}
close $file
puts "TRI_ORACLE_FEEDFORWARD_HOLD_TARGETS [llength $target_nets] PATHS $path_count"

# A stricter local optimizer goal on failing nets only. This does not change
# any timing constraint or add margin to every already-met memory-bank path.
set_db opt_hold_target_slack 0.040
set_db opt_hold_allow_overlap true
set_db opt_hold_allow_setup_tns_degradation false
opt_design -post_route -hold -include_nets $target_file \
    -hold_violation_report $out/${tag}_remaining \
    -report_dir $out/${tag}_reports -report_prefix $tag
check_place > $out/${tag}_placement.rpt
source syn/tri_oracle_require_clean_placement.tcl
tri_oracle_require_clean_placement $out/${tag}_placement.rpt
connect_global_net VDD -type pg_pin -pin_base_name VDD -all
connect_global_net VSS -type pg_pin -pin_base_name VSS -all
# Save before later reporting; the exact predecessor remains in input_exact.db.
write_db -rc_extract $out/routed.db
puts "TRI_ORACLE_FEEDFORWARD_HOLD_REFINEMENT_CHECKPOINT_WRITTEN"
report_timing -early -view hold_fast > $out/${tag}_hold_fast.rpt
report_timing -view setup_slow > $out/${tag}_setup_slow.rpt
puts "TRI_ORACLE_FEEDFORWARD_HOLD_REFINEMENT_COMMANDS_FINISHED"
exit
