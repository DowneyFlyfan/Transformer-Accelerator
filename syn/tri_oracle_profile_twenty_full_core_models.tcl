# Resource/floorplan probe, not whole-processor routing or timing qualification.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set component tri_oracle_sram_memory_compute
set top tri_oracle_twenty_core_capacity_probe
set base $root/.cache/physical/pnr/$component
set out $base/hierarchy_full_twenty_core_75
if {[file exists $out]} {error "Existing full twenty-core profile"}
file mkdir $out
set_multi_cpu_usage -local_cpu 1
set_db design_process_node 28
set_db init_power_nets {VDD}
set_db init_ground_nets {VSS}
read_mmmc $base/routed_typical_repair_44.db/viewDefinition.tcl
update_constraint_mode -name functional \
    -sdc_files [list $base/hierarchy_twenty_core_75_inputs/functional.sdc] \
    -ilm_sdc_files [list $base/hierarchy_twenty_core_75_inputs/functional.sdc]
read_physical -lefs [list \
    $root/.cache/physical/routing_kit/N28_PRTF_Cad_v1d5a/PR_tech/Cadence/LefHeader/VHV/tsmcn28_10lm5X2Y2ZUTRDL.tlef \
    $root/.cache/physical/library/tcbn28hpcplusbwp12t40p140.lef \
    $root/.cache/physical/sram/core_weights_masks_01/ts5n28hpcpsvta32x128m2fw_130a/LEF/ts5n28hpcpsvta32x128m2fw_130a.lef \
    $root/.cache/physical/sram/core_outputs_01/ts6n28hpcpsvta16x128m2f_130a/LEF/ts6n28hpcpsvta16x128m2f_130a.lef \
    $root/.cache/physical/sram/activation_cache_banks_01/ts5n28hpcpsvta512x64m4f_130a/LEF/ts5n28hpcpsvta512x64m4f_130a.lef \
    $base/hierarchy_export_58/core.lef]
read_netlist $base/hierarchy_twenty_core_75_inputs/wrapper.v -top $top
init_design
if {[get_db current_design .name] ne $top} {error "Wrong twenty-core top"}
if {[llength [get_db insts]] != 20 || [llength [get_db ports]] != 63122} {
    error "Wrong full twenty-core parent or port count"
}
create_floorplan -site core12T -no_snap_to_grid -die_size {3600 3600 20 20 20 20}
set file [open $out/macro_instances.tsv w]
puts $file "instance\tmaster\trequested_x_um\trequested_y_um"
for {set i 0} {$i < 20} {incr i} {
    set inst [get_db insts core$i]
    if {[get_db $inst .base_cell.name] ne $component ||
        [llength [get_db $inst .pins]] != 3158} {error "Wrong full-core macro: $i"}
    set x [expr {210.0 + ($i % 4)*819.955}]
    set y [expr {45.0 + ($i / 4)*710.0}]
    place_inst $inst $x $y r0 -fixed
    puts $file "core$i\t$component\t$x\t$y"
}
close $file
connect_global_net VDD -type pg_pin -pin_base_name VDD -all
connect_global_net VSS -type pg_pin -pin_base_name VSS -all
check_place > $out/macro_placement.rpt
write_def $out/macro_floorplan.def
puts TRI_ORACLE_TWENTY75_MACRO_FLOORPLAN_RECORDED

# Read one complete master model for twenty independent physical instances.
set_multi_cpu_usage -local_cpu 19
read_ilm -cell $component -directory $base/hierarchy_full_control_68/ilm
place_design
set_ilm_type -model si
flatten_ilm
report_ilm_status > $out/full_model_status.rpt
set count [llength [get_db insts]]
if {$count != 1889420} {error "Full core instances missing: $count"}
if {[sizeof_collection [get_clocks]] != 3} {error "Missing shared view clocks"}
set file [open $out/full_inventory.rpt w]
puts $file "full_instances: $count"
puts $file "cores: 20"
puts $file "parent_port_bits: [llength [get_db ports]]"
puts $file "timing_clocks: [sizeof_collection [get_clocks]]"
set macros 0
foreach kind {TS5N28HPCPSVTA32X128M2FW TS5N28HPCPSVTA512X64M4F TS6N28HPCPSVTA16X128M2F} expected {360 40 160} {
    set instances [get_db insts -if ".base_cell.name == $kind"]
    set observed [llength $instances]
    if {$observed != $expected} {error "Wrong actual memory macro count: $kind $observed"}
    puts $file "$kind: $observed"
    incr macros $observed
}
puts $file "memory_macros: $macros"
puts $file "core_memory_bytes: 389120"
close $file
puts TRI_ORACLE_TWENTY75_FULL_INSTANCES_LOADED

set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}
set_db enable_ui_precision true
set_db ui_precision_timing 6
set_db timing_analysis_type ocv
set_db timing_analysis_cppr both
set_db delaycal_enable_si true
set_db si_delay_enable_report true
set_db si_glitch_enable_report true
set_db timing_max_transition_use_si_transition true
set_db si_enable_drv_with_delta_slew true
set_db opt_post_route_report_si_transitions true
time_design -post_route -drv_report -expanded_views -report_dir $out/full_si -report_prefix full_si
set_ilm_type -model si
flatten_ilm
report_timing -view setup_slow -max_paths 1 > $out/worst_setup_slow.rpt
report_timing -view setup_typ -max_paths 1 > $out/worst_setup_typ.rpt
report_timing -early -view hold_fast -max_paths 1 > $out/worst_hold_fast.rpt
if {[llength [get_db insts]] != 1889420 || ![get_db delaycal_enable_si]} {
    error "Full-model analysis condition changed"
}
write_db $out/profile.db
exec python3 -B $root/.cache/physical/fingerprint_twenty_core_75.py
puts TRI_ORACLE_TWENTY75_FULL_CAPACITY_PROFILE_FINISHED
exit
