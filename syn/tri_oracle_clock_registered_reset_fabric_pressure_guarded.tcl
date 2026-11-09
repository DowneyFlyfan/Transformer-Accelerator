# Parent clock-tree implementation, using the original complete routed cores.
# Placement57 with all three separate corner reports is the prerequisite.
# This stage does not qualify power delivery, signal routing or paper metrics.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set parent $root/.cache/physical/pnr/tri_oracle_predicted_fabric_registered_reset30
set input $parent/placement57/placed.db
set out $parent/clock59
set component tri_oracle_sram_memory_compute
if {![file isdirectory $input] || [file exists $out/clocked.db]} {
    error "PARENT_CLOCK59_INVALID_CHECKPOINT_STATE"
}
file mkdir $out
read_db $input
set_multi_cpu_usage -local_cpu 4
if {[get_db current_design .name] ne "tri_oracle_predicted_fabric"} {
    error "PARENT_CLOCK59_WRONG_PHYSICAL_TOP"
}
set_analysis_view -setup {setup_slow} -hold {hold_fast}
set_db enable_ui_precision true
set_db ui_precision_timing 6
set_db timing_analysis_type ocv
set_db timing_analysis_cppr both

unflatten_ilm
set cores [get_db insts -if {.base_cell.name == tri_oracle_sram_memory_compute}]
set banks [get_db insts -if {.base_cell.name == TS6N28HPCPSVTA16X128M2F}]
if {[llength $cores] != 20 || [llength $banks] != 40} {
    error "PARENT_CLOCK59_WRONG_MACRO_COUNTS"
}
set poses [dict create]
set prefixes [dict create]
foreach instance [concat $cores $banks] {
    set name [get_db $instance .name]
    if {[get_db $instance .place_status] ne "fixed" ||
        [get_db $instance .orient] ne "r0" || ![get_db $instance .dont_touch]} {
        error "PARENT_CLOCK59_UNPROTECTED_MACRO: $name"
    }
    dict set poses $name [list [get_db $instance .base_cell.name] \
        [get_db $instance .location] [get_db $instance .orient] [get_db $instance .place_status]]
    if {[get_db $instance .base_cell.name] eq $component} {
        if {[llength [get_db $instance .pins]] != 3158 ||
            ![regexp {clusters\[([0-9]+)\]\.unit/cluster/implementation/cores\[([0-9]+)\]$} $name]} {
            error "PARENT_CLOCK59_WRONG_CORE_INTERFACE: $name"
        }
        dict set prefixes $name 0
    } elseif {[llength [get_db $instance .pins]] != 268} {
        error "PARENT_CLOCK59_WRONG_AGGREGATE_INTERFACE: $name"
    }
}
set file [open $out/core_prefixes.txt w]
foreach name [lsort [dict keys $prefixes]] {puts $file $name}
close $file

proc tri_oracle_clock59_snapshot {filename expected} {
    set counts $expected
    set file [open $filename w]
    puts $file "instance\tmaster\tlocation\torientation"
    foreach instance [get_db insts] {
        set name [get_db $instance .name]
        if {![regexp {^(.*clusters\[[0-9]+\]\.unit/cluster/implementation/cores\[[0-9]+\])/(.+)$} $name -> prefix local]} {continue}
        if {![dict exists $counts $prefix]} {error "PARENT_CLOCK59_UNEXPECTED_CORE: $name"}
        dict incr counts $prefix
        puts $file "$name\t[get_db $instance .base_cell.name]\t[get_db $instance .location]\t[get_db $instance .orient]"
    }
    close $file
    foreach prefix [dict keys $counts] {
        if {[dict get $counts $prefix] != 94471} {
            error "PARENT_CLOCK59_INCOMPLETE_OR_MODIFIED_CORE: $prefix"
        }
    }
    foreach master {TS5N28HPCPSVTA32X128M2FW TS5N28HPCPSVTA512X64M4F TS6N28HPCPSVTA16X128M2F} expected {360 40 200} {
        if {[llength [get_db insts -if ".base_cell.name == $master"]] != $expected} {
            error "PARENT_CLOCK59_WRONG_MEMORY_INVENTORY: $master"
        }
    }
}

source $root/syn/tri_oracle_require_preserved_clock_boundaries.tcl

set_ilm_type -model si
flatten_ilm
tri_oracle_clock59_snapshot $out/core_before.tsv $prefixes
exec python3 -B $root/syn/tri_oracle_core_preservation.py \
    $parent/placement57/core_after.tsv $out/core_before.tsv $out/core_prefixes.txt > $out/input_core_preservation.json
report_ilm_status > $out/model_before.rpt
# Clock operations require flattened models in Innovus25.10 Common UI.
set_db cts_buffer_cells {CKBD1BWP12T40P140 CKBD2BWP12T40P140 CKBD4BWP12T40P140 CKBD8BWP12T40P140 CKBD12BWP12T40P140}
set_db cts_inverter_cells {CKND1BWP12T40P140 CKND2BWP12T40P140 CKND4BWP12T40P140 CKND8BWP12T40P140}
set_analysis_view -setup {setup_slow} -hold {hold_fast}
report_analysis_views -type active > $out/optimization_views_before.rpt
create_clock_tree_spec -out_file $out/clock_spec.tcl
source $out/clock_spec.tcl
tri_oracle_require_preserved_clock_boundaries $out/clock_boundaries_before.tsv $prefixes
report_clock_tree_structure -show_sinks -out_file $out/clock_structure_before.rpt
clock_opt_design -check_cts_config
clock_opt_design -report_dir $out/clock_reports
report_analysis_views -type active > $out/optimization_views_after.rpt
tri_oracle_require_preserved_clock_boundaries $out/clock_boundaries_after.tsv $prefixes
report_clock_trees -summary -out_file $out/clock_trees.rpt
report_clock_tree_structure -show_sinks -out_file $out/clock_structure_after.rpt
write_db $out/clocked_before_legalization.db
unflatten_ilm
place_detail
check_place > $out/placement.rpt
source $root/syn/tri_oracle_require_clean_placement.tcl
tri_oracle_require_clean_placement $out/placement.rpt
set matched 0
foreach instance [get_db insts] {
    set name [get_db $instance .name]
    if {[get_db $instance .place_status] ni {placed fixed}} {
        error "PARENT_CLOCK59_UNPLACED_PARENT_INSTANCE: $name"
    }
    if {![dict exists $poses $name]} {continue}
    set pose [list [get_db $instance .base_cell.name] [get_db $instance .location] \
        [get_db $instance .orient] [get_db $instance .place_status]]
    if {$pose ne [dict get $poses $name] || ![get_db $instance .dont_touch]} {
        error "PARENT_CLOCK59_ORIGINAL_MACRO_CHANGED: $name"
    }
    incr matched
}
if {$matched != 60} {error "PARENT_CLOCK59_ORIGINAL_MACRO_DISAPPEARED"}
source $root/syn/tri_oracle_registered_reset_trace.tcl
source $root/syn/tri_oracle_check_registered_reset_fabric.tcl
set masters [exec python3 -B -c {import json,sys; print(" ".join(json.load(open(sys.argv[1]))["flip_flop_cells"]))} $root/records/registered_reset34_sequential_masters.json]
tri_oracle_require_parent_registered_resets $masters $out/registered_reset_roots.tsv
write_def $out/clocked_parent.def -routing
set_ilm_type -model si
flatten_ilm
tri_oracle_clock59_snapshot $out/core_after.tsv $prefixes
exec python3 -B $root/syn/tri_oracle_core_preservation.py \
    $out/core_before.tsv $out/core_after.tsv $out/core_prefixes.txt > $out/core_preservation.json
report_ilm_status > $out/model_after.rpt
# All three post-clock corner reports run in fresh native processes. Retain
# explicit propagated clock timing in this checkpoint for subsequent routing.
set_propagated_clock [get_clocks core_clock]
if {![get_db [get_db clocks core_clock] .is_propagated]} {error "PARENT_CLOCK59_IDEAL_CLOCK"}
write_db $out/clocked.db
puts TRI_ORACLE_REGISTERED_RESET_PARENT_CLOCK59_FINISHED
exit
