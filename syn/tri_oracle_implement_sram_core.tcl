# Standalone19KB core physical implementation; all28actual compiler macros.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set top tri_oracle_sram_memory_compute
set out $root/.cache/physical/pnr/$top
file mkdir $out
set_multi_cpu_usage -local_cpu 18
set_db design_process_node 28
set_db init_power_nets {VDD}
set_db init_ground_nets {VSS}
read_mmmc $root/syn/tri_oracle_sram_core_mmmc.tcl
read_physical -lefs [list {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator/.cache/physical/routing_kit/N28_PRTF_Cad_v1d5a/PR_tech/Cadence/LefHeader/VHV/tsmcn28_10lm5X2Y2ZUTRDL.tlef} {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator/.cache/physical/library/tcbn28hpcplusbwp12t40p140.lef} {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator/.cache/physical/sram/core_weights_masks_01/ts5n28hpcpsvta32x128m2fw_130a/LEF/ts5n28hpcpsvta32x128m2fw_130a.lef} {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator/.cache/physical/sram/core_outputs_01/ts6n28hpcpsvta16x128m2f_130a/LEF/ts6n28hpcpsvta16x128m2f_130a.lef} {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator/.cache/physical/sram/activation_cache_banks_01/ts5n28hpcpsvta512x64m4f_130a/LEF/ts5n28hpcpsvta512x64m4f_130a.lef}]
read_netlist $root/.cache/physical/synthesis/$top/netlist.v -top $top
init_design
if {[get_db current_design .name] ne $top} {error "Wrong physical top"}
set_db enable_ui_precision true
set_db ui_precision_timing 6
# Local700x650um core; macro geometry and5um halos are not paper die dimensions.
create_floorplan -site core12T -core_size {700 650 10 10 10 10}
set placed_macros [dict create]
foreach i [get_db insts] {dict set placed_macros [get_db $i .name] $i}
set inst [dict get $placed_macros {weights[0]}]
place_inst $inst 30 30 r0 -fixed
set inst [dict get $placed_macros {weights[1]}]
place_inst $inst 64 30 r0 -fixed
set inst [dict get $placed_macros {weights[2]}]
place_inst $inst 98 30 r0 -fixed
set inst [dict get $placed_macros {weights[3]}]
place_inst $inst 132 30 r0 -fixed
set inst [dict get $placed_macros {weights[4]}]
place_inst $inst 166 30 r0 -fixed
set inst [dict get $placed_macros {weights[5]}]
place_inst $inst 200 30 r0 -fixed
set inst [dict get $placed_macros {weights[6]}]
place_inst $inst 234 30 r0 -fixed
set inst [dict get $placed_macros {weights[7]}]
place_inst $inst 268 30 r0 -fixed
set inst [dict get $placed_macros {weights[8]}]
place_inst $inst 302 30 r0 -fixed
set inst [dict get $placed_macros {weights[9]}]
place_inst $inst 336 30 r0 -fixed
set inst [dict get $placed_macros {weights[10]}]
place_inst $inst 370 30 r0 -fixed
set inst [dict get $placed_macros {weights[11]}]
place_inst $inst 404 30 r0 -fixed
set inst [dict get $placed_macros {weights[12]}]
place_inst $inst 438 30 r0 -fixed
set inst [dict get $placed_macros {weights[13]}]
place_inst $inst 472 30 r0 -fixed
set inst [dict get $placed_macros {weights[14]}]
place_inst $inst 506 30 r0 -fixed
set inst [dict get $placed_macros {weights[15]}]
place_inst $inst 540 30 r0 -fixed
set inst [dict get $placed_macros {masks[0]}]
place_inst $inst 574 30 r0 -fixed
set inst [dict get $placed_macros {masks[1]}]
place_inst $inst 608 30 r0 -fixed
set inst [dict get $placed_macros {outputs[0]}]
place_inst $inst 30 300 r0 -fixed
set inst [dict get $placed_macros {outputs[1]}]
place_inst $inst 64 300 r0 -fixed
set inst [dict get $placed_macros {outputs[2]}]
place_inst $inst 98 300 r0 -fixed
set inst [dict get $placed_macros {outputs[3]}]
place_inst $inst 132 300 r0 -fixed
set inst [dict get $placed_macros {outputs[4]}]
place_inst $inst 166 300 r0 -fixed
set inst [dict get $placed_macros {outputs[5]}]
place_inst $inst 200 300 r0 -fixed
set inst [dict get $placed_macros {outputs[6]}]
place_inst $inst 234 300 r0 -fixed
set inst [dict get $placed_macros {outputs[7]}]
place_inst $inst 268 300 r0 -fixed
set inst [dict get $placed_macros {inputs[0]}]
place_inst $inst 350 300 r0 -fixed
set inst [dict get $placed_macros {inputs[1]}]
place_inst $inst 435 300 r0 -fixed
create_place_halo -halo_deltas {5 5 5 5} -snap_to_site -cell TS5N28HPCPSVTA32X128M2FW
create_place_halo -halo_deltas {5 5 5 5} -snap_to_site -cell TS6N28HPCPSVTA16X128M2F
create_place_halo -halo_deltas {5 5 5 5} -snap_to_site -cell TS5N28HPCPSVTA512X64M4F
set macro_names {{weights[0]} {weights[1]} {weights[2]} {weights[3]} {weights[4]} {weights[5]} {weights[6]} {weights[7]} {weights[8]} {weights[9]} {weights[10]} {weights[11]} {weights[12]} {weights[13]} {weights[14]} {weights[15]} {masks[0]} {masks[1]} {outputs[0]} {outputs[1]} {outputs[2]} {outputs[3]} {outputs[4]} {outputs[5]} {outputs[6]} {outputs[7]} {inputs[0]} {inputs[1]}}
connect_global_net VDD -type pg_pin -pin_base_name VDD -all
connect_global_net VSS -type pg_pin -pin_base_name VSS -all
add_rings -nets {VDD VSS} -type core_rings -follow core \
    -layer {top M8 bottom M8 left M9 right M9} -width 2 -spacing 2 -offset 2
add_stripes -nets {VDD VSS} -layer M7 -direction vertical \
    -width 1 -spacing 1 -set_to_set_distance 40 -start_offset 20
set pins [lsort [get_db ports .name]]
set count [llength $pins]
for {set i 0} {$i < 4} {incr i} {
    set first [expr {$i*$count/4}]
    set last [expr {($i+1)*$count/4-1}]
    edit_pin -pin [lrange $pins $first $last] -side [lindex {left right top bottom} $i] \
        -spread_type side -layer [lindex {M4 M4 M5 M5} $i] -snap track
}
place_opt_design
add_tieoffs -lib_cell {TIEHBWP12T40P140 TIELBWP12T40P140}
place_detail
# Macro supplies are M4; connect them as well as ordinary row power pins.
route_special -nets {VDD VSS} -connect {block_pin core_pin} -block_pin use_lef \
    -block_pin_target {ring stripe} -core_pin_target {ring stripe} \
    -allow_layer_change 1 -allow_jogging 1 -layer_change_range {M1 M9}
check_place > $out/placement_check.rpt
write_db $out/placed.db
puts TRI_ORACLE_SRAM_CORE_PLACEMENT_FINISHED
set_db cts_buffer_cells {CKBD1BWP12T40P140 CKBD2BWP12T40P140 CKBD4BWP12T40P140 CKBD8BWP12T40P140 CKBD12BWP12T40P140}
set_db cts_inverter_cells {CKND1BWP12T40P140 CKND2BWP12T40P140 CKND4BWP12T40P140 CKND8BWP12T40P140}
clock_opt_design -report_dir $out/clock_reports
write_db $out/clocked.db
route_design
write_db $out/routed_before_optimization.db
set_db timing_analysis_type ocv
set_db timing_analysis_cppr both
set_db opt_hold_target_slack 0.020
opt_design -post_route -setup -hold -report_dir $out/route_reports
write_db -rc_extract $out/routed.db
check_place > $out/final_placement.rpt
check_drc -out_file $out/prefix_power_drc.rpt
fix_via -min_cut
check_drc -out_file $out/route_drc.rpt
check_connectivity -type all -out_file $out/route_connectivity.rpt
check_antenna -out_file $out/antenna.rpt
write_db -rc_extract $out/routed_power_checked.db
report_area > $out/final_area.rpt
set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}
report_timing -view setup_slow -check_type setup > $out/export_setup_slow.rpt
report_timing -view setup_typ -check_type setup > $out/export_setup_typ.rpt
report_timing -early -view hold_fast > $out/export_hold_fast.rpt
write_netlist $out/routed_netlist.v -exclude_leaf_cells
write_def $out/routed.def -routing
write_parasitics -spef_file $out/rc_slow.spef -rc_corner rc_slow
write_parasitics -spef_file $out/rc_fast.spef -rc_corner rc_fast
set f [open $out/memory_placement.tsv w]
puts $f "instance\tmaster\tlocation\torientation\tstatus"
foreach name $macro_names {
    set inst [dict get $placed_macros $name]
    puts $f "$name\t[get_db $inst .base_cell.name]\t[get_db $inst .location]\t[get_db $inst .orient]\t[get_db $inst .place_status]"
}
close $f
puts TRI_ORACLE_SRAM_CORE_PHYSICAL_COMMANDS_FINISHED
exit
