# Read-only cold-load verification of the actual post-clock checkpoint.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set out $::env(TRI_ORACLE_PLACEMENT_PROBE_DIRECTORY)
set input $root/.cache/physical/pnr/tri_oracle_clock_probe35_green6/clocked_probe.db
read_db $input
set_multi_cpu_usage -local_cpu 4
set_db enable_ui_precision true
set_db ui_precision_timing 6
report_analysis_views -type active > $out/views_before.rpt
unflatten_ilm
check_place > $out/placement.rpt
source $root/syn/tri_oracle_require_clean_placement.tcl
tri_oracle_require_clean_placement $out/placement.rpt
set block [get_db insts core0]
if {![get_db $block .dont_touch] || [get_db $block .place_status] ne "fixed"} {error "CLOCK35_COLD_UNPROTECTED_CORE"}
set_ilm_type -model si
flatten_ilm
# Native optimizers can prune a dominated setup view; restore the unchanged
# original corner set before accepting any timing report (core54 precedent).
set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}
report_analysis_views -type active > $out/views_after.rpt
source $root/syn/tri_oracle_require_preserved_clock_boundaries.tcl
tri_oracle_require_preserved_clock_boundaries $out/clock_boundaries_before.tsv [dict create core0 0]
proc snapshot_original_core21 {filename} {
    set inventory [dict create]
    set file [open $filename w]
    puts $file "instance\tmaster\tlocation\torientation"
    foreach instance [get_db insts] {
        set name [get_db $instance .name]
        if {![string match {core0/*} $name]} {continue}
        set fields [list [get_db $instance .base_cell.name] [get_db $instance .location] [get_db $instance .orient]]
        dict set inventory $name $fields
        puts $file [join [linsert $fields 0 $name] \t]
    }
    close $file
    if {[dict size $inventory] != 94471} {
        error "PRESERVED_CORE21_MISSING_FULL_MODEL: [dict size $inventory]"
    }
    foreach master {TS5N28HPCPSVTA32X128M2FW TS5N28HPCPSVTA512X64M4F TS6N28HPCPSVTA16X128M2F} expected {18 2 8} {
        if {[llength [get_db insts -if ".base_cell.name == $master"]] != $expected} {
            error "PRESERVED_CORE21_WRONG_MEMORY_COUNT: $master"
        }
    }
    return $inventory
}

snapshot_original_core21 $out/core_before.tsv
set file [open $out/core_prefixes.txt w]; puts $file core0; close $file
set saved_check [get_db timing_analysis_check_type]
set file [open $out/slack_properties.tsv w]
puts $file "view\tslack_ns\tstartpoint\tendpoint"
foreach view {setup_slow setup_typ hold_fast} {
    set_db timing_analysis_check_type [expr {$view eq "hold_fast" ? "hold" : "setup"}]
    report_clocks -view $view -hierarchy -description -source_insertion > $out/clock_$view.rpt
    set command [list report_timing -view $view -max_paths 5 -max_slack 100]
    if {$view eq "hold_fast"} {lappend command -early} else {lappend command -check_type setup}
    eval $command > $out/clocked_$view.rpt
    set exact [lreplace $command 4 4 1]
    set paths [eval $exact -collection]
    if {[sizeof_collection $paths] != 1} {error "CLOCK35_MISSING_REAL_PATH: $view"}
    foreach_in_collection path $paths {
        puts $file "$view\t[get_property $path slack]\t[get_object_name [get_property $path launching_point]]\t[get_object_name [get_property $path capturing_point]]"
    }
}
close $file
set_db timing_analysis_check_type $saved_check
tri_oracle_require_preserved_clock_boundaries $out/clock_boundaries_after.tsv [dict create core0 0]
snapshot_original_core21 $out/core_after.tsv
exec python3 -B $root/syn/tri_oracle_core_preservation.py $root/.cache/physical/pnr/tri_oracle_clock_probe35_green6/core_after.tsv $out/core_after.tsv $out/core_prefixes.txt > $out/core_preservation.json
puts TRI_ORACLE_CORE_CLOCK35_COLD_REPORTS_FINISHED
exit
