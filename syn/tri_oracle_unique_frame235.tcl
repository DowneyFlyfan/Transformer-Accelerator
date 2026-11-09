# Timing queries require flattened full ILMs; structural operations do not.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set out $::env(TRI235_OUT)
set mode $::env(TRI235_MODE)
set top tri_oracle_predicted_feedforward_frame
if {$mode ni {warm cold}} {error TRI235_BAD_MODE}
read_db $::env(TRI235_INPUT)
set_multi_cpu_usage -local_cpu 8
set_db enable_ui_precision true
set_db ui_precision_timing 6
if {[get_db current_design .name] ne $top} {error TRI235_WRONG_PARENT}
source $root/syn/tri_oracle_unique215_snapshot.tcl
source $root/syn/tri_oracle_preservation233.tcl
set source_sdc $root/.cache/physical/synthesis/tri_oracle_predicted_feedforward_finish213/constraints.sdc
proc tri235_constraints {tag} {
    global out source_sdc
    # Follow the working203 timing-view initialization, rather than querying
    # clocks from the unsupported unflattened placement view.
    unflatten_ilm
    set_ilm_type -model si
    flatten_ilm
    set stream [open $out/[set tag]_clocks.tsv w]
    puts $stream "view\tname\tdisplayed_period_ns\texported_period_ns"
    foreach view {setup_slow setup_typ hold_fast} {
        set_analysis_view -setup [list $view] -hold [list $view]
        set clocks [get_clocks core_clock]
        if {[sizeof_collection $clocks]!=1} {error "TRI235_VIEW_CLOCK_COUNT $view"}
        set filename $out/[set tag]_[set view].sdc
        write_sdc -view $view $filename
        set input [open $filename r];set text [read $input];close $input
        set matches [regexp -all -inline -line {^create_clock[^\n]*-period[ \t]+([0-9.eE+-]+)} $text]
        if {[llength $matches]!=2 || abs(double([lindex $matches 1])-1.72414)>0.00000001} {
            error "TRI235_EXPORTED_CLOCK_CHANGED $view $matches"
        }
        puts $stream "$view\t[get_object_name $clocks]\t[get_property $clocks period]\t[lindex $matches 1]"
    }
    close $stream
    set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}
}
proc tri235_parent_inventory {} {
    if {[llength [get_db insts]]!=673622 ||
        [llength [get_db insts -if {.base_cell.name == tri_oracle_sram_memory_compute}]]!=20 ||
        [llength [get_db insts -if {.base_cell.name == TS6N28HPCPSVTA16X128M2F}]]!=40} {
        error TRI235_WRONG_PARENT_INVENTORY
    }
}
if {$mode eq "warm"} {
    tri235_constraints before
    unflatten_ilm
    tri233_preservation $source_sdc $out/before_preservation.tsv 86
    tri235_parent_inventory
    tri215_snapshot $out before
    set before [check_unique -verbose]
    if {$before!=0} {error TRI235_EXPECTED_NONUNIQUE_BASELINE_MISSING}
    uniquify $top -verbose
    set after [check_unique -verbose]
    if {$after!=1} {error TRI235_PARENT_NOT_UNIQUE}
    if {[tri215_snapshot $out after]!=673622} {error TRI235_LEAF_COUNT_CHANGED}
    tri215_require_equal $out before after
    tri233_preservation $source_sdc $out/after_preservation.tsv 86
    set stream [open $out/unique_status.tsv w]
    puts $stream "unique_before\t$before"
    puts $stream "unique_after\t$after"
    puts $stream "parent_cells\t673622"
    close $stream
} else {
    tri235_constraints cold
    unflatten_ilm
    tri233_preservation $source_sdc $out/cold_preservation.tsv 86
    tri235_parent_inventory
    if {[check_unique]!=1} {error TRI235_COLD_PARENT_NOT_UNIQUE}
    tri215_snapshot $out cold
    foreach kind {cells ports nets pins} {
        set reference $::env(TRI235_WARM)/before_[set kind].tsv.sorted
        set candidate $out/cold_[set kind].tsv
        exec env LC_ALL=C sort -S 64M -T $out -o $candidate.sorted $candidate
        if {[catch {exec cmp -s $reference $candidate.sorted}]} {error "TRI235_COLD_GRAPH_CHANGED $kind"}
    }
}
source $root/syn/tri_oracle_registered_reset_trace102.tcl
source $root/syn/tri_oracle_check_registered_reset_fabric.tcl
set registered_masters [exec python3 -B -c {import json,sys; print(" ".join(json.load(open(sys.argv[1]))["flip_flop_cells"]))} $root/records/registered_reset34_sequential_masters.json]
tri_oracle_require_parent_registered_resets $registered_masters $out/registered_reset_roots.tsv
check_place > $out/placement.rpt
if {$mode eq "warm"} {
    write_netlist $out/unique_parent.v -exclude_leaf_cells
    write_def $out/unique_parent.def
    tri235_constraints after
    write_db $out/unique.db
    puts TRI_ORACLE_FRAME235_UNIQUE_PARENT_SAVED
    exit
}
# The cold parent must still restore every original routed core instance.
set stream [open $::env(TRI235_PREFIXES) r]
set prefixes [split [string trim [read $stream]] "\n"]
close $stream
set counts [dict create]
foreach prefix $prefixes {dict set counts $prefix 0}
if {[dict size $counts] != 20} {error TRI235_WRONG_CORE_PREFIXES}
set_ilm_type -model si
flatten_ilm
set stream [open $out/core_after.tsv w]
puts $stream "instance\tmaster\tlocation\torientation"
foreach instance [get_db insts] {
    set name [get_db $instance .name]
    if {![regexp {^(.*clusters\[[0-9]+\]\.cluster/cores\[[0-9]+\])/(.+)$} $name -> prefix local]} {continue}
    if {![dict exists $counts $prefix]} {error "TRI235_UNKNOWN_CORE $prefix"}
    dict incr counts $prefix
    puts $stream "$name\t[get_db $instance .base_cell.name]\t[get_db $instance .location]\t[get_db $instance .orient]"
}
close $stream
dict for {prefix count} $counts {
    if {$count != 94471} {error "TRI235_ORIGINAL_CORE_INCOMPLETE $prefix $count"}
}
foreach master {TS5N28HPCPSVTA32X128M2FW TS5N28HPCPSVTA512X64M4F TS6N28HPCPSVTA16X128M2F} expected {360 40 200} {
    if {[llength [get_db insts -if ".base_cell.name == $master"]] != $expected} {error TRI235_MEMORY_COUNT_CHANGED}
}
report_ilm_status > $out/model_status.rpt
# Reapply the pinned original SDC only in this disposable reference process.
# Compare its exports to every candidate capture; never overwrite unique.db.
set source_sdc $root/.cache/physical/synthesis/tri_oracle_predicted_feedforward_finish213/constraints.sdc
update_constraint_mode -name functional -sdc_files [list $source_sdc] -ilm_sdc_files [list $source_sdc]
tri235_constraints expected
unflatten_ilm
tri233_preservation $source_sdc $out/expected_preservation.tsv 86
puts TRI_ORACLE_FRAME235_UNIQUE_PARENT_COLD_VERIFIED
exit
