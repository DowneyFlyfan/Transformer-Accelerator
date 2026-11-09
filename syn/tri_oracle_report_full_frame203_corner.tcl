# A fresh native process checks one process corner on the complete parent.
# All twenty full routed core models remain present. No timing constraint is
# altered. Running the three corners separately bounds timing-cache memory.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set input $::env(TRI_ORACLE_PARENT_DIAGNOSTIC_CHECKPOINT)
set out $::env(TRI_ORACLE_PARENT_DIAGNOSTIC_DIRECTORY)
set view $::env(TRI_ORACLE_PARENT_DIAGNOSTIC_VIEW)
if {$view ni {setup_slow setup_typ hold_fast}} {error "PARENT_CORNER53_UNKNOWN_VIEW"}
set_multi_cpu_usage -local_cpu 8
read_db $input
set_multi_cpu_usage -local_cpu 8
if {[get_db current_design .name] ne "tri_oracle_predicted_feedforward_frame"} {
    error "PARENT_CORNER53_WRONG_PARENT"
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
    if {![regexp {^(.*clusters\[[0-9]+\]\.cluster/cores\[[0-9]+\])/(.+)$} $name -> prefix local]} {continue}
    dict incr counts $prefix
}
if {[dict size $counts] != 20} {error "PARENT_CORNER53_INCOMPLETE_CORE_SET"}
set file [open $out/core_counts.tsv w]
puts $file "core\tfull_original_cells"
dict for {prefix count} $counts {
    if {$count != 94471} {error "PARENT_CORNER53_INCOMPLETE_ORIGINAL_CORE: $prefix $count"}
    puts $file "$prefix\t$count"
}
close $file
foreach master {TS5N28HPCPSVTA32X128M2FW TS5N28HPCPSVTA512X64M4F TS6N28HPCPSVTA16X128M2F} expected {360 40 200} {
    if {[llength [get_db insts -if ".base_cell.name == $master"]] != $expected} {
        error "PARENT_CORNER53_WRONG_MEMORY_COUNT: $master"
    }
}
report_ilm_status > $out/model_status.rpt
if {[sizeof_collection [get_clocks core_clock]] != 1} {error "PARENT_CORNER53_MISSING_ACTUAL_CLOCK"}
time_design -pre_cts -drv_report -expanded_views -report_dir $out/timing -report_prefix corner
set_db timing_analysis_check_type [expr {$view eq "hold_fast" ? "hold" : "setup"}]
report_clocks -view $view -hierarchy -description -source_insertion > $out/clocks.rpt
set command [list report_timing -view $view -max_paths 1 -max_slack 100]
if {$view eq "hold_fast"} {lappend command -early} else {lappend command -check_type setup}
eval $command > $out/worst_path.rpt
set paths [eval $command -collection]
if {[sizeof_collection $paths] != 1} {error "PARENT_CORNER53_MISSING_ACTUAL_PATH: $view"}
set file [open $out/slack_properties.tsv w]
puts $file "view\tslack_ns\tstartpoint\tendpoint"
foreach_in_collection path $paths {
    puts $file "$view\t[get_property $path slack]\t[get_object_name [get_property $path launching_point]]\t[get_object_name [get_property $path capturing_point]]"
}
close $file
puts "TRI_ORACLE_FRAME203_CORNER_DIAGNOSTIC_FINISHED $view"
exit
