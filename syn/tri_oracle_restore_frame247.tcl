# Export the repaired boundary parent, then use a fresh full-model context.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set out $::env(TRI247_OUT)
set parent $::env(TRI247_PARENT)
set mode $::env(TRI247_MODE)
set base $root/.cache/physical/pnr/tri_oracle_sram_memory_compute
set source_sdc $root/.cache/physical/synthesis/tri_oracle_predicted_feedforward_finish213/constraints.sdc
set_multi_cpu_usage -local_cpu 4
source $root/syn/tri_oracle_unique215_snapshot.tcl
source $root/syn/tri_oracle_preservation233.tcl
source $root/syn/tri_oracle_design242_metadata.tcl
proc tri247_hierarchy {filename} {
    set stream [open $filename w]
    puts $stream "instance\tmodule\tdont_touch\tmodule_dont_touch"
    foreach hinst [get_db hinsts] {
        puts $stream "[get_db $hinst .name]\t[get_db $hinst .module.name]\t[get_db $hinst .dont_touch]\t[get_db $hinst .module.dont_touch]"
    }
    close $stream
}
proc tri247_port_poses {filename} {
    set stream [open $filename w]
    puts $stream "port\tdirection\tlocation\tlayer\tstatus\tphysical_pins"
    foreach port [get_db ports] {
        puts $stream [join [list [get_db $port .name] [get_db $port .direction] [get_db $port .location] [get_db $port .layer.name] [get_db $port .place_status] [llength [get_db $port .physical_pins]]] "\t"]
    }
    close $stream
}
proc tri247_macros {tag guidance} {
    global out
    set cores [get_db insts -if {.base_cell.name == tri_oracle_sram_memory_compute}]
    set banks [get_db insts -if {.base_cell.name == TS6N28HPCPSVTA16X128M2F}]
    if {[llength $cores]!=20 || [llength $banks]!=40} {error TRI247_WRONG_MACRO_SET}
    set halos [open $out/[set tag]_halos.tsv w]
    puts $halos "instance\tmaster\tlocation\torientation\tstatus\tdont_touch\thas_halo\tleft\tbottom\tright\ttop"
    foreach instance [concat $cores $banks] {
        puts $halos [join [list [get_db $instance .name] [get_db $instance .base_cell.name] [get_db $instance .location] [get_db $instance .orient] [get_db $instance .place_status] [get_db $instance .dont_touch] [get_db $instance .is_place_halo] [get_db $instance .place_halo_left] [get_db $instance .place_halo_bottom] [get_db $instance .place_halo_right] [get_db $instance .place_halo_top]] "\t"]
    }
    close $halos
    set stream [open $out/[set tag]_core_pins.tsv w]
    puts $stream "pin\tdirection\tnet\tconstant"
    foreach core $cores {
        set count 0
        set internal 0
        set name [get_db $core .name]
        foreach pin [get_db $core .pins] {
            set pname [get_db $pin .name]
            set direction [get_db $pin .direction]
            set net [get_db $pin .net.name]
            set constant [get_db $pin .constant]
            if {$direction eq "internal"} {
                if {!$guidance || $pname ne "$name/_INT_clk_src_data_check_clk" || $net ne "" || $constant ne "no_constant"} {error TRI247_UNEXPECTED_INTERNAL_PIN}
                incr internal
            } else {incr count}
            puts $stream "$pname\t$direction\t$net\t$constant"
        }
        if {$count!=3158 || $internal!=$guidance} {error "TRI247_ORIGINAL_CORE_INTERFACE_CHANGED $name $count $internal"}
    }
    close $stream
}
proc tri247_reset_check {filename} {
    global root
    source $root/syn/tri_oracle_registered_reset_trace102.tcl
    source $root/syn/tri_oracle_check_registered_reset_fabric.tcl
    set masters [exec python3 -B -c {import json,sys; print(" ".join(json.load(open(sys.argv[1]))["flip_flop_cells"]))} $root/records/registered_reset34_sequential_masters.json]
    tri_oracle_require_parent_registered_resets $masters $filename
}

proc tri247_controllers {filename} {
    set stream [open $filename w]
    set count 0
    foreach cell [get_db insts] {
        set name [get_db $cell .name]
        if {![regexp {^numeric/engine/(gated/implementation/|backend/clusters\[[0-4]\]\.control/(down/engines\[[0-3]\]|projection/transfer)/implementation/)} $name]} {continue}
        puts $stream "$name\t[get_db $cell .base_cell.name]"
        incr count
    }
    close $stream
    if {$count!=382490} {error "TRI247_PROTECTED_CONTROLLER_CELL_COUNT_CHANGED $count"}
}


proc tri247_parent_evidence {tag guidance} {
    global out source_sdc
    tri215_snapshot $out $tag
    tri242_design_snapshot $out/[set tag]_design.tsv
    tri247_hierarchy $out/[set tag]_hierarchy.tsv
    tri247_port_poses $out/[set tag]_port_poses.tsv
    tri247_macros $tag $guidance
    tri247_controllers $out/[set tag]_controller_cells.tsv
    tri233_preservation $source_sdc $out/[set tag]_preservation.tsv 86
    tri247_reset_check $out/[set tag]_reset_roots.tsv
    check_place > $out/[set tag]_placement.rpt
}
proc tri247_full_evidence {} {
    global out
    set_ilm_type -model si
    flatten_ilm
    set input [open $::env(TRI247_PREFIXES) r]
    set prefixes [split [string trim [read $input]] "\n"]
    close $input
    set counts [dict create]
    foreach prefix $prefixes {dict set counts $prefix 0}
    if {[dict size $counts]!=20} {error TRI247_WRONG_CORE_PREFIXES}
    set stream [open $out/core_cells.tsv w]
    puts $stream "instance\tmaster\tlocation\torientation"
    foreach instance [get_db insts] {
        set name [get_db $instance .name]
        if {![regexp {^(.*clusters\[[0-9]+\]\.cluster/cores\[[0-9]+\])/(.+)$} $name -> prefix local]} {continue}
        if {![dict exists $counts $prefix]} {error TRI247_UNEXPECTED_CORE}
        dict incr counts $prefix
        puts $stream "$name\t[get_db $instance .base_cell.name]\t[get_db $instance .location]\t[get_db $instance .orient]"
    }
    close $stream
    dict for {prefix count} $counts {if {$count!=94471} {error "TRI247_INCOMPLETE_ORIGINAL_CORE $prefix $count"}}
    foreach master {TS5N28HPCPSVTA32X128M2FW TS5N28HPCPSVTA512X64M4F TS6N28HPCPSVTA16X128M2F} expected {360 40 200} {
        if {[llength [get_db insts -if ".base_cell.name == $master"]]!=$expected} {error TRI247_WRONG_FULL_MEMORY_COUNT}
    }
    report_ilm_status > $out/full_model_status.rpt
    foreach view {setup_slow setup_typ hold_fast} {
        set_analysis_view -setup [list $view] -hold [list $view]
        if {[sizeof_collection [get_clocks core_clock]]!=1} {error TRI247_MISSING_ORIGINAL_CLOCK}
        write_sdc -view $view $out/[set view].sdc
    }
    set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}
}
if {$mode eq "reference"} {
    read_db $::env(TRI247_INPUT)
    set_multi_cpu_usage -local_cpu 4
    if {[get_db current_design .name] ne "tri_oracle_predicted_feedforward_frame" || [check_unique]!=1} {error TRI247_WRONG_GUIDANCE_SOURCE}
    tri247_parent_evidence reference 1
    write_sdc -view setup_typ $out/setup_typ.sdc
    write_netlist $out/parent.v -exclude_leaf_cells
    write_def $out/parent.def
    puts TRI_ORACLE_FRAME247_REPAIRED_REFERENCE_EXPORTED
    exit
}
if {$mode eq "full"} {
    set_db init_design_uniquify false
    set_db init_power_nets {VDD}
    set_db init_ground_nets {VSS}
    set_db design_process_node 28
    read_mmmc $parent/full_mmmc.tcl
    read_physical -lefs [list \
        $root/.cache/physical/routing_kit/N28_PRTF_Cad_v1d5a/PR_tech/Cadence/LefHeader/VHV/tsmcn28_10lm5X2Y2ZUTRDL.tlef \
        $root/.cache/physical/library/tcbn28hpcplusbwp12t40p140.lef \
        $root/.cache/physical/sram/core_weights_masks_01/ts5n28hpcpsvta32x128m2fw_130a/LEF/ts5n28hpcpsvta32x128m2fw_130a.lef \
        $root/.cache/physical/sram/core_outputs_01/ts6n28hpcpsvta16x128m2f_130a/LEF/ts6n28hpcpsvta16x128m2f_130a.lef \
        $root/.cache/physical/sram/activation_cache_banks_01/ts5n28hpcpsvta512x64m4f_130a/LEF/ts5n28hpcpsvta512x64m4f_130a.lef \
        $base/hierarchy_export_58/core.lef]
    read_netlist $parent/parent_import.v -top tri_oracle_predicted_feedforward_frame
    init_design
    read_def $parent/reference/parent.def
    tri242_restore_design $parent/reference/reference_design.tsv
    set input [open $parent/reference/reference_cells.tsv r]
    gets $input header
    set count 0
    while {[gets $input line]>=0} {
        lassign [split $line "\t"] name master location orientation status flag
        if {$flag ni {none false true delete_ok const_prop_size_delete_ok const_prop_delete_ok size_delete_ok size_ok size_same_height_ok size_same_footprint_ok map_size_ok}} {error "TRI247_UNSUPPORTED_DOCUMENTED_LEAF_FLAG $name $flag"}
        set instance [get_db insts $name]
        if {[llength $instance]!=1 || [get_db $instance .name] ne $name || [get_db $instance .base_cell.name] ne $master} {error TRI247_LEAF_TARGET_CHANGED}
        if {[get_db $instance .dont_touch] ne $flag} {set_db $instance .dont_touch $flag}
        incr count
    }
    close $input
    if {$count!=[llength [get_db insts]]} {error TRI247_REPAIRED_LEAF_INVENTORY_CHANGED}
    set input [open $parent/reference/reference_hierarchy.tsv r]
    gets $input header
    set count 0
    while {[gets $input line]>=0} {
        lassign [split $line "\t"] name module flag module_flag
        if {$flag ni {none false true} || $module_flag ni {none false true}} {error TRI247_UNSUPPORTED_HIERARCHY_FLAG}
        set hinst [get_db hinsts $name]
        if {[llength $hinst]!=1 || [get_db $hinst .name] ne $name || [get_db $hinst .module.name] ne $module} {error TRI247_HIERARCHY_TARGET_CHANGED}
        if {[get_db $hinst .dont_touch] ne $flag} {set_db $hinst .dont_touch $flag}
        if {[get_db $hinst .module.dont_touch] ne $module_flag} {set_db [get_db $hinst .module] .dont_touch $module_flag}
        incr count
    }
    close $input
    if {$count!=[llength [get_db hinsts]]} {error TRI247_HIERARCHY_INVENTORY_CHANGED}
    tri247_parent_evidence imported 0
    read_ilm -cell tri_oracle_sram_memory_compute -directory $base/hierarchy_full_control_68/ilm
    tri247_full_evidence
    write_db $out/restored_full.db
} elseif {$mode eq "cold"} {
    read_db $::env(TRI247_INPUT)
    set_multi_cpu_usage -local_cpu 4
    unflatten_ilm
    tri247_full_evidence
} else {error TRI247_BAD_MODE}
unflatten_ilm
tri247_parent_evidence restored 0
if {$mode eq "full"} {
    write_netlist $out/restored_parent.v -exclude_leaf_cells
    write_def $out/restored_parent.def
}
puts "TRI_ORACLE_FRAME247_ALL_ORIGINAL_CORES_VERIFIED $mode"
exit
