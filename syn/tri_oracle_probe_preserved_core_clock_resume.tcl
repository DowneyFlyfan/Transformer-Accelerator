# Focused replay from the native pre-clock checkpoint; original full core.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set out $::env(TRI_ORACLE_PLACEMENT_PROBE_DIRECTORY)
set input $root/.cache/physical/pnr/tri_oracle_clock_probe35_green4/placed_probe.db
read_db $input
set_multi_cpu_usage -local_cpu 4
set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}
set_db enable_ui_precision true
set_db ui_precision_timing 6
set_db timing_analysis_type ocv
set_db timing_analysis_cppr both
if {[get_db current_design .name] ne "tri_oracle_preserved_placement_probe21"} {error "CLOCK35_WRONG_CHECKPOINT"}
unflatten_ilm
set block [get_db insts core0]
if {![get_db $block .dont_touch] || [get_db $block .place_status] ne "fixed"} {error "CLOCK35_UNPROTECTED_BLOCK"}
set original_block_pose [list [get_db $block .location] [get_db $block .orient] [get_db $block .place_status]]
set_ilm_type -model si
flatten_ilm
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

set original_cells [snapshot_original_core21 $out/core_before.tsv]
set file [open $out/core_prefixes.txt w]; puts $file core0; close $file
exec python3 -B $root/syn/tri_oracle_core_preservation.py $root/.cache/physical/pnr/tri_oracle_clock_probe35_green4/core_before.tsv $out/core_before.tsv $out/core_prefixes.txt > $out/input_preservation.json
set_db cts_buffer_cells {CKBD1BWP12T40P140 CKBD2BWP12T40P140 CKBD4BWP12T40P140 CKBD8BWP12T40P140 CKBD12BWP12T40P140}
set_db cts_inverter_cells {CKND1BWP12T40P140 CKND2BWP12T40P140 CKND4BWP12T40P140 CKND8BWP12T40P140}
source $root/syn/tri_oracle_require_preserved_clock_boundaries.tcl
create_clock_tree_spec -out_file $out/clock_spec.tcl
source $out/clock_spec.tcl
tri_oracle_require_preserved_clock_boundaries $out/clock_boundaries_before.tsv [dict create core0 0]
report_clock_tree_structure -show_sinks -out_file $out/clock_structure_before.rpt
clock_opt_design -check_cts_config
clock_opt_design -report_dir $out/clock_reports
tri_oracle_require_preserved_clock_boundaries $out/clock_boundaries_after.tsv [dict create core0 0]
report_clock_trees -summary -out_file $out/clock_trees.rpt
report_clock_tree_structure -show_sinks -out_file $out/clock_structure_after.rpt
write_db $out/clocked_before_legalization.db
unflatten_ilm
place_detail
set block [get_db insts core0]
if {[list [get_db $block .location] [get_db $block .orient] [get_db $block .place_status]] ne $original_block_pose || ![get_db $block .dont_touch]} {error "CLOCK35_BLOCK_CHANGED"}
check_place > $out/placement.rpt
source $root/syn/tri_oracle_require_clean_placement.tcl
tri_oracle_require_clean_placement $out/placement.rpt
write_def $out/clocked_parent.def -routing
set_ilm_type -model si
flatten_ilm
snapshot_original_core21 $out/core_after.tsv
exec python3 -B $root/syn/tri_oracle_core_preservation.py $out/core_before.tsv $out/core_after.tsv $out/core_prefixes.txt > $out/core_preservation.json
write_db $out/clocked_probe.db
set saved_check [get_db timing_analysis_check_type]
foreach view {setup_slow setup_typ hold_fast} {
    set_db timing_analysis_check_type [expr {$view eq "hold_fast" ? "hold" : "setup"}]
    report_clocks -view $view -hierarchy -description -source_insertion > $out/clock_$view.rpt
    if {$view eq "hold_fast"} {
        report_timing -view $view -early -max_paths 5 > $out/clocked_$view.rpt
    } else {
        report_timing -view $view -max_paths 5 > $out/clocked_$view.rpt
    }
}
set_db timing_analysis_check_type $saved_check
puts TRI_ORACLE_PRESERVED_CORE_CLOCK35_FINISHED
exit
