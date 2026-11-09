# Diagnosis only: test an explicit identity clock at the block boundary.
# SI remains enabled; full-control invariance is required before accepting a fix.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set top tri_oracle_sram_memory_compute
set base $root/.cache/physical/pnr/$top
set model $base/hierarchy_export_58
set out $base/hierarchy_clock_diagnostic_72
if {[file exists $out]} {error "Existing base-timing diagnosis"}
file mkdir $out
set_multi_cpu_usage -local_cpu 1
set_db design_process_node 28
set_db init_power_nets {VDD}
set_db init_ground_nets {VSS}
read_mmmc $base/routed_typical_repair_44.db/viewDefinition.tcl
update_constraint_mode -name functional \
    -sdc_files [list $base/hierarchy_generated_clock_72_inputs/functional.sdc] \
    -ilm_sdc_files [list $base/hierarchy_generated_clock_72_inputs/functional.sdc]
read_physical -lefs [list \
    $root/.cache/physical/routing_kit/N28_PRTF_Cad_v1d5a/PR_tech/Cadence/LefHeader/VHV/tsmcn28_10lm5X2Y2ZUTRDL.tlef \
    $root/.cache/physical/library/tcbn28hpcplusbwp12t40p140.lef \
    $root/.cache/physical/sram/core_weights_masks_01/ts5n28hpcpsvta32x128m2fw_130a/LEF/ts5n28hpcpsvta32x128m2fw_130a.lef \
    $root/.cache/physical/sram/core_outputs_01/ts6n28hpcpsvta16x128m2f_130a/LEF/ts6n28hpcpsvta16x128m2f_130a.lef \
    $root/.cache/physical/sram/activation_cache_banks_01/ts5n28hpcpsvta512x64m4f_130a/LEF/ts5n28hpcpsvta512x64m4f_130a.lef \
    $model/core.lef]
read_netlist $base/hierarchy_probe_60_inputs/wrapper.v -top tri_oracle_sram_core_hierarchy_probe
init_design
if {[llength [get_db insts]] != 1 || [llength [get_db ports]] != 3158} {
    error "Wrong one-core parent"
}
create_floorplan -site core12T -die_size {799.955 750 20 20 20 20}
place_inst core0 40 40 r0 -fixed
connect_global_net VDD -type pg_pin -pin_base_name VDD -all
connect_global_net VSS -type pg_pin -pin_base_name VSS -all
read_ilm -cell $top -directory $model/ilm
place_design
set_ilm_type -model si
flatten_ilm
set_multi_cpu_usage -local_cpu 19
set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}
set_db enable_ui_precision true
set_db ui_precision_timing 6
set_db timing_analysis_type ocv
set_db timing_analysis_cppr both

proc tri_oracle_si_clock_diagnostic_mode {} {
    # Keep the original production SI calculation and noisy reports enabled.
    set_db delaycal_enable_si true
    set_db si_delay_enable_report true
    set_db si_glitch_enable_report true
    set_db timing_max_transition_use_si_transition true
    set_db si_enable_drv_with_delta_slew true
    set_db opt_post_route_report_si_transitions true
}
source syn/tri_oracle_hierarchy_boundary_paths.tcl
foreach variant {compact full} {
    if {$variant eq {full}} {
        set_multi_cpu_usage -local_cpu 1
        unflatten_ilm
        read_ilm -cell $top -directory $base/hierarchy_full_control_68/ilm
        set_ilm_type -model si
        flatten_ilm
        set_multi_cpu_usage -local_cpu 19
    }
    set directory $out/$variant
    file mkdir $directory
    tri_oracle_si_clock_diagnostic_mode
    set expected [expr {$variant eq {compact} ? 33818 : 94471}]
    if {[llength [get_db insts]] != $expected} {error "Wrong base-timing model count"}
    if {[sizeof_collection [get_clocks]] != 6} {error "Missing view clocks"}
    set file [open $directory/mode_before.rpt w]
    puts $file "diagnostic_only: true"
    puts $file "instances: [llength [get_db insts]]"
    puts $file "delaycal_enable_si: [get_db delaycal_enable_si]"
    puts $file "timing_analysis_type: [get_db timing_analysis_type]"
    puts $file "timing_analysis_cppr: [get_db timing_analysis_cppr]"
    puts $file "timing_clocks: [sizeof_collection [get_clocks]]"
    close $file
    report_ilm_status > $directory/model_before.rpt
    foreach view {setup_slow setup_typ hold_fast} {
        report_clocks -view $view -hierarchy -description -source_insertion > $directory/clock_$view.rpt
    }
    tri_oracle_record_boundary_paths $directory
    if {![get_db delaycal_enable_si]} {error "SI diagnostic condition changed"}
    set file [open $directory/mode_after.rpt w]
    puts $file "delaycal_enable_si: [get_db delaycal_enable_si]"
    puts $file "model_type: [get_ilm_type -model]"
    puts $file "instances: [llength [get_db insts]]"
    close $file
}
puts TRI_ORACLE_SRAM_CORE_CLOCK72_DIAGNOSED
exit
