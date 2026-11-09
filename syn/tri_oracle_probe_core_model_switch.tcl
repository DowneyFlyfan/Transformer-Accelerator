# Verify that a guidance view can be replaced by the complete routed model.
# The compact view is never accepted as final timing or physical signoff.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set out $::env(TRI_ORACLE_MODEL_SWITCH_DIRECTORY)
set input $::env(TRI_ORACLE_MODEL_SWITCH_INPUT)
set base $root/.cache/physical/pnr/tri_oracle_sram_memory_compute
set component tri_oracle_sram_memory_compute
read_db $input
set_multi_cpu_usage -local_cpu 4
if {[get_db current_design .name] ne "tri_oracle_preserved_placement_probe21"} {
    error "MODEL_SWITCH84_WRONG_PARENT"
}
set_db enable_ui_precision true
set_db ui_precision_timing 6
set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}
unflatten_ilm
set block [get_db insts core0]
if {[llength $block] != 1 || [get_db $block .base_cell.name] ne $component ||
    [llength [get_db $block .pins]] != 3158 || ![get_db $block .dont_touch]} {
    error "MODEL_SWITCH84_WRONG_CORE_INTERFACE"
}
set original_pose [list [get_db $block .location] [get_db $block .orient] [get_db $block .place_status]]

proc model_switch84_snapshot {filename expected} {
    set file [open $filename w]
    puts $file "instance\tmaster\tlocation\torientation"
    set count 0
    foreach instance [get_db insts] {
        set name [get_db $instance .name]
        if {![string match {core0/*} $name]} {continue}
        puts $file "$name\t[get_db $instance .base_cell.name]\t[get_db $instance .location]\t[get_db $instance .orient]"
        incr count
    }
    close $file
    if {$count != $expected} {error "MODEL_SWITCH84_WRONG_CORE_COUNT: $count $expected"}
}

proc model_switch84_clocks {filename} {
    set file [open $filename w]
    puts $file "clock\tperiod_ns"
    foreach_in_collection clock [get_clocks *] {
        puts $file "[get_object_name $clock]\t[get_property $clock period]"
    }
    close $file
}

set_ilm_type -model si
flatten_ilm
model_switch84_snapshot $out/full_before.tsv 94471
model_switch84_clocks $out/clocks_before.tsv
report_ilm_status > $out/full_before.rpt
if {[info exists ::env(TRI_ORACLE_MODEL_SWITCH_COLD)] && $::env(TRI_ORACLE_MODEL_SWITCH_COLD) eq "1"} {
    puts TRI_ORACLE_MODEL_SWITCH84_COLD_COMPLETE_MODEL_VERIFIED
    exit
}
unflatten_ilm
read_ilm -cell $component -directory $base/hierarchy_export_58/ilm
set_ilm_type -model si
flatten_ilm
model_switch84_snapshot $out/guidance.tsv 33818
report_ilm_status > $out/guidance.rpt
puts TRI_ORACLE_MODEL_SWITCH84_GUIDANCE_LOADED

unflatten_ilm
read_ilm -cell $component -directory $base/hierarchy_full_control_68/ilm
set_ilm_type -model si
flatten_ilm
model_switch84_snapshot $out/full_after.tsv 94471
model_switch84_clocks $out/clocks_after.tsv
report_ilm_status > $out/full_after.rpt
set file [open $out/core_prefixes.txt w]; puts $file core0; close $file
exec python3 -B $root/syn/tri_oracle_core_preservation.py \
    $out/full_before.tsv $out/full_after.tsv $out/core_prefixes.txt > $out/full_preservation.json
unflatten_ilm
set block [get_db insts core0]
if {[list [get_db $block .location] [get_db $block .orient] [get_db $block .place_status]] ne $original_pose ||
    ![get_db $block .dont_touch] || [llength [get_db $block .pins]] != 3158} {
    error "MODEL_SWITCH84_CORE_POSE_OR_INTERFACE_CHANGED"
}
set_ilm_type -model si
flatten_ilm
write_db $out/restored_full.db
puts TRI_ORACLE_MODEL_SWITCH84_COMPLETE_CORE_RESTORED
exit
