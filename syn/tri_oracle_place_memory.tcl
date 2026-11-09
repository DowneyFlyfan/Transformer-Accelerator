source syn/tri_oracle_memory_physical_config.tcl
set_multi_cpu_usage -local_cpu 20
read_db $out/initialized.db
tri_oracle_require_memory_design
source syn/tri_oracle_release_memory_core.tcl
tri_oracle_release_memory_core
set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}
connect_global_net VDD -type pg_pin -pin_base_name VDD -all
connect_global_net VSS -type pg_pin -pin_base_name VSS -all
# Local floorplan and power-grid choices, not dimensions specified by the paper.
add_rings -nets {VDD VSS} -type core_rings -follow core \
    -layer {top M8 bottom M8 left M9 right M9} -width 2 -spacing 2 -offset 2
add_stripes -nets {VDD VSS} -layer M7 -direction vertical \
    -width 1 -spacing 1 -set_to_set_distance 40 -start_offset 20
set pins [lsort [get_db ports .name]]
set count [llength $pins]
for {set side_index 0} {$side_index < 4} {incr side_index} {
    set first [expr {$side_index*$count/4}]
    set last [expr {($side_index+1)*$count/4-1}]
    set side [lindex {left right top bottom} $side_index]
    set layer [lindex {M4 M4 M5 M5} $side_index]
    edit_pin -pin [lrange $pins $first $last] -side $side -spread_type side \
        -layer $layer -snap track
}
place_opt_design
add_tieoffs -lib_cell {TIEHBWP12T40P140 TIELBWP12T40P140}
place_detail
route_special -nets {VDD VSS} -connect {core_pin} -allow_layer_change 1 \
    -allow_jogging 1 -core_pin_target {ring stripe} -layer_change_range {M1 M9}
check_place > $out/placement_check.rpt
source syn/tri_oracle_require_clean_placement.tcl
tri_oracle_require_clean_placement $out/placement_check.rpt
report_timing > $out/prects_setup.rpt
write_db $out/placed.db
puts "TRI_ORACLE_PLACEMENT_FINISHED"
exit
