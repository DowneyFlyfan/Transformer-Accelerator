# Cold guidance and fresh full-model restoration use separate native contexts.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set out $::env(TRI241_OUT)
set parent $::env(TRI241_PARENT)
set mode $::env(TRI241_MODE)
set base $root/.cache/physical/pnr/tri_oracle_sram_memory_compute
set_multi_cpu_usage -local_cpu 8
source $root/syn/tri_oracle_unique215_snapshot.tcl
proc tri241_pins {filename} {
    set block [get_db insts core0]
    if {[llength $block]!=1 || [get_db $block .base_cell.name] ne "tri_oracle_sram_memory_compute"} {error TRI241_MISSING_PHYSICAL_CORE}
    set stream [open $filename w]
    puts $stream "pin\tdirection\tnet\tconstant"
    foreach pin [get_db $block .pins] {puts $stream "[get_db $pin .name]\t[get_db $pin .direction]\t[get_db $pin .net.name]\t[get_db $pin .constant]"}
    close $stream
}
proc tri241_full_evidence {} {
    global out
    set_ilm_type -model si
    flatten_ilm
    set count 0
    set stream [open $out/core_cells.tsv w]
    puts $stream "instance\tmaster\tlocation\torientation"
    foreach instance [get_db insts] {
        set name [get_db $instance .name]
        if {![string match {core0/*} $name]} {continue}
        puts $stream "$name\t[get_db $instance .base_cell.name]\t[get_db $instance .location]\t[get_db $instance .orient]"
        incr count
    }
    close $stream
    if {$count!=94471} {error TRI241_INCOMPLETE_ORIGINAL_CORE}
    foreach master {TS5N28HPCPSVTA32X128M2FW TS5N28HPCPSVTA512X64M4F TS6N28HPCPSVTA16X128M2F} expected {18 2 8} {
        if {[llength [get_db insts -if ".base_cell.name == $master"]]!=$expected} {error TRI241_WRONG_MEMORY_COUNT}
    }
    report_ilm_status > $out/model_status.rpt
    foreach view {setup_slow setup_typ hold_fast} {
        set_analysis_view -setup [list $view] -hold [list $view]
        if {[sizeof_collection [get_clocks core_clock]]!=1} {error TRI241_WRONG_CLOCK_COUNT}
        write_sdc -view $view $out/[set view].sdc
    }
    set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}
}
if {$mode eq "cold_guide"} {
    read_db $::env(TRI241_INPUT)
    set_multi_cpu_usage -local_cpu 8
    tri215_snapshot $out cold_guide
    tri241_pins $out/cold_guide_core_pins.tsv
    write_sdc -view setup_typ $out/setup_typ.sdc
    write_netlist $out/parent.v -exclude_leaf_cells
    write_def $out/parent.def
    puts TRI_ORACLE_FRESH241_COLD_GUIDANCE_EXPORTED
    exit
}
if {$mode eq "fresh_full"} {
    set_db init_design_uniquify false
    set_db init_power_nets {VDD}
    set_db init_ground_nets {VSS}
    read_mmmc $parent/full_mmmc.tcl
    read_physical -lefs [list \
        $root/.cache/physical/routing_kit/N28_PRTF_Cad_v1d5a/PR_tech/Cadence/LefHeader/VHV/tsmcn28_10lm5X2Y2ZUTRDL.tlef \
        $root/.cache/physical/library/tcbn28hpcplusbwp12t40p140.lef \
        $root/.cache/physical/sram/core_weights_masks_01/ts5n28hpcpsvta32x128m2fw_130a/LEF/ts5n28hpcpsvta32x128m2fw_130a.lef \
        $root/.cache/physical/sram/core_outputs_01/ts6n28hpcpsvta16x128m2f_130a/LEF/ts6n28hpcpsvta16x128m2f_130a.lef \
        $root/.cache/physical/sram/activation_cache_banks_01/ts5n28hpcpsvta512x64m4f_130a/LEF/ts5n28hpcpsvta512x64m4f_130a.lef \
        $base/hierarchy_export_58/core.lef]
    read_netlist $parent/parent_import.v -top tri_oracle_preserved_placement_probe21
    init_design
    read_def $parent/cold_guide/parent.def
    set input [open $parent/cold_guide/cold_guide_cells.tsv r]
    gets $input header
    while {[gets $input line]>=0} {
        lassign [split $line "\t"] name master location orientation status protected
        if {$protected ni {none false true}} {error TRI241_UNSUPPORTED_REFERENCE_FLAG}
        set instance [get_db insts $name]
        if {[llength $instance]!=1 || [get_db $instance .name] ne $name || [get_db $instance .base_cell.name] ne $master} {error TRI241_METADATA_TARGET_CHANGED}
        set_db $instance .dont_touch $protected
    }
    close $input
    tri215_snapshot $out before_full
    tri241_pins $out/before_full_core_pins.tsv
    read_ilm -cell tri_oracle_sram_memory_compute -directory $base/hierarchy_full_control_68/ilm
    tri241_full_evidence
    write_db $out/restored_full.db
} elseif {$mode eq "cold_full"} {
    read_db $::env(TRI241_INPUT)
    set_multi_cpu_usage -local_cpu 8
    unflatten_ilm
    tri241_full_evidence
} else {error TRI241_UNKNOWN_MODE}
unflatten_ilm
tri215_snapshot $out restored_parent
tri241_pins $out/restored_core_pins.tsv
puts "TRI_ORACLE_FRESH241_FULL_MODEL_VERIFIED $mode"
exit
