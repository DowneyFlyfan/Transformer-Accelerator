# Standalone cache physical implementation with actual compiler memories.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set top tri_oracle_sram_activation_cache
set out $root/.cache/physical/pnr/$top
file mkdir $out
set_multi_cpu_usage -local_cpu 20
set_db design_process_node 28
set_db init_power_nets {VDD}
set_db init_ground_nets {VSS}
read_mmmc $root/syn/tri_oracle_sram_cache_mmmc.tcl
read_physical -lefs [list {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator/.cache/physical/routing_kit/N28_PRTF_Cad_v1d5a/PR_tech/Cadence/LefHeader/VHV/tsmcn28_10lm5X2Y2ZUTRDL.tlef} {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator/.cache/physical/library/tcbn28hpcplusbwp12t40p140.lef} {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator/.cache/physical/sram/activation_cache_banks_01/ts5n28hpcpsvta512x64m4f_130a/LEF/ts5n28hpcpsvta512x64m4f_130a.lef} {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator/.cache/physical/sram/activation_cache_banks_01/ts5n28hpcpsvta512x16m4f_130a/LEF/ts5n28hpcpsvta512x16m4f_130a.lef}]
read_netlist $root/.cache/physical/synthesis/$top/netlist.v -top $top
init_design
if {[get_db current_design .name] ne $top} {error "Wrong physical top"}
set_db enable_ui_precision true
set_db ui_precision_timing 6
# Local floorplan, not a claimed paper dimension. Both macros have 5um halos.
create_floorplan -site core12T -core_size {200 250 10 10 10 10}
place_inst activation_memory 30 30 r0 -fixed
place_inst metadata_memory 115 110 r0 -fixed
foreach name {activation_memory metadata_memory} {
    set inst [get_db insts $name]
    if {[llength $inst] != 1} {error "Expected exactly one real memory: $name"}
    create_place_halo -halo_deltas {5 5 5 5} -insts $name
}
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
puts TRI_ORACLE_SRAM_CACHE_PLACEMENT_FINISHED
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
check_drc -out_file $out/route_drc.rpt
check_connectivity -type all -out_file $out/route_connectivity.rpt
check_antenna -out_file $out/antenna.rpt
report_area > $out/final_area.rpt
report_timing -view setup_slow -check_type setup > $out/export_setup_slow.rpt
report_timing -view setup_typ -check_type setup > $out/export_setup_typ.rpt
report_timing -early -view hold_fast > $out/export_hold_fast.rpt
write_netlist $out/routed_netlist.v -exclude_leaf_cells
write_def $out/routed.def -routing
write_parasitics -spef_file $out/rc_slow.spef -rc_corner rc_slow
write_parasitics -spef_file $out/rc_fast.spef -rc_corner rc_fast
set f [open $out/memory_placement.tsv w]
puts $f "instance\tmaster\tlocation\torientation\tstatus"
foreach name {activation_memory metadata_memory} {
    set inst [get_db insts $name]
    puts $f "$name\t[get_db $inst .base_cell.name]\t[get_db $inst .location]\t[get_db $inst .orient]\t[get_db $inst .place_status]"
}
close $f
puts TRI_ORACLE_SRAM_CACHE_PHYSICAL_COMMANDS_FINISHED
exit
