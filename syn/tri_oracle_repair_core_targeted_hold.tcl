# Limit repair to data nets feeding currently failing hold endpoints. The prior
# blanket margin pass was dominated by lack of legal buffer locations.
source syn/tri_oracle_physical_config.tcl
if {$top ne "tri_oracle_memory_compute"} {error "Core-only targeted hold repair"}
set_multi_cpu_usage -local_cpu 18
read_db $out/routed.db
set tag $::env(TRI_ORACLE_PHYSICAL_STAGE)
set backup $out/${tag}_input.db
if {[file exists $backup]} {error "Refusing to overwrite repair input backup"}
write_db -rc_extract $backup
puts "TRI_ORACLE_TARGETED_HOLD_INPUT_CHECKPOINT_WRITTEN"

set paths [report_timing -early -view hold_fast -collection -max_paths 10000 -nworst 1 -max_slack 0]
set path_count [sizeof_collection $paths]
if {$path_count == 0 || $path_count >= 10000} {
    error "Expected a nonempty, bounded set of failing hold paths; got $path_count"
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
        error "Ambiguous endpoint or data net for a failing hold path"
    }
    set endpoint_name [get_object_name $endpoint]
    set net_name [get_object_name $net]
    puts $file "$endpoint_name\t$net_name\t$slack"
    lappend target_nets $net_name
}
close $file
set target_nets [lsort -unique $target_nets]
if {[llength $target_nets] == 0} {error "No negative-slack data nets selected"}
set target_file $out/${tag}_nets.txt
set file [open $target_file w]
foreach net $target_nets {puts $file $net}
close $file
puts "TRI_ORACLE_TARGETED_HOLD_NETS [llength $target_nets] PATHS $path_count"

# The documented overlap mode legalizes inserted cells before engineering-change
# routing. It changes placement freedom, not clocks, uncertainty or I/O budgets.
set_db opt_hold_allow_overlap true
set_db opt_hold_allow_setup_tns_degradation false
set_db opt_hold_target_slack 0.020
set_db opt_post_route_hold_recovery true
set_db opt_post_route_area_reclaim none
opt_design -post_route -hold -include_nets $target_file -hold_violation_report $out/${tag}_remaining -report_dir $out/${tag}_reports
write_db -rc_extract $out/routed.db
puts "TRI_ORACLE_TARGETED_HOLD_OUTPUT_CHECKPOINT_WRITTEN"
report_timing -view setup_slow -check_type setup > $out/postroute_setup.rpt
report_timing -early -view hold_fast > $out/postroute_hold.rpt
check_place > $out/targeted_hold_placement.rpt
check_drc -out_file $out/route_drc.rpt
check_connectivity -type all -out_file $out/route_connectivity.rpt
puts "TRI_ORACLE_CORE_TARGETED_HOLD_COMMANDS_FINISHED"
exit
