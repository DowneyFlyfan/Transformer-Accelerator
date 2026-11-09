# Electrical repair in a cold-qualified boundary-only parent; full restore follows.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set out $::env(TRI251_OUT)
set reference $::env(TRI251_REFERENCE)
set source_sdc $root/.cache/physical/synthesis/tri_oracle_predicted_feedforward_finish213/constraints.sdc
set_multi_cpu_usage -local_cpu 4
source $root/syn/tri_oracle_design242_metadata.tcl
source $root/syn/tri_oracle_preservation233.tcl
proc tri251_hierarchy {filename} {
    set stream [open $filename w]
    puts $stream "instance\tmodule\tdont_touch\tmodule_dont_touch"
    foreach hinst [get_db hinsts] {
        puts $stream "[get_db $hinst .name]\t[get_db $hinst .module.name]\t[get_db $hinst .dont_touch]\t[get_db $hinst .module.dont_touch]"
    }
    close $stream
}
proc tri251_port_poses {filename} {
    set stream [open $filename w]
    puts $stream "port\tdirection\tlocation\tlayer\tstatus\tphysical_pins"
    foreach port [get_db ports] {
        puts $stream [join [list [get_db $port .name] [get_db $port .direction] [get_db $port .location] [get_db $port .layer.name] [get_db $port .place_status] [llength [get_db $port .physical_pins]]] "\t"]
    }
    close $stream
}
proc tri251_macros {tag guidance} {
    global out
    set cores [get_db insts -if {.base_cell.name == tri_oracle_sram_memory_compute}]
    set banks [get_db insts -if {.base_cell.name == TS6N28HPCPSVTA16X128M2F}]
    if {[llength $cores]!=20 || [llength $banks]!=40} {error TRI251_WRONG_MACRO_SET}
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
                if {!$guidance || $pname ne "$name/_INT_clk_src_data_check_clk" || $net ne "" || $constant ne "no_constant"} {error TRI251_UNEXPECTED_INTERNAL_PIN}
                incr internal
            } else {incr count}
            puts $stream "$pname\t$direction\t$net\t$constant"
        }
        if {$count!=3158 || $internal!=$guidance} {error "TRI251_ORIGINAL_CORE_INTERFACE_CHANGED $name $count $internal"}
    }
    close $stream
}
proc tri251_reset_check {filename} {
    global root
    source $root/syn/tri_oracle_registered_reset_trace102.tcl
    source $root/syn/tri_oracle_check_registered_reset_fabric.tcl
    set masters [exec python3 -B -c {import json,sys; print(" ".join(json.load(open(sys.argv[1]))["flip_flop_cells"]))} $root/records/registered_reset34_sequential_masters.json]
    tri_oracle_require_parent_registered_resets $masters $filename
}

proc tri251_controllers {filename} {
    set stream [open $filename w]
    set count 0
    foreach cell [get_db insts] {
        set name [get_db $cell .name]
        if {![regexp {^numeric/engine/(gated/implementation/|backend/clusters\[[0-4]\]\.control/(down/engines\[[0-3]\]|projection/transfer)/implementation/)} $name]} {continue}
        puts $stream "$name\t[get_db $cell .base_cell.name]"
        incr count
    }
    close $stream
    if {$count!=382490} {error "TRI251_PROTECTED_CONTROLLER_CELL_COUNT_CHANGED $count"}
}

read_db $::env(TRI251_INPUT)
set_multi_cpu_usage -local_cpu 4
if {[get_db current_design .name] ne "tri_oracle_predicted_feedforward_frame" || [check_unique]!=1} {error TRI251_WRONG_OR_NONUNIQUE_PARENT}
tri242_require_design $reference/candidate_design.tsv $out/before_design.tsv
tri251_hierarchy $out/before_hierarchy.tsv
tri251_controllers $out/before_controller_cells.tsv
tri251_port_poses $out/before_port_poses.tsv
tri251_macros before 1
tri233_preservation $source_sdc $out/before_preservation.tsv 86
tri251_reset_check $out/before_reset_roots.tsv
write_sdc -view setup_typ $out/before_setup_typ.sdc
# Hold the original reset source registers fixed in identity/master during ECO.
# Their exact user flags are restored before candidate constraints are exported.
set stream [open $out/before_reset_roots.tsv r]
gets $stream header
set reset_roots [dict create]
while {[gets $stream line]>=0} {
    set fields [split $line "\t"]
    set names [split [lindex $fields 2] ,]
    set masters [split [lindex $fields 3] ,]
    set clocks [split [lindex $fields 4] ,]
    if {[llength $names]!=[llength $masters] || [llength $names]!=[llength $clocks]} {error TRI251_BAD_RESET_CHAIN}
    foreach name $names master $masters clock $clocks {
        if {[dict exists $reset_roots $name]} {continue}
        set instance [get_db insts $name]
        if {[llength $instance]!=1 || [get_db $instance .name] ne $name || [get_db $instance .base_cell.name] ne $master} {error "TRI251_RESET_SOURCE_CHANGED $name"}
        set flag [get_db $instance .dont_touch]
        if {$flag ni {none false true}} {error TRI251_UNSUPPORTED_RESET_FLAG}
        dict set reset_roots $name [list $master $clock $flag]
        set_db $instance .dont_touch true
    }
}
close $stream
if {[dict size $reset_roots]<1} {error TRI251_EMPTY_RESET_ROOT_SET}
set stream [open $out/temporary_reset_protection.tsv w]
puts $stream "instance\tmaster\tclock\toriginal_flag\ttemporary_flag"
dict for {name values} $reset_roots {puts $stream [join [concat [list $name] $values [list true]] "\t"]}
close $stream
set_db design_process_node 28
set_db enable_ui_precision true
set_db ui_precision_timing 6
set_db timing_analysis_type ocv
set_db timing_analysis_cppr both
set_db delaycal_enable_si true
set_db place_design_floorplan_mode false
set_db opt_fix_fanout_load true
# Read existing scale factors only. report_rc_factors calibrates and can
# route an unrouted design; perform that correlation after actual routing.
set rc [get_db rc_corners rc_typ]
if {[llength $rc]!=1} {error TRI251_WRONG_RC_CORNER}
set stream [open $out/original_rc_factors.tsv w]
puts $stream "attribute\tvalue"
foreach attribute {pre_route_res pre_route_cap pre_route_clock_res pre_route_clock_cap} {puts $stream "$attribute\t[get_db $rc .$attribute]"}
close $stream
time_design -pre_cts -drv_report -report_dir $out/before_timing -report_prefix before
report_timing -view setup_typ -check_type setup -max_paths 1 -max_slack 100 > $out/before_worst_path.rpt
opt_design -pre_cts -drv -report_dir $out/repair_reports -report_prefix repair
# Never publish the temporary reset protection as an original design constraint.
set stream [open $out/restored_reset_source_flags.tsv w]
puts $stream "instance\tmaster\tclock\tdont_touch"
dict for {name values} $reset_roots {
    lassign $values master clock flag
    set instance [get_db insts $name]
    if {[llength $instance]!=1 || [get_db $instance .base_cell.name] ne $master} {error "TRI251_OPTIMIZER_CHANGED_RESET_SOURCE $name"}
    set actual_clocks {}
    foreach pin [get_db $instance .pins] {if {[file tail [get_db $pin .base_pin.name]] eq "CP"} {lappend actual_clocks [get_db $pin .net.name]}}
    if {$actual_clocks ne [list $clock]} {error "TRI251_OPTIMIZER_CHANGED_RESET_CLOCK $name"}
    set_db $instance .dont_touch $flag
    puts $stream "$name\t$master\t$clock\t[get_db $instance .dont_touch]"
}
close $stream
place_detail
write_netlist $out/repaired_parent.v -exclude_leaf_cells
write_def $out/repaired_parent.def
write_db $out/repaired_candidate.db
set stream [open $out/candidate_scope.txt w]
puts $stream "UNQUALIFIED: boundary-only electrical candidate; full600-memory restoration, all3original-corner timing and mapped functional verification remain mandatory."
close $stream
tri242_require_design $reference/candidate_design.tsv $out/after_design.tsv
tri251_hierarchy $out/after_hierarchy.tsv
tri251_controllers $out/after_controller_cells.tsv
tri251_port_poses $out/after_port_poses.tsv
tri251_macros after 1
tri233_preservation $source_sdc $out/after_preservation.tsv 86
tri251_reset_check $out/after_reset_roots.tsv
check_place > $out/placement.rpt
write_sdc -view setup_typ $out/after_setup_typ.sdc
set stream [open $out/after_rc_factors.tsv w]
puts $stream "attribute\tvalue"
foreach attribute {pre_route_res pre_route_cap pre_route_clock_res pre_route_clock_cap} {puts $stream "$attribute\t[get_db $rc .$attribute]"}
close $stream
time_design -pre_cts -drv_report -report_dir $out/after_timing -report_prefix after
report_timing -view setup_typ -check_type setup -max_paths 1 -max_slack 100 > $out/after_worst_path.rpt
set paths [report_timing -view setup_typ -check_type setup -max_paths 1 -max_slack 100 -collection]
if {[sizeof_collection $paths]!=1} {error TRI251_MISSING_GUIDANCE_PATH}
set stream [open $out/guidance_slack.tsv w]
puts $stream "view\tslack_ns"
foreach_in_collection path $paths {puts $stream "setup_typ\t[get_property $path slack]"}
close $stream
puts TRI_ORACLE_FRAME251_BOUNDARY_ELECTRICAL_REPAIR_FINISHED_PENDING_FULL_RESTORE
exit
