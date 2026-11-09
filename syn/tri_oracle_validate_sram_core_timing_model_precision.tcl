# Preserve the generated native comparison; replace its removed import method.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set top tri_oracle_sram_memory_compute
set base $root/.cache/physical/pnr/$top
set producer $base/hierarchy_timing_model_76
set inputs $base/hierarchy_timing_model_79_inputs
set out $base/hierarchy_timing_model_validation_79
if {[file exists $out]} {error "Existing timing-model validation"}
file mkdir $out
set_multi_cpu_usage -local_cpu 1
set_db design_process_node 28
set_db init_power_nets {VDD}
set_db init_ground_nets {VSS}
eval_legacy [list source $producer/native_validation/.var.tcl]
eval_legacy {set_global timing_prefix_module_name_with_library_genclk false}
eval_legacy {set_global timing_library_genclk_use_group_name true}
read_mmmc $inputs/mmmc.tcl
read_physical -lefs [list \
    $root/.cache/physical/routing_kit/N28_PRTF_Cad_v1d5a/PR_tech/Cadence/LefHeader/VHV/tsmcn28_10lm5X2Y2ZUTRDL.tlef \
    $root/.cache/physical/library/tcbn28hpcplusbwp12t40p140.lef \
    $base/hierarchy_export_58/core.lef]
read_netlist $producer/model_shell.v -top tri_oracle_core44_timing_shell
init_design
set_multi_cpu_usage -local_cpu 19
if {[llength [get_db insts]] != 1 || [llength [get_db ports]] != 3158} {
    error "Wrong extracted model shell or external interface"
}
set macro [lindex [get_db insts] 0]
if {[get_db $macro .base_cell.name] ne $top} {error "Wrong model master"}
set file [open $out/model_inventory.rpt w]
puts $file "instances: [llength [get_db insts]]"
puts $file "signal_ports: [llength [get_db ports]]"
puts $file "macro: [get_db $macro .base_cell.name]"
puts $file "macro_pins_including_internal_nodes: [llength [get_db $macro .pins]]"
puts $file "clock_objects: [sizeof_collection [get_clocks]]"
puts $file "scope: standalone model validation, not a placed or routed design"
close $file
foreach kind {setup hold} {
    file copy $producer/native_validation/pre_etm_${kind}.setup_typ.rpt \
        $out/pre_etm_${kind}.setup_typ.rpt
}
# Numeric limits, reporting options, model assertions and reference report bytes
# are unchanged. Only model initialization and output paths differ.
# Match the original reference reporting precision; no numeric constraints change.
set_db enable_ui_precision true
set_db ui_precision_timing 6
set_interactive_constraint_modes {functional}
eval_legacy [list source $inputs/validation_driver.tcl]
foreach kind {setup hold} {
    if {![file exists $out/${kind}.pre_vs_post.cmp]} {
        error "Missing actual native comparison report: $kind"
    }
}
puts TRI_ORACLE_CORE_TIMING_MODEL79_COMPARED
exit
