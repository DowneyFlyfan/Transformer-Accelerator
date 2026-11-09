set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set top tri_oracle_predicted_feedforward_frame
set output $::env(TRI_ORACLE_SYNTH_OUTPUT)
set prepared $::env(TRI_ORACLE_PREOPT_SOURCE)
set_db fail_on_error_mesg true
set_db message:ELABUTL/ELABUTL-124 .severity Error
set_db message:ELABUTL/ELABUTL-123 .severity Error
read_db $prepared/elaborated.db
if {[llength [get_db designs]]!=1 || [get_db [get_db designs] .name] ne $top} {error FRAME145_WRONG_RESTORED_TOP}
set_db auto_ungroup none
set_db partition_based_synthesis false
set_db auto_partition false
set_db auto_super_thread false
set_db super_thread_servers {}
set_db max_cpus_per_server 18
set_db syn_global_effort none
set_db control_logic_optimization none
set_db syn_generic_effort low
set_db syn_map_effort medium
set_db syn_opt_effort medium
if {[get_db / .control_logic_optimization] ne "none" || [get_db / .syn_global_effort] ne "none"} {error FRAME145_UNEXPECTED_OPTIMIZER_OVERRIDE}
check_design -unresolved > $output/elaboration_check.rpt
check_design -undriven -multiple_driver -cross_hier > $output/elaboration_wiring.rpt
if {[check_design -undriven -multiple_driver -cross_hier -status]} {error FRAME139_UNDRIVEN_OR_MULTIDRIVEN_DESIGN}
set down_controls [get_db hinsts -if {.module.name == tri_oracle_down_executor_staged}]
set projection_controls [get_db hinsts -if {.module.name == tri_oracle_sparse_weight_dma_pipelined}]
if {[llength $down_controls]!=20 || [llength $projection_controls]!=5} {
    error "Staged source binding mismatch: [llength $down_controls] down controls, [llength $projection_controls] projection controls"
}
set staged_file [open $output/staged_control_bindings.tsv w]
puts $staged_file "instance\tmodule"
foreach control [concat $down_controls $projection_controls] {
    puts $staged_file "[get_db $control .name]\t[get_db $control .module.name]"
}
close $staged_file
puts TRI_ORACLE_FRAME145_STAGED_CONTROLS_20_DOWN_5_PROJECTION_BOUND
set boundary [open $output/mapped_controller_boundaries.tsv w]
puts $boundary "instance\thpin\thnet"
foreach group [list $down_controls $projection_controls] expected {6075 2840} {
    foreach control $group {
        set hpins [get_db $control .hpins]
        if {[llength $hpins]!=$expected} {error "FRAME139_BOUNDARY_WIDTH_MISMATCH: [get_db $control .name]"}
        foreach pin $hpins {
            set net [get_db $pin .hnet]
            if {[llength $net]!=1} {error "FRAME139_DISCONNECTED_BOUNDARY: [get_db $pin .name]"}
            puts $boundary "[get_db $control .name]\t[get_db $pin .name]\t[get_db $net .name]"
        }
    }
}
close $boundary
puts TRI_ORACLE_FRAME145_ALL_135700_CONTROLLER_BOUNDARY_BITS_CONNECTED
set reused_control_expected [dict create]
foreach control $down_controls {
    if {![get_db $control .preserve]} {error FRAME145_RESTORED_CONTROL_PRESERVATION_LOST}
    dict set reused_control_expected [get_db $control .name] 11049
}
foreach control $projection_controls {
    if {![get_db $control .preserve]} {error FRAME145_RESTORED_CONTROL_PRESERVATION_LOST}
    dict set reused_control_expected [get_db $control .name] 2047
}
proc snapshot_reused_controls131 {filename expected} {
    set current [dict create]
    foreach control [get_db hinsts] {
        set name [get_db $control .name]
        if {![dict exists $expected $name]} {continue}
        if {![get_db $control .preserve]} {error "FRAME131_REUSED_CONTROL_PRESERVATION_LOST: $name"}
        dict set current $name 0
    }
    if {[dict size $current]!=25} {error FRAME131_REUSED_CONTROL_HIERARCHY_LOST}
    set stream [open $filename w]
    foreach leaf [get_db insts] {
        set name [get_db $leaf .name]
        set master [get_db $leaf .base_cell.name]
        if {![string match *BWP12T40P140 $master]} {continue}
        foreach prefix [dict keys $expected] {
            if {[string first "${prefix}/" $name]!=0} {continue}
            dict incr current $prefix
            puts $stream "$name\t$master"
            break
        }
    }
    close $stream
    foreach prefix [dict keys $expected] {
        if {[dict get $current $prefix]!=[dict get $expected $prefix]} {
            error "FRAME131_REUSED_CONTROL_CELL_COUNT_CHANGED: $prefix [dict get $current $prefix] [dict get $expected $prefix]"
        }
    }
    exec env LC_ALL=C sort -o ${filename}.sorted $filename
}
snapshot_reused_controls131 $output/reused_controls_before.tsv $reused_control_expected
puts TRI_ORACLE_FRAME145_ALL_25_MAPPED_CONTROL_CELL_INVENTORIES_PRESERVED

proc verify_real_banks {filename preserve_now} {
    set cores [get_db insts -if {.base_cell.name == tri_oracle_sram_memory_compute}]
    set memories [get_db insts -if {.base_cell.name == TS6N28HPCPSVTA16X128M2F}]
    if {[llength $cores] != 20 || [llength $memories] != 40} {
        error "Expected20 full-core cells and40 aggregate memories; observed [llength $cores], [llength $memories]"
    }
    set file [open $filename w]
    puts $file "instance\tmaster\tarea_um2\tpreserve"
    foreach inst [concat $cores $memories] {
        if {$preserve_now} {set_db $inst .preserve true}
        if {![get_db $inst .preserve]} {error "Required core or bank lost preservation"}
        set area [get_db $inst .base_cell.area]
        if {[get_db $inst .base_cell.name] eq "tri_oracle_sram_memory_compute" &&
            abs($area - 482369.843750) > 0.01} {
            error "Core model area does not match the actual original footprint"
        }
        puts $file "[get_db $inst .name]\t[get_db $inst .base_cell.name]\t$area\t[get_db $inst .preserve]"
    }
    close $file
}
verify_real_banks $output/preserved_banks_before.tsv false
puts TRI_ORACLE_BOUNDARY_TRIAL_TWENTY_CORES_FORTY_BANKS_PRESERVED
write_sdc > $output/restored_constraints.sdc
set settings [open $output/flow_settings.rpt w]
foreach attribute {dp_analytical_opt control_logic_optimization syn_global_effort syn_generic_effort syn_map_effort syn_opt_effort} {
    puts $settings "$attribute: [get_db / .$attribute]"
}
close $settings
exec python3 -B $root/syn/tri_oracle_validate_cold_restore145.py $prepared $output
puts TRI_ORACLE_FRAME145_COLD_RESTORE_AND_ORIGINAL_CONSTRAINTS_VERIFIED
syn_generic
write_db $output/generic.db
puts "TRI_ORACLE_GENERIC_CHECKPOINT_WRITTEN $top"
syn_map
write_db $output/mapped.db
puts "TRI_ORACLE_MAPPED_CHECKPOINT_WRITTEN $top"
syn_opt
verify_real_banks $output/preserved_banks_after.tsv false
snapshot_reused_controls131 $output/reused_controls_after.tsv $reused_control_expected
if {[catch {exec cmp -s $output/reused_controls_before.tsv.sorted $output/reused_controls_after.tsv.sorted}]} {error FRAME131_REUSED_CONTROL_CELL_INVENTORY_CHANGED}
write_db $output/optimized.db
check_design -unresolved > $output/mapped_check.rpt
check_timing_intent -verbose > $output/timing_intent.rpt
report_area > $output/area.rpt
report_timing -max_paths 20 > $output/timing.rpt
write_hdl > $output/netlist.v
write_sdc > $output/constraints.sdc
puts "TRI_ORACLE_FRAME145_SYNTHESIS_PASS $top"
exit
