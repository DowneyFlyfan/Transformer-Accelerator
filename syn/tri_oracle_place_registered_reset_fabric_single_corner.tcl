# Real mapped-parent placement with all twenty original complete core models.
# Prerequisite mapping, functional simulation, and native import are checked by
# the guarded launcher. Pre-clock-tree timing is diagnostic, not routed signoff.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set top tri_oracle_predicted_fabric
set parent $root/.cache/physical/pnr/tri_oracle_predicted_fabric_registered_reset30
set out $parent/placement68
set component tri_oracle_sram_memory_compute
set base $root/.cache/physical/pnr/$component
if {![file isdirectory $parent/macro_floorplan.db]} {error "PARENT33_MISSING_NATIVE_IMPORT"}
if {[file exists $out/placed.db]} {error "PARENT33_EXISTING_PLACED_DATABASE"}
file mkdir $out
read_db $parent/macro_floorplan.db
set_multi_cpu_usage -local_cpu 4
if {[get_db current_design .name] ne $top} {error "PARENT33_WRONG_PHYSICAL_TOP"}
set constraints $root/.cache/physical/synthesis/tri_oracle_predicted_fabric_registered_reset30/constraints.sdc
update_constraint_mode -name functional -sdc_files [list $constraints] -ilm_sdc_files [list $constraints]
set_analysis_view -setup {setup_slow} -hold {setup_slow}
if {[sizeof_collection [get_clocks core_clock]] == 0} {error "PARENT33_MISSING_PARENT_CLOCK"}

set core_blocks [get_db insts -if {.base_cell.name == tri_oracle_sram_memory_compute}]
set aggregate_banks [get_db insts -if {.base_cell.name == TS6N28HPCPSVTA16X128M2F}]
if {[llength $core_blocks] != 20 || [llength $aggregate_banks] != 40} {
    error "PARENT33_WRONG_INITIAL_MACRO_COUNTS"
}
set original_macro_poses [dict create]
set core_prefixes [dict create]
set indexes [dict create]
foreach instance [concat $core_blocks $aggregate_banks] {
    set name [get_db $instance .name]
    set master [get_db $instance .base_cell.name]
    if {[get_db $instance .place_status] ne "fixed" || [get_db $instance .orient] ne "r0"} {
        error "PARENT33_UNFIXED_OR_ROTATED_MACRO: $name"
    }
    if {$master eq $component} {
        if {![regexp {clusters\[([0-9]+)\]\.unit/cluster/implementation/cores\[([0-9]+)\]$} $name -> cluster core] ||
            $cluster >= 5 || $core >= 4 || [llength [get_db $instance .pins]] != 3158} {
            error "PARENT33_WRONG_ORIGINAL_CORE_INTERFACE: $name"
        }
        set key core:$cluster:$core
        dict set core_prefixes $name 0
    } else {
        if {![regexp {clusters\[([0-9]+)\]\.unit/cluster/implementation/aggregate_memory\[([0-9]+)\]$} $name -> cluster bank] ||
            $cluster >= 5 || $bank >= 8 || [llength [get_db $instance .pins]] != 268} {
            error "PARENT33_WRONG_AGGREGATE_INTERFACE: $name"
        }
        set key bank:$cluster:$bank
    }
    if {[dict exists $indexes $key]} {error "PARENT33_DUPLICATE_MACRO_INDEX: $key"}
    dict set indexes $key 1
    set_db $instance .dont_touch true
    dict set original_macro_poses $name [list $master [get_db $instance .location] \
        [get_db $instance .orient] [get_db $instance .place_status]]
}
if {[dict size $indexes] != 60 || [dict size $core_prefixes] != 20} {error "PARENT33_INCOMPLETE_MACRO_INVENTORY"}
set prefix_file [open $out/core_prefixes.txt w]
foreach name [lsort [dict keys $core_prefixes]] {puts $prefix_file $name}
close $prefix_file
set original_parent_count [llength [get_db insts]]
if {$original_parent_count <= 60} {error "PARENT33_MISSING_MAPPED_PARENT_LOGIC"}

proc tri_oracle_snapshot_complete_cores33 {filename expected_prefixes} {
    set counts $expected_prefixes
    set file [open $filename w]
    puts $file "instance\tmaster\tlocation\torientation"
    foreach instance [get_db insts] {
        set name [get_db $instance .name]
        if {![regexp {^(.*clusters\[[0-9]+\]\.unit/cluster/implementation/cores\[[0-9]+\])/(.+)$} $name -> prefix local]} {continue}
        if {![dict exists $counts $prefix]} {error "PARENT33_UNEXPECTED_CORE_INTERNAL: $name"}
        dict incr counts $prefix
        puts $file "$name\t[get_db $instance .base_cell.name]\t[get_db $instance .location]\t[get_db $instance .orient]"
    }
    close $file
    foreach name [dict keys $counts] {
        if {[dict get $counts $name] != 94471} {
            error "PARENT33_INCOMPLETE_CORE_MODEL: $name [dict get $counts $name]"
        }
    }
    foreach master {TS5N28HPCPSVTA32X128M2FW TS5N28HPCPSVTA512X64M4F TS6N28HPCPSVTA16X128M2F} expected {360 40 200} {
        if {[llength [get_db insts -if ".base_cell.name == $master"]] != $expected} {
            error "PARENT33_WRONG_FULL_MEMORY_COUNT: $master"
        }
    }
    return 1889420
}

read_ilm -cell $component -directory $base/hierarchy_full_control_68/ilm
set_ilm_type -model si
flatten_ilm
if {[llength [get_db insts]] != $original_parent_count-20+1889420} {
    error "PARENT33_INCOMPLETE_INITIAL_FULL_HIERARCHY"
}
tri_oracle_snapshot_complete_cores33 $out/core_before.tsv $core_prefixes
report_ilm_status > $out/model_before.rpt
unflatten_ilm
set_db enable_ui_precision true
set_db ui_precision_timing 6
set_db timing_analysis_type ocv
set_db timing_analysis_cppr both
set_db delaycal_enable_si true
place_opt_design -report_dir $out/place_reports
place_detail
check_place > $out/placement.rpt
set final_macro_count 0
foreach instance [get_db insts] {
    set name [get_db $instance .name]
    if {[get_db $instance .place_status] ni {placed fixed}} {
        error "PARENT33_UNPLACED_PARENT_INSTANCE: $name"
    }
    if {![dict exists $original_macro_poses $name]} {continue}
    set pose [list [get_db $instance .base_cell.name] [get_db $instance .location] \
        [get_db $instance .orient] [get_db $instance .place_status]]
    if {$pose ne [dict get $original_macro_poses $name] || ![get_db $instance .dont_touch]} {
        error "PARENT33_ORIGINAL_FIXED_MACRO_CHANGED: $name"
    }
    incr final_macro_count
}
if {$final_macro_count != 60} {error "PARENT33_ORIGINAL_MACRO_DISAPPEARED"}
source $root/syn/tri_oracle_registered_reset_trace.tcl
source $root/syn/tri_oracle_check_registered_reset_fabric.tcl
set registered_masters [exec python3 -B -c {import json,sys; print(" ".join(json.load(open(sys.argv[1]))["flip_flop_cells"]))} $root/records/registered_reset34_sequential_masters.json]
tri_oracle_require_parent_registered_resets $registered_masters $out/registered_reset_roots.tsv
set final_parent_count [llength [get_db insts]]
write_def $out/placed_parent.def
set_ilm_type -model si
flatten_ilm
if {[llength [get_db insts]] != $final_parent_count-20+1889420} {
    error "PARENT33_INCOMPLETE_FINAL_FULL_HIERARCHY"
}
tri_oracle_snapshot_complete_cores33 $out/core_after.tsv $core_prefixes
exec python3 -B $root/syn/tri_oracle_core_preservation.py \
    $out/core_before.tsv $out/core_after.tsv $out/core_prefixes.txt > $out/core_preservation.json
report_ilm_status > $out/model_after.rpt
# All three complete-corner diagnostics run in fresh native processes after
# this checkpoint is saved. This process optimizes the original slow view only.
# Fast hold is checked separately and repaired in a later dedicated phase if needed.
set inventory [open $out/full_inventory.rpt w]
puts $inventory "original_core_models: 20"
puts $inventory "original_core_cells: 1889420"
puts $inventory "aggregate_banks: 40"
puts $inventory "memory_macros: 600"
puts $inventory "parent_instances_before_placement: $original_parent_count"
puts $inventory "parent_instances_after_placement: $final_parent_count"
puts $inventory "fixed_original_macros_preserved: $final_macro_count"
puts $inventory "unplaced_parent_instances: 0"
close $inventory
write_db $out/placed.db
puts TRI_ORACLE_PREDICTED_FABRIC_FULL_MODEL_PLACEMENT68_FINISHED
exit
