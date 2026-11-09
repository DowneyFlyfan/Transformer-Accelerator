# Native placement capability fixture, not the twenty-core processor.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set out $::env(TRI_ORACLE_PLACEMENT_PROBE_DIRECTORY)
set component tri_oracle_sram_memory_compute
set base $root/.cache/physical/pnr/$component
set probe_top tri_oracle_preserved_placement_probe21
set_multi_cpu_usage -local_cpu 4
set_db design_process_node 28
set_db init_power_nets {VDD}
set_db init_ground_nets {VSS}
read_mmmc $out/mmmc.tcl
read_physical -lefs [list \
    $root/.cache/physical/routing_kit/N28_PRTF_Cad_v1d5a/PR_tech/Cadence/LefHeader/VHV/tsmcn28_10lm5X2Y2ZUTRDL.tlef \
    $root/.cache/physical/library/tcbn28hpcplusbwp12t40p140.lef \
    $root/.cache/physical/sram/core_weights_masks_01/ts5n28hpcpsvta32x128m2fw_130a/LEF/ts5n28hpcpsvta32x128m2fw_130a.lef \
    $root/.cache/physical/sram/core_outputs_01/ts6n28hpcpsvta16x128m2f_130a/LEF/ts6n28hpcpsvta16x128m2f_130a.lef \
    $root/.cache/physical/sram/activation_cache_banks_01/ts5n28hpcpsvta512x64m4f_130a/LEF/ts5n28hpcpsvta512x64m4f_130a.lef \
    $base/hierarchy_export_58/core.lef]
read_netlist $out/fixture.v -top $probe_top
init_design
if {[get_db current_design .name] ne $probe_top || [llength [get_db insts]] != 2} {
    error "PRESERVED_CORE21_WRONG_PARENT"
}
create_floorplan -site core12T -no_snap_to_grid -die_size {799.955 750 20 20 20 20}
place_inst core0 40 40 r0 -fixed
create_place_halo -halo_deltas {5 5 5 5} -snap_to_site -cell $component
set block [get_db insts core0]
set register [get_db insts parent_valid]
set_db $block .dont_touch true
set_db $register .dont_touch true
set original_block_pose [list [get_db $block .location] [get_db $block .orient] [get_db $block .place_status]]
connect_global_net VDD -type pg_pin -pin_base_name VDD -all
connect_global_net VSS -type pg_pin -pin_base_name VSS -all
set ports [lsort [get_db ports .name]]
for {set side 0} {$side < 4} {incr side} {
    set first [expr {$side*[llength $ports]/4}]
    set last [expr {($side+1)*[llength $ports]/4-1}]
    edit_pin -pin [lrange $ports $first $last] -side [lindex {left right top bottom} $side] \
        -spread_type side -layer [lindex {M4 M4 M5 M5} $side] -snap track
}

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

if {$::env(TRI_ORACLE_PLACEMENT_PROBE_FULL_MODEL) eq "1"} {
    read_ilm -cell $component -directory $base/hierarchy_full_control_68/ilm
    set_ilm_type -model si
    flatten_ilm
}
set original_cells [snapshot_original_core21 $out/core_before.tsv]
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
set block [get_db insts core0]
set current_block_pose [list [get_db $block .location] [get_db $block .orient] [get_db $block .place_status]]
if {$current_block_pose ne $original_block_pose || ![get_db $block .dont_touch]} {
    error "PRESERVED_CORE21_FIXED_BLOCK_CHANGED"
}
if {[get_db [get_db insts parent_valid] .place_status] ni {placed fixed}} {
    error "PRESERVED_CORE21_PARENT_REGISTER_NOT_PLACED"
}
write_def $out/placed_parent.def
set_ilm_type -model si
flatten_ilm
set final_cells [snapshot_original_core21 $out/core_after.tsv]
foreach name [dict keys $original_cells] {
    if {![dict exists $final_cells $name] || [dict get $original_cells $name] ne [dict get $final_cells $name]} {
        error "PRESERVED_CORE21_INTERNAL_MODEL_CHANGED: $name"
    }
}
report_ilm_status > $out/model_after.rpt
time_design -pre_cts -expanded_views -report_dir $out/prects -report_prefix prects
set file [open $out/parent_to_core_paths.tsv w]
puts $file "view\tstart\tendpoint\tslack_ns\tpath_delay_ns"
foreach view {setup_slow setup_typ hold_fast} {
    set command [list report_timing -view $view -from [get_pins parent_valid/Q] -max_paths 1 -collection]
    if {$view eq "hold_fast"} {lappend command -early} else {lappend command -check_type setup}
    set paths [eval $command]
    if {[sizeof_collection $paths] != 1} {error "PRESERVED_CORE21_NO_CROSS_BOUNDARY_PATH: $view"}
    foreach_in_collection path $paths {
        set start [get_object_name [get_property $path launching_point]]
        set endpoint [get_object_name [get_property $path capturing_point]]
        set endpoint_instance [string range $endpoint 0 [expr {[string last / $endpoint]-1}]]
        if {![dict exists $original_cells $endpoint_instance]} {
            error "PRESERVED_CORE21_ENDPOINT_IS_NOT_AN_ORIGINAL_CORE_CELL: $endpoint"
        }
        puts $file "$view\t$start\t$endpoint\t[get_property $path slack]\t[get_property $path path_delay]"
    }
}
close $file
# Inspect and synthesize the actual parent clock using the complete fixed core.
# The existing core clock network must not be rebuilt or geometrically changed.
write_db $out/placed_probe.db
set_db cts_buffer_cells {CKBD1BWP12T40P140 CKBD2BWP12T40P140 CKBD4BWP12T40P140 CKBD8BWP12T40P140 CKBD12BWP12T40P140}
set_db cts_inverter_cells {CKND1BWP12T40P140 CKND2BWP12T40P140 CKND4BWP12T40P140 CKND8BWP12T40P140}
create_clock_tree_spec -out_file $out/clock_spec.tcl
source $out/clock_spec.tcl
set file [open $out/clock_extraction.rpt w]
puts $file "clock_trees: [get_db clock_trees .name]"
close $file
report_clock_tree_structure -show_sinks -out_file $out/clock_structure_before.rpt
clock_opt_design -check_cts_config
clock_opt_design -report_dir $out/clock_reports
report_clock_trees -summary -out_file $out/clock_trees.rpt
report_clock_tree_structure -show_sinks -out_file $out/clock_structure_after.rpt
unflatten_ilm
check_place > $out/clock_placement.rpt
source $root/syn/tri_oracle_require_clean_placement.tcl
tri_oracle_require_clean_placement $out/clock_placement.rpt
set block [get_db insts core0]
set current_block_pose [list [get_db $block .location] [get_db $block .orient] [get_db $block .place_status]]
if {$current_block_pose ne $original_block_pose || ![get_db $block .dont_touch]} {
    error "PRESERVED_CLOCK35_FIXED_BLOCK_CHANGED"
}
write_def $out/clocked_parent.def -routing
set_ilm_type -model si
flatten_ilm
set clocked_cells [snapshot_original_core21 $out/core_clocked.tsv]
foreach name [dict keys $original_cells] {
    if {![dict exists $clocked_cells $name] || [dict get $original_cells $name] ne [dict get $clocked_cells $name]} {
        error "PRESERVED_CLOCK35_ORIGINAL_CORE_CHANGED: $name"
    }
}
foreach view {setup_slow setup_typ hold_fast} {
    report_clocks -view $view -hierarchy -description -source_insertion > $out/clock_$view.rpt
    if {$view eq "hold_fast"} {
        report_timing -view $view -early -max_paths 5 > $out/clocked_$view.rpt
    } else {
        report_timing -view $view -max_paths 5 > $out/clocked_$view.rpt
    }
}
write_db $out/clocked_probe.db
puts TRI_ORACLE_PRESERVED_CORE_CLOCK35_FINISHED
exit
