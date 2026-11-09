# Scale the native-qualified fresh import protocol to the actual placed parent.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set parent $::env(TRI242_PARENT)
set out $::env(TRI242_OUT)
set mode $::env(TRI242_MODE)
set reference $::env(TRI242_REFERENCE)
set top tri_oracle_predicted_feedforward_frame
set base $root/.cache/physical/pnr/tri_oracle_sram_memory_compute
set source_sdc $root/.cache/physical/synthesis/tri_oracle_predicted_feedforward_finish213/constraints.sdc
set_multi_cpu_usage -local_cpu 8
source $root/syn/tri_oracle_unique215_snapshot.tcl
source $root/syn/tri_oracle_preservation233.tcl
source $root/syn/tri_oracle_design242_metadata.tcl
proc tri242_hierarchy {filename} {
    set stream [open $filename w]
    puts $stream "instance\tmodule\tdont_touch\tmodule_dont_touch"
    foreach hinst [get_db hinsts] {
        puts $stream "[get_db $hinst .name]\t[get_db $hinst .module.name]\t[get_db $hinst .dont_touch]\t[get_db $hinst .module.dont_touch]"
    }
    close $stream
}
proc tri242_port_poses {filename} {
    set stream [open $filename w]
    puts $stream "port\tdirection\tlocation\tlayer\tstatus\tphysical_pins"
    foreach port [get_db ports] {
        puts $stream [join [list [get_db $port .name] [get_db $port .direction] [get_db $port .location] [get_db $port .layer.name] [get_db $port .place_status] [llength [get_db $port .physical_pins]]] "\t"]
    }
    close $stream
}
proc tri242_macros {tag guidance} {
    global out
    set cores [get_db insts -if {.base_cell.name == tri_oracle_sram_memory_compute}]
    set banks [get_db insts -if {.base_cell.name == TS6N28HPCPSVTA16X128M2F}]
    if {[llength $cores]!=20 || [llength $banks]!=40} {error TRI242_WRONG_MACRO_SET}
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
                if {!$guidance || $pname ne "$name/_INT_clk_src_data_check_clk" || $net ne "" || $constant ne "no_constant"} {error TRI242_UNEXPECTED_INTERNAL_PIN}
                incr internal
            } else {incr count}
            puts $stream "$pname\t$direction\t$net\t$constant"
        }
        if {$count!=3158 || $internal!=$guidance} {error "TRI242_ORIGINAL_CORE_INTERFACE_CHANGED $name $count $internal"}
    }
    close $stream
}
proc tri242_reset_check {filename} {
    global root
    source $root/syn/tri_oracle_registered_reset_trace102.tcl
    source $root/syn/tri_oracle_check_registered_reset_fabric.tcl
    set masters [exec python3 -B -c {import json,sys; print(" ".join(json.load(open(sys.argv[1]))["flip_flop_cells"]))} $root/records/registered_reset34_sequential_masters.json]
    tri_oracle_require_parent_registered_resets $masters $filename
}
if {$mode eq "reference"} {
    read_db $::env(TRI242_INPUT)
    set_multi_cpu_usage -local_cpu 8
    if {[get_db current_design .name] ne $top} {error TRI242_WRONG_REFERENCE_PARENT}
    unflatten_ilm
    if {[check_unique]!=1 || [llength [get_db insts]]!=673622} {error TRI242_REFERENCE_NOT_UNIQUE_OR_INCOMPLETE}
    tri242_design_snapshot $out/reference_design.tsv
    tri242_hierarchy $out/reference_hierarchy.tsv
    tri242_port_poses $out/reference_port_poses.tsv
    tri242_macros reference 0
    tri233_preservation $source_sdc $out/reference_preservation.tsv 86
    puts TRI_ORACLE_FRESH242_REFERENCE_METADATA_EXPORTED
    exit
}
if {$mode eq "guide"} {
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
    read_netlist $parent/parent_import.v -top $top
    init_design
    read_def $reference/unique_parent.def
    tri242_restore_design $parent/reference/reference_design.tsv
    set stream [open $reference/before_cells.tsv r]
    gets $stream header
    set count 0
    while {[gets $stream line]>=0} {
        lassign [split $line "\t"] name master location orientation status flag
        if {$flag ni {none false true}} {error "TRI242_UNSUPPORTED_LEAF_FLAG $name $flag"}
        set instance [get_db insts $name]
        if {[llength $instance]!=1 || [get_db $instance .name] ne $name || [get_db $instance .base_cell.name] ne $master} {error "TRI242_LEAF_TARGET_CHANGED $name"}
        if {[get_db $instance .dont_touch] ne $flag} {set_db $instance .dont_touch $flag}
        incr count
    }
    close $stream
    if {$count!=673622 || $count!=[llength [get_db insts]]} {error TRI242_LEAF_INVENTORY_CHANGED}
    set stream [open $parent/reference/reference_hierarchy.tsv r]
    gets $stream header
    set count 0
    while {[gets $stream line]>=0} {
        lassign [split $line "\t"] name module flag module_flag
        if {$flag ni {none false true} || $module_flag ni {none false true}} {error "TRI242_UNSUPPORTED_HIERARCHY_FLAG $name $flag $module_flag"}
        set hinst [get_db hinsts $name]
        if {[llength $hinst]!=1 || [get_db $hinst .name] ne $name || [get_db $hinst .module.name] ne $module} {error "TRI242_HIERARCHY_TARGET_CHANGED $name"}
        if {[get_db $hinst .dont_touch] ne $flag} {set_db $hinst .dont_touch $flag}
        if {[get_db $hinst .module.dont_touch] ne $module_flag} {set_db [get_db $hinst .module] .dont_touch $module_flag}
        incr count
    }
    close $stream
    if {$count!=[llength [get_db hinsts]]} {error TRI242_HIERARCHY_INVENTORY_CHANGED}
} elseif {$mode eq "cold"} {
    read_db $::env(TRI242_INPUT)
    set_multi_cpu_usage -local_cpu 8
} else {error TRI242_BAD_MODE}
if {[get_db current_design .name] ne $top || [check_unique]!=1} {error TRI242_IMPORTED_PARENT_NOT_UNIQUE}
tri242_require_design $parent/reference/reference_design.tsv $out/candidate_design.tsv
tri215_snapshot $out candidate
tri242_hierarchy $out/candidate_hierarchy.tsv
tri242_port_poses $out/candidate_port_poses.tsv
tri242_macros candidate 1
tri233_preservation $source_sdc $out/candidate_preservation.tsv 86
tri242_reset_check $out/registered_reset_roots.tsv
check_place > $out/placement.rpt
write_sdc -view setup_typ $out/setup_typ.sdc
report_ilm_status > $out/model_status.rpt
if {$mode eq "guide"} {
    write_db $out/guidance.db
    puts TRI_ORACLE_FRESH242_WHOLE_PARENT_GUIDANCE_IMPORTED
} else {puts TRI_ORACLE_FRESH242_COLD_WHOLE_PARENT_GUIDANCE_VERIFIED}
exit
