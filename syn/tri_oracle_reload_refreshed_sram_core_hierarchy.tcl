# Fresh one-block ILM import. The wrapper adds no logic or replacement memories.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set top tri_oracle_sram_memory_compute
set base $root/.cache/physical/pnr/$top
set model $base/hierarchy_export_58
set out $base/hierarchy_probe_64
if {[file exists $out]} {error "Existing hierarchy probe"}
file mkdir $out
set_multi_cpu_usage -local_cpu 1
set_db design_process_node 28
set_db init_power_nets {VDD}
set_db init_ground_nets {VSS}
read_mmmc $base/routed_typical_repair_44.db/viewDefinition.tcl
# Rebind only the source SDC design context to this actual wrapper top.
update_constraint_mode -name functional -sdc_files [list $base/hierarchy_probe_63_inputs/functional.sdc]
read_physical -lefs [list \
    $root/.cache/physical/routing_kit/N28_PRTF_Cad_v1d5a/PR_tech/Cadence/LefHeader/VHV/tsmcn28_10lm5X2Y2ZUTRDL.tlef \
    $root/.cache/physical/library/tcbn28hpcplusbwp12t40p140.lef \
    $root/.cache/physical/sram/core_weights_masks_01/ts5n28hpcpsvta32x128m2fw_130a/LEF/ts5n28hpcpsvta32x128m2fw_130a.lef \
    $root/.cache/physical/sram/core_outputs_01/ts6n28hpcpsvta16x128m2f_130a/LEF/ts6n28hpcpsvta16x128m2f_130a.lef \
    $root/.cache/physical/sram/activation_cache_banks_01/ts5n28hpcpsvta512x64m4f_130a/LEF/ts5n28hpcpsvta512x64m4f_130a.lef \
    $model/core.lef]
read_netlist $base/hierarchy_probe_60_inputs/wrapper.v -top tri_oracle_sram_core_hierarchy_probe
init_design
if {[get_db current_design .name] ne {tri_oracle_sram_core_hierarchy_probe}} {error "Wrong probe top"}
if {[llength [get_db insts]] != 1} {error "Probe must contain one actual physical block"}
set block [get_db insts core0]
if {[get_db $block .base_cell.name] ne $top} {error "Wrong macro master"}
if {[llength [get_db $block .pins]] != 3158} {error "Missing imported macro signal pins"}
if {[llength [get_db ports]] != 3158} {error "Missing wrapper signal ports"}
create_floorplan -site core12T -die_size {799.955 750 20 20 20 20}
place_inst core0 40 40 r0 -fixed
connect_global_net VDD -type pg_pin -pin_base_name VDD -all
connect_global_net VSS -type pg_pin -pin_base_name VSS -all
read_ilm -cell $top -directory $model/ilm
# Establish actual parent placement through the native flow; keep core0 fixed.
place_design
report_ilm_status > $out/ilm_before_flatten.rpt
set_ilm_type -model si
flatten_ilm
report_ilm_status > $out/ilm_after_flatten.rpt
set file [open $out/clock_context_before_refresh.rpt w]
puts $file "clock_db_objects: [llength [get_db clocks]]"
puts $file "timing_clock_collection: [sizeof_collection [get_clocks]]"
puts $file "interactive_modes: [get_interactive_constraint_modes]"
close $file
# ILM flattening changes the mapped hierarchy. Reload the unchanged parent
# constraint mode through the native API after that mapping is established.
update_constraint_mode -name functional -sdc_files [list $base/hierarchy_probe_63_inputs/functional.sdc]
set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}
set file [open $out/clock_context_after_refresh.rpt w]
puts $file "clock_db_objects: [llength [get_db clocks]]"
puts $file "timing_clock_collection: [sizeof_collection [get_clocks]]"
puts $file "clock_names: [get_object_name [get_clocks]]"
puts $file "interactive_modes: [get_interactive_constraint_modes]"
close $file
if {[sizeof_collection [get_clocks]] < 1} {error "Parent timing clocks missing after constraint reload"}
check_timing -verbose -view setup_slow > $out/constraint_coverage.rpt
set file [open $out/import_inventory.rpt w]
puts $file "wrapper_ports: [llength [get_db ports]]"
puts $file "flattened_instances: [llength [get_db insts]]"
puts $file "analysis_views: [get_db analysis_views .name]"
close $file
set_multi_cpu_usage -local_cpu 19
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
source syn/tri_oracle_hierarchy_boundary_paths.tcl
tri_oracle_record_boundary_paths $out
# Boundary validation emits reports; database reuse requires separate hierarchical-link fingerprint support.
puts TRI_ORACLE_SRAM_CORE_HIERARCHY64_RELOADED
exit
