# Fresh single-corner post-clock timing with explicit propagated clock timing.
# The one-core profile qualifies this reporting method before the full parent.
# Full-parent acceptance always requires all20 complete cores and600 memories.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set input $::env(TRI_ORACLE_PARENT_DIAGNOSTIC_CHECKPOINT)
set out $::env(TRI_ORACLE_PARENT_DIAGNOSTIC_DIRECTORY)
set view $::env(TRI_ORACLE_PARENT_DIAGNOSTIC_VIEW)
set profile full_parent
if {[info exists ::env(TRI_ORACLE_CLOCK_DIAGNOSTIC_PROFILE)]} {set profile $::env(TRI_ORACLE_CLOCK_DIAGNOSTIC_PROFILE)}
switch $profile {
    full_parent {
        set expected_top tri_oracle_predicted_fabric
        set expected_cores 20
        set memory_counts {360 40 200}
    }
    one_core {
        set expected_top tri_oracle_preserved_placement_probe21
        set expected_cores 1
        set memory_counts {18 2 8}
    }
    default {error "PARENT_POSTCLOCK55_UNKNOWN_PROFILE"}
}
if {$view ni {setup_slow setup_typ hold_fast}} {error "PARENT_POSTCLOCK55_UNKNOWN_VIEW"}
set_multi_cpu_usage -local_cpu 4
read_db $input
set_multi_cpu_usage -local_cpu 4
if {[get_db current_design .name] ne $expected_top} {
    error "PARENT_POSTCLOCK55_WRONG_PARENT"
}
# The same selected process corner is supplied in both required view slots;
# the explicit setup/hold query below selects its intended timing check.
set_analysis_view -setup [list $view] -hold [list $view]
set_db enable_ui_precision true
set_db ui_precision_timing 6
set_db timing_analysis_type ocv
set_db timing_analysis_cppr both
set_db delaycal_enable_si true
unflatten_ilm
set_ilm_type -model si
flatten_ilm
set counts [dict create]
foreach instance [get_db insts] {
    set name [get_db $instance .name]
    if {$profile eq "one_core"} {
        if {![string match {core0/*} $name]} {continue}
        set prefix core0
    } else {
        if {![regexp {^(.*clusters\[[0-9]+\]\.unit/cluster/implementation/cores\[[0-9]+\])/(.+)$} $name -> prefix local]} {continue}
    }
    dict incr counts $prefix
}
if {[dict size $counts] != $expected_cores} {error "PARENT_POSTCLOCK55_INCOMPLETE_CORE_SET"}
set file [open $out/core_counts.tsv w]
puts $file "core\tfull_original_cells"
dict for {prefix count} $counts {
    if {$count != 94471} {error "PARENT_POSTCLOCK55_INCOMPLETE_ORIGINAL_CORE: $prefix $count"}
    puts $file "$prefix\t$count"
}
close $file
foreach master {TS5N28HPCPSVTA32X128M2FW TS5N28HPCPSVTA512X64M4F TS6N28HPCPSVTA16X128M2F} expected $memory_counts {
    if {[llength [get_db insts -if ".base_cell.name == $master"]] != $expected} {
        error "PARENT_POSTCLOCK55_WRONG_MEMORY_COUNT: $master"
    }
}
report_ilm_status > $out/model_status.rpt
if {[sizeof_collection [get_clocks core_clock]] != 1} {error "PARENT_POSTCLOCK55_MISSING_ACTUAL_CLOCK"}
source $root/syn/tri_oracle_require_preserved_clock_boundaries.tcl
tri_oracle_require_preserved_clock_boundaries $out/clock_boundaries.tsv $counts
set clocks [get_db clocks core_clock]
if {[llength $clocks] != 1} {error "PARENT_POSTCLOCK55_MISSING_WAVEFORM_OBJECT"}
set was_propagated [get_db $clocks .is_propagated]
set period [get_db $clocks .period]
if {abs($period-1.72414) > 0.00001} {error "PARENT_POSTCLOCK55_CHANGED_CLOCK_PERIOD: $period"}
set_propagated_clock [get_clocks core_clock]
if {![get_db $clocks .is_propagated]} {error "PARENT_POSTCLOCK55_IDEAL_WAVEFORM"}
time_design -post_cts -drv_report -expanded_views -report_dir $out/timing -report_prefix corner
# Native optimization/reporting may reapply a mode; make the assertion explicit
# immediately before accepting detailed clock and register-path timing.
set_propagated_clock [get_clocks core_clock]
if {![get_db $clocks .is_propagated]} {error "PARENT_POSTCLOCK55_LOST_PROPAGATION"}
set file [open $out/clock_propagation.tsv w]
puts $file "view\tprofile\tclock_period_ns\tpropagated_before\tpropagated_after\toriginal_cores"
puts $file "$view\t$profile\t$period\t$was_propagated\t[get_db $clocks .is_propagated]\t$expected_cores"
close $file
set_db timing_analysis_check_type [expr {$view eq "hold_fast" ? "hold" : "setup"}]
report_clocks -view $view -hierarchy -description -source_insertion > $out/clocks.rpt
set command [list report_timing -view $view -max_paths 1 -max_slack 100 -path_type full_clock]
if {$view eq "hold_fast"} {lappend command -early} else {lappend command -check_type setup}
eval $command > $out/worst_path.rpt
set paths [eval $command -collection]
if {[sizeof_collection $paths] != 1} {error "PARENT_POSTCLOCK55_MISSING_ACTUAL_PATH: $view"}
set file [open $out/slack_properties.tsv w]
puts $file "view\tslack_ns\tstartpoint\tendpoint"
foreach_in_collection path $paths {
    puts $file "$view\t[get_property $path slack]\t[get_object_name [get_property $path launching_point]]\t[get_object_name [get_property $path capturing_point]]"
}
close $file
# A register-to-register path independently verifies nonzero propagated clock
# network latency, even when the global worst path is an interface path.
set register_command [concat $command {-skip_io_paths}]
eval $register_command > $out/register_clock_path.rpt
set register_paths [eval $register_command -collection]
if {[sizeof_collection $register_paths] != 1} {error "PARENT_POSTCLOCK55_NO_REGISTER_PATH"}
set file [open $out/register_slack_properties.tsv w]
puts $file "view\tslack_ns\tstartpoint\tendpoint"
foreach_in_collection path $register_paths {
    puts $file "$view\t[get_property $path slack]\t[get_object_name [get_property $path launching_point]]\t[get_object_name [get_property $path capturing_point]]"
}
close $file
tri_oracle_require_preserved_clock_boundaries $out/clock_boundaries_after.tsv $counts
puts "TRI_ORACLE_PARENT_POSTCLOCK_CORNER55_DIAGNOSTIC_FINISHED $view"
exit
