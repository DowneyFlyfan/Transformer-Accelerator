# Start guidance in a new design; never reset/swap a live full ILM context.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set out $::env(TRI239_OUT)
set parent $::env(TRI239_PARENT)
set mode $::env(TRI239_MODE)
set component tri_oracle_sram_memory_compute
set base $root/.cache/physical/pnr/$component
set_multi_cpu_usage -local_cpu 2
source $root/syn/tri_oracle_unique215_snapshot.tcl
proc tri239_dump_pins {filename} {
    set block [get_db insts core0]
    if {[llength $block]!=1 || [get_db $block .base_cell.name] ne "tri_oracle_sram_memory_compute"} {error TRI239_CORE_NOT_FOUND}
    set stream [open $filename w]
    puts $stream "pin\tdirection\tnet\tconstant"
    foreach pin [get_db $block .pins] {puts $stream "[get_db $pin .name]\t[get_db $pin .direction]\t[get_db $pin .net.name]\t[get_db $pin .constant]"}
    close $stream
}
if {$mode eq "export"} {
    read_db $::env(TRI239_INPUT)
    set_multi_cpu_usage -local_cpu 2
    if {[get_db current_design .name] ne "tri_oracle_preserved_placement_probe21"} {error TRI239_WRONG_PARENT}
    unflatten_ilm
    set_ilm_type -model si
    flatten_ilm
    set stream [open $out/full_before.tsv w]
    puts $stream "instance\tmaster\tlocation\torientation"
    set count 0
    foreach instance [get_db insts] {
        set name [get_db $instance .name]
        if {![string match {core0/*} $name]} {continue}
        puts $stream "$name\t[get_db $instance .base_cell.name]\t[get_db $instance .location]\t[get_db $instance .orient]"
        incr count
    }
    close $stream
    if {$count!=94471} {error TRI239_INCOMPLETE_FULL_REFERENCE}
    foreach view {setup_slow setup_typ hold_fast} {
        set_analysis_view -setup [list $view] -hold [list $view]
        write_sdc -view $view $out/[set view].sdc
    }
    unflatten_ilm
    tri215_snapshot $out original
    tri239_dump_pins $out/original_core_pins.tsv
    write_netlist $out/parent.v -exclude_leaf_cells
    write_def $out/parent.def
    puts TRI_ORACLE_FRESH239_REFERENCE_EXPORTED
    exit
}
if {$mode ne "guide"} {error TRI239_BAD_MODE}
set_db init_design_uniquify false
set_db init_power_nets {VDD}
set_db init_ground_nets {VSS}
read_mmmc $parent/guide_mmmc.tcl
read_physical -lefs [list \
 $root/.cache/physical/routing_kit/N28_PRTF_Cad_v1d5a/PR_tech/Cadence/LefHeader/VHV/tsmcn28_10lm5X2Y2ZUTRDL.tlef \
 $root/.cache/physical/library/tcbn28hpcplusbwp12t40p140.lef \
 $root/.cache/physical/sram/core_weights_masks_01/ts5n28hpcpsvta32x128m2fw_130a/LEF/ts5n28hpcpsvta32x128m2fw_130a.lef \
 $root/.cache/physical/sram/core_outputs_01/ts6n28hpcpsvta16x128m2f_130a/LEF/ts6n28hpcpsvta16x128m2f_130a.lef \
 $root/.cache/physical/sram/activation_cache_banks_01/ts5n28hpcpsvta512x64m4f_130a/LEF/ts5n28hpcpsvta512x64m4f_130a.lef \
 $base/hierarchy_export_58/core.lef]
read_netlist $parent/parent_import.v -top tri_oracle_preserved_placement_probe21
init_design
read_def $parent/export/parent.def
# DEF does not promise optimization attributes. Transfer each exact leaf flag
# explicitly from the accepted reference, before strict graph/property checks.
set input [open $parent/export/original_cells.tsv r]
gets $input header
set count 0
while {[gets $input line]>=0} {
    lassign [split $line "\t"] name master location orientation status protected
    # dont_touch is an enum: retain the exact unset/false/true value.
    if {$protected ni {none false true}} {error TRI239_UNSUPPORTED_REFERENCE_FLAG}
    set instance [get_db insts $name]
    if {[llength $instance]!=1 || [get_db $instance .name] ne $name || [get_db $instance .base_cell.name] ne $master} {error "TRI239_METADATA_TARGET_CHANGED $name"}
    set_db $instance .dont_touch $protected
    incr count
}
close $input
if {$count!=[llength [get_db insts]]} {error TRI239_PARENT_LEAF_COUNT_CHANGED}
tri215_snapshot $out guidance
tri239_dump_pins $out/guidance_core_pins.tsv
write_sdc -view setup_typ $out/guidance_setup_typ.sdc
report_timing -view setup_typ -check_type setup -max_paths 1 -max_slack 100 > $out/guidance_path.rpt
report_ilm_status > $out/model_status.rpt
write_netlist $out/guidance_parent.v -exclude_leaf_cells
write_def $out/guidance_parent.def
write_db $out/guidance.db
puts TRI_ORACLE_FRESH239_GUIDANCE_IMPORTED
exit
