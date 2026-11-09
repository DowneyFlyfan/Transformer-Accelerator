# Four short supply-only extensions on a private copy of routed core44.
# Candidate corridors were checked against actual routed geometry by probe38.
# No placement, logical-net editing, signal routing or constraint relaxation.
set root {/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator}
set out $::env(TRI_ORACLE_PLACEMENT_PROBE_DIRECTORY)
read_db $root/.cache/physical/pnr/tri_oracle_sram_memory_compute/routed_typical_repair_44.db
set_multi_cpu_usage -local_cpu 4
if {[get_db current_design .name] ne "tri_oracle_sram_memory_compute" ||
    [llength [get_db insts]] != 94471} {error "CORE_POWER39_WRONG_REFERENCE"}
proc power39_cells {} {
    set rows {}
    foreach instance [get_db insts] {
        lappend rows [list [get_db $instance .name] [get_db $instance .base_cell.name] \
            [get_db $instance .location] [get_db $instance .orient] \
            [get_db $instance .place_status] [get_db $instance .dont_touch]]
    }
    return [lsort $rows]
}
proc power39_logic {} {
    set rows {}
    foreach net [get_db nets] {
        lappend rows [list [get_db $net .name] [lsort [get_db $net .pins.name]] \
            [lsort [get_db $net .driver_ports.name]] [lsort [get_db $net .load_ports.name]]]
    }
    return [lsort $rows]
}
set cells_before [power39_cells]
set logic_before [power39_logic]
write_def $out/before.def -routing
foreach {net rectangle} {
    VDD {5.99 663.0 7.99 670.0}
    VDD {711.85 663.0 713.85 670.0}
    VSS {1.99 667.0 3.99 670.0}
    VSS {715.85 667.0 717.85 670.0}
} {
    create_shape -net $net -layer M9 -shape stripe -status fixed -rect $rectangle
}
if {[power39_cells] ne $cells_before || [power39_logic] ne $logic_before} {
    error "CORE_POWER39_CHANGED_CELLS_OR_LOGIC"
}
set file [open $out/preservation.rpt w]
puts $file "original_cells: 94471"
puts $file "all_cell_names_masters_geometry_status_and_protection_preserved: true"
puts $file "all_logical_net_pin_and_port_connections_preserved: true"
puts $file "new_geometry: four fixed M9 supply rectangles in audited top-edge corridors"
close $file
write_def $out/after.def -routing
write_db $out/power_access_candidate.db
write_lef_abstract $out/core.lef -top_layer 10 -stripe_pins \
    -pg_pin_layers {8 9} -port_for_each_stripe_pin -extract_block_obs
check_place > $out/placement.rpt
source $root/syn/tri_oracle_require_clean_placement.tcl
tri_oracle_require_clean_placement $out/placement.rpt
check_drc -limit 100000 -out_file $out/route_drc.rpt
check_connectivity -type all -check_pg_ports -error 100000 -warning 100000 \
    -out_file $out/connectivity.rpt
check_antenna -out_file $out/antenna.rpt
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
time_design -post_route -expanded_views -drv_report -report_dir $out/timing -report_prefix power_access
set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}
set saved_check [get_db timing_analysis_check_type]
set file [open $out/slack_properties.tsv w]
puts $file "view\tslack_ns\tstartpoint\tendpoint"
foreach view {setup_slow setup_typ hold_fast} {
    set_db timing_analysis_check_type [expr {$view eq "hold_fast" ? "hold" : "setup"}]
    report_clocks -view $view -hierarchy -description -source_insertion > $out/clock_$view.rpt
    set command [list report_timing -view $view -max_paths 1 -max_slack 100]
    if {$view eq "hold_fast"} {lappend command -early} else {lappend command -check_type setup}
    eval $command > $out/timing_$view.rpt
    set paths [eval $command -collection]
    if {[sizeof_collection $paths] != 1} {error "CORE_POWER39_MISSING_REAL_CORNER_PATH: $view"}
    foreach_in_collection path $paths {
        puts $file "$view\t[get_property $path slack]\t[get_object_name [get_property $path launching_point]]\t[get_object_name [get_property $path capturing_point]]"
    }
}
close $file
set_db timing_analysis_check_type $saved_check
if {[power39_cells] ne $cells_before || [power39_logic] ne $logic_before} {
    error "CORE_POWER39_REPORTING_CHANGED_CELLS_OR_LOGIC"
}
puts TRI_ORACLE_CORE_POWER_ACCESS39_CANDIDATE_FINISHED
exit
