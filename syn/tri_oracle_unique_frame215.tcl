# Unique parent definitions; no electrical/timing optimization in this stage.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set out $::env(TRI215_OUT)
set input $::env(TRI215_INPUT)
set mode $::env(TRI215_MODE)
set top tri_oracle_predicted_feedforward_frame
if {$mode ni {warm cold}} {error TRI215_BAD_MODE}
set_multi_cpu_usage -local_cpu 8
read_db $input
set_multi_cpu_usage -local_cpu 8
if {[get_db current_design .name] ne $top} {error TRI215_WRONG_PARENT}
unflatten_ilm
if {[llength [get_db insts]] != 673622 ||
    [llength [get_db insts -if {.base_cell.name == tri_oracle_sram_memory_compute}]] != 20 ||
    [llength [get_db insts -if {.base_cell.name == TS6N28HPCPSVTA16X128M2F}]] != 40} {
    error TRI215_WRONG_PARENT_INVENTORY
}
if {[sizeof_collection [get_clocks core_clock]] != 1 ||
    abs([get_property [get_clocks core_clock] period]-1.72414)>0.00000001} {
    error TRI215_ORIGINAL_CLOCK_CHANGED
}
source $root/syn/tri_oracle_unique215_snapshot.tcl
if {$mode eq "warm"} {
    tri215_snapshot $out before
    foreach view {setup_slow setup_typ hold_fast} {write_sdc -view $view $out/before_[set view].sdc}
    set before [check_unique -verbose]
    if {$before != 0} {error TRI215_EXPECTED_NONUNIQUE_BASELINE_MISSING}
    uniquify $top -verbose
    set after [check_unique -verbose]
    if {$after != 1} {error TRI215_PARENT_NOT_UNIQUE}
    if {[tri215_snapshot $out after] != 673622} {error TRI215_LEAF_COUNT_CHANGED}
    tri215_require_equal $out before after
    foreach view {setup_slow setup_typ hold_fast} {write_sdc -view $view $out/after_[set view].sdc}
    set stream [open $out/unique_status.tsv w]
    puts $stream "unique_before\t$before"
    puts $stream "unique_after\t$after"
    puts $stream "parent_cells\t673622"
    close $stream
} else {
    if {[check_unique -verbose] != 1} {error TRI216_COLD_PARENT_NOT_UNIQUE}
    tri215_snapshot $out cold
    foreach view {setup_slow setup_typ hold_fast} {write_sdc -view $view $out/cold_[set view].sdc}
    # Compare in the warm directory, keeping every sorted snapshot bound.
    foreach kind {cells ports nets pins} {
        set reference $::env(TRI215_WARM)/before_[set kind].tsv.sorted
        set candidate $out/cold_[set kind].tsv
        exec env LC_ALL=C sort -S 64M -T $out -o $candidate.sorted $candidate
        if {[catch {exec cmp -s $reference $candidate.sorted}]} {
            error "TRI216_COLD_PARENT_GRAPH_CHANGED $kind"
        }
    }
}
source $root/syn/tri_oracle_registered_reset_trace102.tcl
source $root/syn/tri_oracle_check_registered_reset_fabric.tcl
set registered_masters [exec python3 -B -c {import json,sys; print(" ".join(json.load(open(sys.argv[1]))["flip_flop_cells"]))} $root/records/registered_reset34_sequential_masters.json]
tri_oracle_require_parent_registered_resets $registered_masters $out/registered_reset_roots.tsv
report_clocks -view setup_slow -description > $out/clocks.rpt
check_place > $out/placement.rpt
if {$mode eq "warm"} {
    write_netlist $out/unique_parent.v -exclude_leaf_cells
    write_def $out/unique_parent.def
    write_db $out/unique.db
    puts TRI_ORACLE_FRAME215_UNIQUE_PARENT_SAVED
    exit
}
# The cold parent must still restore every original routed core instance.
set stream [open $::env(TRI215_PREFIXES) r]
set prefixes [split [string trim [read $stream]] "\n"]
close $stream
set counts [dict create]
foreach prefix $prefixes {dict set counts $prefix 0}
if {[dict size $counts] != 20} {error TRI216_WRONG_CORE_PREFIXES}
set_ilm_type -model si
flatten_ilm
set stream [open $out/core_after.tsv w]
puts $stream "instance\tmaster\tlocation\torientation"
foreach instance [get_db insts] {
    set name [get_db $instance .name]
    if {![regexp {^(.*clusters\[[0-9]+\]\.cluster/cores\[[0-9]+\])/(.+)$} $name -> prefix local]} {continue}
    if {![dict exists $counts $prefix]} {error "TRI216_UNKNOWN_CORE $prefix"}
    dict incr counts $prefix
    puts $stream "$name\t[get_db $instance .base_cell.name]\t[get_db $instance .location]\t[get_db $instance .orient]"
}
close $stream
dict for {prefix count} $counts {
    if {$count != 94471} {error "TRI216_ORIGINAL_CORE_INCOMPLETE $prefix $count"}
}
foreach master {TS5N28HPCPSVTA32X128M2FW TS5N28HPCPSVTA512X64M4F TS6N28HPCPSVTA16X128M2F} expected {360 40 200} {
    if {[llength [get_db insts -if ".base_cell.name == $master"]] != $expected} {error TRI216_MEMORY_COUNT_CHANGED}
}
report_ilm_status > $out/model_status.rpt
puts TRI_ORACLE_FRAME216_UNIQUE_PARENT_COLD_VERIFIED
exit
