# Real mapped-parent import with local corner-cluster placement informed by Figure31.6.7.
# All original cores and banks remain; this import is not timing/routing signoff.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set top tri_oracle_predicted_feedforward_frame
set out $root/.cache/physical/pnr/tri_oracle_predicted_feedforward_private207
set core_base $root/.cache/physical/pnr/tri_oracle_sram_memory_compute
if {[file exists $out/macro_floorplan.db]} {error "Existing parent floorplan checkpoint"}
file mkdir $out
set_multi_cpu_usage -local_cpu 8
set_db design_process_node 28
set_db init_power_nets {VDD}
set_db init_ground_nets {VSS}
read_mmmc $root/syn/tri_oracle_private_frame207_mmmc.tcl
read_physical -lefs [list \
    $root/.cache/physical/routing_kit/N28_PRTF_Cad_v1d5a/PR_tech/Cadence/LefHeader/VHV/tsmcn28_10lm5X2Y2ZUTRDL.tlef \
    $root/.cache/physical/library/tcbn28hpcplusbwp12t40p140.lef \
    $root/.cache/physical/sram/core_weights_masks_01/ts5n28hpcpsvta32x128m2fw_130a/LEF/ts5n28hpcpsvta32x128m2fw_130a.lef \
    $root/.cache/physical/sram/core_outputs_01/ts6n28hpcpsvta16x128m2f_130a/LEF/ts6n28hpcpsvta16x128m2f_130a.lef \
    $root/.cache/physical/sram/activation_cache_banks_01/ts5n28hpcpsvta512x64m4f_130a/LEF/ts5n28hpcpsvta512x64m4f_130a.lef \
    $core_base/hierarchy_export_58/core.lef]
# The guarded launcher preserves the mapped text and appends the original empty
# core port declaration only when the library master has no Verilog declaration.
read_netlist $out/parent_import.v -top $top
init_design
if {[get_db current_design .name] ne $top} {error "Wrong mapped physical top"}
source $root/syn/tri_oracle_registered_reset_trace102.tcl
source $root/syn/tri_oracle_check_registered_reset_fabric.tcl
set registered_masters [exec python3 -B -c {import json,sys; print(" ".join(json.load(open(sys.argv[1]))["flip_flop_cells"]))} $root/records/registered_reset34_sequential_masters.json]
tri_oracle_require_parent_registered_resets $registered_masters $out/registered_reset_roots.tsv
create_floorplan -site core12T -no_snap_to_grid -die_size {3600 3600 20 20 20 20}
source $root/syn/tri_oracle_staged_frame123_floorplan.tcl
tri_oracle_place_staged_frame123_macros $out/macro_inventory.tsv
if {[llength [get_db insts]] <= 60} {error "Mapped parent controller logic is missing"}
if {[sizeof_collection [get_clocks core_clock]] == 0} {error "Mapped parent clock is missing"}
set inventory [open $out/parent_import_inventory.rpt w]
puts $inventory "parent_instances_without_core_internals: [llength [get_db insts]]"
puts $inventory "parent_port_bits: [llength [get_db ports]]"
puts $inventory "core_macros: 20"
puts $inventory "aggregate_banks: 40"
puts $inventory "clock_names: [get_object_name [get_clocks]]"
close $inventory
create_place_halo -halo_deltas {5 5 5 5} -snap_to_site -cell tri_oracle_sram_memory_compute
create_place_halo -halo_deltas {5 5 5 5} -snap_to_site -cell TS6N28HPCPSVTA16X128M2F
connect_global_net VDD -type pg_pin -pin_base_name VDD -all
connect_global_net VSS -type pg_pin -pin_base_name VSS -all
set pins [lsort [get_db ports .name]]
set count [llength $pins]
for {set side 0} {$side < 4} {incr side} {
    set first [expr {$side*$count/4}]
    set last [expr {($side+1)*$count/4-1}]
    edit_pin -pin [lrange $pins $first $last] -side [lindex {left right top bottom} $side] \
        -spread_type side -layer [lindex {M4 M4 M5 M5} $side] -snap track
}
set file [open $out/macro_floorplan_scope.rpt w]
puts $file "Mapped parent with twenty original-core LEF blocks and forty aggregate banks."
puts $file "Original core internals are not loaded at this checkpoint; full keep_all models68 are mandatory for subsequent physical timing and placement optimization."
puts $file "No timing, parent placement, power-grid, routing or paper-result qualification follows from this import stage."
close $file
puts "TRI_ORACLE_FRAME207_RESET_CHECK_SCOPE: registered connectivity only; new parent reset baseline and recovery/removal timing remain unqualified"
report_area > $out/macro_floorplan_area.rpt
write_def $out/macro_floorplan.def
write_db $out/macro_floorplan.db
puts TRI_ORACLE_RESUMED_FRAME207_MACRO_FLOORPLAN_FINISHED
exit
